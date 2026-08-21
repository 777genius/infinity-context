"""Authenticated provider-free runtime probe for Docker acceptance."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import socket
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from .config import BASE_INSTRUCTIONS_SHA256, PublishableLaneConfig
from .immutable_evidence import (
    ImmutableJsonEvidence,
    require_immutable_json_unchanged,
    write_immutable_json,
)

_REQUEST_SCHEMA: Final = "mem0-oss-adapter-v5.runtime-attestation-request.v1"
_RESPONSE_SCHEMA: Final = "mem0-oss-adapter-v5.runtime-attestation.v1"
_IMPLEMENTATION_SCHEMA: Final = "mem0-oss-adapter-v5.implementation-binding.v1"
_ATTESTATION_PATH: Final = "/v5/runtime/attest"
_AUTHENTICATION_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-authentication/v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response-key/v1"
_IDEMPOTENCY_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-idempotency/v1\0"
_SIGNATURE_DOMAIN = b"mem0-oss-adapter-v5/runtime-attestation-response/v1\0"
_EVIDENCE_PREFIX: Final = "provider-attestation-"
_EVIDENCE_SCHEMA: Final = "publishable-mem0-v5-provider-attestation-evidence.v1"
_SECRET_FILE: Final = "runtime-attestation-secret"
_VALIDITY_SECONDS = 1_200
_HTTP_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_HEADERS_BYTES = 16 * 1024
_MAX_RESPONSE_BYTES = 32 * 1024
_ROUTE_CONTRACT_SHA256: Final = "7ed6947e7694feebff43e5b33e1c99b462462c437be808d078442c4aaac0bf49"
_RUNTIME_TRANSPORT_ORIGIN_SHA256: Final = hashlib.sha256(b"http://127.0.0.1:8891").hexdigest()
_DYNAMIC_IMPLEMENTATION_KEYS = {
    "attestation_hmac_sha256",
    "expires_at_unix",
    "implementation_binding_sha256",
    "issued_at_unix",
    "probe_nonce_sha256",
    "provider_calls",
    "run_id_sha256",
    "schema_version",
    "service",
    "target_origin_sha256",
}
_RESPONSE_KEYS = {
    "attestation_hmac_sha256",
    "expected_account_binding_hmac_sha256",
    "expected_base_instructions_sha256",
    "expires_at_unix",
    "extraction_response_format_sha256",
    "extraction_response_schema_sha256",
    "extraction_system_prompt_sha256",
    "implementation_binding_sha256",
    "issued_at_unix",
    "output_limit_enforced",
    "phase_c_infinity_commit_sha1",
    "phase_c_infinity_tree_sha1",
    "phase_c_release_manifest_sha256",
    "probe_nonce_sha256",
    "provider_calls",
    "requested_output_tokens",
    "route_contract_sha256",
    "run_id_sha256",
    "runtime_binding_commitment_sha256",
    "runtime_route_binding_sha256",
    "runtime_source_sha256",
    "runtime_transport_origin_sha256",
    "schema_version",
    "service",
    "source_closure_sha256",
    "source_commit_sha1",
    "source_manifest_sha256",
    "source_tree_sha1",
    "subscription_runtime_binding_commitment_sha256",
    "target_origin_sha256",
    "usage_attestation_required",
}


class ProviderAttestationError(RuntimeError):
    """Stable failure at the authenticated provider-free probe boundary."""


class RuntimeProbeTransport(Protocol):
    def post(
        self,
        *,
        host: str,
        port: int,
        path: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class LoopbackRuntimeProbeTransport:
    timeout_seconds: float = _HTTP_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0.001 <= float(self.timeout_seconds) <= _HTTP_TIMEOUT_SECONDS
        ):
            _fail("publishable_provider_attestation_timeout_invalid")

    def post(
        self,
        *,
        host: str,
        port: int,
        path: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> bytes:
        if host != "127.0.0.1" or path != _ATTESTATION_PATH:
            _fail("publishable_provider_attestation_target_invalid")
        request = _http_request(
            host=host,
            port=port,
            path=path,
            body=body,
            headers=headers,
        )
        deadline = time.monotonic() + float(self.timeout_seconds)
        connection: socket.socket | None = None
        try:
            connection = socket.create_connection(
                (host, port),
                timeout=_remaining_seconds(deadline),
            )
            _send_until_complete(connection, request, deadline=deadline)
            header, initial_body = _receive_headers(connection, deadline=deadline)
            status, content_length = _parse_response_headers(header)
            if status != 200:
                _fail("publishable_provider_attestation_http_failed")
            if content_length > _MAX_RESPONSE_BYTES:
                _fail("publishable_provider_attestation_response_too_large")
            raw = _receive_body(
                connection,
                initial=initial_body,
                content_length=content_length,
                deadline=deadline,
            )
        except ProviderAttestationError:
            raise
        except (OSError, TimeoutError) as exc:
            raise ProviderAttestationError("publishable_provider_attestation_unavailable") from exc
        finally:
            if connection is not None:
                connection.close()
        return raw


@dataclass(frozen=True, slots=True)
class ProviderAttestationEvidence:
    immutable: ImmutableJsonEvidence
    fleet_mode: str
    runtime_attestation_sha256: str
    target_origin_sha256: str
    run_id_sha256: str
    probe_nonce_sha256: str
    source_commit_sha1: str
    source_tree_sha1: str
    phase_c_infinity_commit_sha1: str
    phase_c_infinity_tree_sha1: str
    implementation_binding_sha256: str

    @property
    def commitment_sha256(self) -> str:
        return self.immutable.commitment_sha256

    @property
    def path(self) -> Path:
        return self.immutable.path

    def authority_identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_commit_sha1,
            self.source_tree_sha1,
            self.phase_c_infinity_commit_sha1,
            self.phase_c_infinity_tree_sha1,
            self.implementation_binding_sha256,
        )


class ProviderFreeRuntimeProbe(Protocol):
    def attest(
        self,
        *,
        fleet_mode: str,
        runtime_attestation_sha256: str,
    ) -> ProviderAttestationEvidence: ...

    def require_unchanged(
        self,
        evidence: ProviderAttestationEvidence,
    ) -> ProviderAttestationEvidence: ...


class ProviderFreeRuntimeAttestor:
    """Make one authenticated loopback call and independently verify its HMAC."""

    def __init__(
        self,
        config: PublishableLaneConfig,
        *,
        expected_uid: int,
        expected_gid: int,
        transport: RuntimeProbeTransport | None = None,
        clock: Callable[[], float] = time.time,
        nonce: Callable[[int], bytes] = os.urandom,
    ) -> None:
        if (
            type(config) is not PublishableLaneConfig
            or type(expected_uid) is not int
            or expected_uid < 0
            or type(expected_gid) is not int
            or expected_gid < 0
            or not callable(clock)
            or not callable(nonce)
        ):
            _fail("publishable_provider_attestation_input_invalid")
        self._config = config
        self._expected_uid = expected_uid
        self._expected_gid = expected_gid
        self._transport = transport or LoopbackRuntimeProbeTransport()
        self._clock = clock
        self._nonce = nonce

    def attest(
        self,
        *,
        fleet_mode: str,
        runtime_attestation_sha256: str,
    ) -> ProviderAttestationEvidence:
        if fleet_mode not in {"create", "reopen"} or not _sha256(runtime_attestation_sha256):
            _fail("publishable_provider_attestation_input_invalid")
        target = self._target_identity()
        run_id = self._run_identity(
            fleet_mode=fleet_mode,
            runtime_attestation_sha256=runtime_attestation_sha256,
        )
        try:
            nonce_raw = self._nonce(32)
            if type(nonce_raw) is not bytes or len(nonce_raw) != 32:
                raise ValueError
            nonce = hashlib.sha256(nonce_raw).hexdigest()
        except Exception as exc:
            raise ProviderAttestationError("publishable_provider_attestation_nonce_failed") from exc
        request = {
            "probe_nonce_sha256": nonce,
            "run_id_sha256": run_id,
            "schema_version": _REQUEST_SCHEMA,
            "target_origin_sha256": target,
            "validity_seconds": _VALIDITY_SECONDS,
        }
        request_raw = _canonical_json(request)
        request_sha256 = hashlib.sha256(request_raw).hexdigest()
        secret = self._read_secret()
        try:
            authentication = hmac.new(
                secret,
                _AUTHENTICATION_DOMAIN,
                hashlib.sha256,
            ).hexdigest()
            idempotency = hashlib.sha256(
                _IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha256)
            ).hexdigest()
            raw = self._transport.post(
                host="127.0.0.1",
                port=self._config.host_adapter_port,
                path=_ATTESTATION_PATH,
                body=request_raw,
                headers={
                    "Authorization": f"Bearer {authentication}",
                    "Connection": "close",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency,
                    "X-Request-Commitment-SHA256": request_sha256,
                },
            )
            payload = _decode_response(raw)
            self._validate_payload(
                payload,
                secret=secret,
                target=target,
                run_id=run_id,
                nonce=nonce,
                require_current=True,
            )
        finally:
            secret[:] = b"\0" * len(secret)
        immutable = write_immutable_json(
            directory=self._config.paths.attestation_dir,
            prefix=_EVIDENCE_PREFIX,
            payload={
                "fleet_mode": fleet_mode,
                "response": payload,
                "runtime_attestation_sha256": runtime_attestation_sha256,
                "schema_version": _EVIDENCE_SCHEMA,
            },
            expected_uid=self._expected_uid,
            expected_gid=self._expected_gid,
        )
        return self._evidence(immutable)

    def require_unchanged(
        self,
        evidence: ProviderAttestationEvidence,
    ) -> ProviderAttestationEvidence:
        if type(evidence) is not ProviderAttestationEvidence:
            _fail("publishable_provider_attestation_input_invalid")
        immutable = require_immutable_json_unchanged(
            evidence.immutable,
            directory=self._config.paths.attestation_dir,
            prefix=_EVIDENCE_PREFIX,
            expected_uid=self._expected_uid,
            expected_gid=self._expected_gid,
        )
        observed = self._evidence(immutable)
        secret = self._read_secret()
        try:
            self._validate_payload(
                _evidence_response(immutable.payload),
                secret=secret,
                target=self._target_identity(),
                run_id=self._run_identity(
                    fleet_mode=observed.fleet_mode,
                    runtime_attestation_sha256=observed.runtime_attestation_sha256,
                ),
                nonce=observed.probe_nonce_sha256,
                require_current=False,
            )
        finally:
            secret[:] = b"\0" * len(secret)
        if observed != evidence:
            _fail("publishable_provider_attestation_changed")
        return observed

    def _evidence(
        self,
        immutable: ImmutableJsonEvidence,
    ) -> ProviderAttestationEvidence:
        wrapper = immutable.payload
        if (
            set(wrapper)
            != {"fleet_mode", "response", "runtime_attestation_sha256", "schema_version"}
            or wrapper.get("schema_version") != _EVIDENCE_SCHEMA
            or wrapper.get("fleet_mode") not in {"create", "reopen"}
            or not _sha256(wrapper.get("runtime_attestation_sha256"))
        ):
            _fail("publishable_provider_attestation_evidence_invalid")
        value = _evidence_response(wrapper)
        fleet_mode = str(wrapper["fleet_mode"])
        runtime_attestation_sha256 = str(wrapper["runtime_attestation_sha256"])
        if value.get("target_origin_sha256") != self._target_identity() or value.get(
            "run_id_sha256"
        ) != self._run_identity(
            fleet_mode=fleet_mode,
            runtime_attestation_sha256=runtime_attestation_sha256,
        ):
            _fail("publishable_provider_attestation_evidence_invalid")
        return ProviderAttestationEvidence(
            immutable=immutable,
            fleet_mode=fleet_mode,
            runtime_attestation_sha256=runtime_attestation_sha256,
            target_origin_sha256=str(value["target_origin_sha256"]),
            run_id_sha256=str(value["run_id_sha256"]),
            probe_nonce_sha256=str(value["probe_nonce_sha256"]),
            source_commit_sha1=str(value["source_commit_sha1"]),
            source_tree_sha1=str(value["source_tree_sha1"]),
            phase_c_infinity_commit_sha1=str(value["phase_c_infinity_commit_sha1"]),
            phase_c_infinity_tree_sha1=str(value["phase_c_infinity_tree_sha1"]),
            implementation_binding_sha256=str(value["implementation_binding_sha256"]),
        )

    def _target_identity(self) -> str:
        return hashlib.sha256(
            f"http://127.0.0.1:{self._config.host_adapter_port}".encode("ascii")
        ).hexdigest()

    def _run_identity(
        self,
        *,
        fleet_mode: str,
        runtime_attestation_sha256: str,
    ) -> str:
        return hashlib.sha256(
            (
                "publishable-docker-acceptance:"
                f"{self._config.project_name}:{fleet_mode}:{runtime_attestation_sha256}"
            ).encode("ascii")
        ).hexdigest()

    def _validate_payload(
        self,
        payload: dict[str, object],
        *,
        secret: bytearray,
        target: str,
        run_id: str,
        nonce: str,
        require_current: bool,
    ) -> None:
        if (
            set(payload) != _RESPONSE_KEYS
            or payload.get("schema_version") != _RESPONSE_SCHEMA
            or payload.get("service") != "mem0-oss-adapter-v5"
            or payload.get("route_contract_sha256") != _ROUTE_CONTRACT_SHA256
            or payload.get("target_origin_sha256") != target
            or payload.get("run_id_sha256") != run_id
            or payload.get("probe_nonce_sha256") != nonce
            or payload.get("source_manifest_sha256") != self._config.source_manifest_sha256
            or payload.get("runtime_transport_origin_sha256") != _RUNTIME_TRANSPORT_ORIGIN_SHA256
            or payload.get("expected_account_binding_hmac_sha256")
            != self._config.bridges[0].account_binding_hmac_sha256
            or payload.get("expected_base_instructions_sha256") != BASE_INSTRUCTIONS_SHA256
            or type(payload.get("requested_output_tokens")) is not int
            or payload.get("requested_output_tokens") != 4096
            or payload.get("output_limit_enforced") is not False
            or payload.get("usage_attestation_required") is not False
            or type(payload.get("provider_calls")) is not int
            or payload.get("provider_calls") != 0
        ):
            _fail("publishable_provider_attestation_invalid")
        sha1_keys = (
            "source_commit_sha1",
            "source_tree_sha1",
            "phase_c_infinity_commit_sha1",
            "phase_c_infinity_tree_sha1",
        )
        if any(not _sha1(payload.get(key)) for key in sha1_keys):
            _fail("publishable_provider_attestation_invalid")
        ignored_hashes = {*sha1_keys, "attestation_hmac_sha256"}
        if any(
            not _sha256(value)
            for key, value in payload.items()
            if key.endswith("_sha256") and key not in ignored_hashes
        ) or not _sha256(payload.get("attestation_hmac_sha256")):
            _fail("publishable_provider_attestation_invalid")
        issued = payload.get("issued_at_unix")
        expires = payload.get("expires_at_unix")
        if (
            type(issued) is not int
            or type(expires) is not int
            or issued < 1
            or expires < 1
            or expires - issued != _VALIDITY_SECONDS
        ):
            _fail("publishable_provider_attestation_invalid")
        if require_current:
            try:
                raw_now = self._clock()
                if isinstance(raw_now, bool) or not isinstance(raw_now, int | float):
                    raise ValueError
                now = float(raw_now)
            except Exception:
                _fail("publishable_provider_attestation_clock_invalid")
            if not math.isfinite(now) or not issued <= int(now) <= expires:
                _fail("publishable_provider_attestation_expired")
        static = {
            key: value for key, value in payload.items() if key not in _DYNAMIC_IMPLEMENTATION_KEYS
        }
        implementation = hashlib.sha256(
            _canonical_json({"schema_version": _IMPLEMENTATION_SCHEMA, **static})
        ).hexdigest()
        if not hmac.compare_digest(
            implementation,
            str(payload.get("implementation_binding_sha256")),
        ):
            _fail("publishable_provider_attestation_implementation_invalid")
        signed = dict(payload)
        presented = str(signed.pop("attestation_hmac_sha256"))
        signing_key = hmac.new(secret, _KEY_DOMAIN, hashlib.sha256).digest()
        expected = hmac.new(
            signing_key,
            _SIGNATURE_DOMAIN + _canonical_json(signed),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, presented):
            _fail("publishable_provider_attestation_authentication_invalid")

    def _read_secret(self) -> bytearray:
        path = self._config.paths.adapter_secret_dir / _SECRET_FILE
        descriptor: int | None = None
        raw: bytearray | None = None
        try:
            before = path.lstat()
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_uid, opened.st_gid) != (self._expected_uid, self._expected_gid)
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                or not 32 <= opened.st_size <= 4_096
            ):
                _fail("publishable_provider_attestation_secret_unsafe")
            raw = bytearray(os.read(descriptor, 4_097))
            final = os.fstat(descriptor)
            if len(raw) != opened.st_size or (opened.st_size, opened.st_mtime_ns) != (
                final.st_size,
                final.st_mtime_ns,
            ):
                _fail("publishable_provider_attestation_secret_changed")
        except ProviderAttestationError:
            if raw is not None:
                raw[:] = b"\0" * len(raw)
            raise
        except OSError as exc:
            if raw is not None:
                raw[:] = b"\0" * len(raw)
            raise ProviderAttestationError(
                "publishable_provider_attestation_secret_unavailable"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if raw is None:
            _fail("publishable_provider_attestation_secret_unavailable")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raw[:] = b"\0" * len(raw)
            _fail("publishable_provider_attestation_secret_invalid")
        if not text or text != text.strip():
            raw[:] = b"\0" * len(raw)
            _fail("publishable_provider_attestation_secret_invalid")
        return raw


def _http_request(
    *,
    host: str,
    port: int,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
) -> bytes:
    values = {"Host": f"{host}:{port}", "Content-Length": str(len(body)), **headers}
    if (
        type(port) is not int
        or not 1 <= port <= 65_535
        or type(body) is not bytes
        or any(
            type(name) is not str
            or type(value) is not str
            or not name
            or not name.replace("-", "").isalnum()
            or "\r" in value
            or "\n" in value
            for name, value in values.items()
        )
        or len({name.casefold() for name in values}) != len(values)
    ):
        _fail("publishable_provider_attestation_request_invalid")
    try:
        head = "\r\n".join(
            (f"POST {path} HTTP/1.1", *(f"{name}: {value}" for name, value in values.items()))
        ).encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProviderAttestationError("publishable_provider_attestation_request_invalid") from exc
    return head + b"\r\n\r\n" + body


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        _fail("publishable_provider_attestation_unavailable")
    return remaining


def _send_until_complete(connection: socket.socket, value: bytes, *, deadline: float) -> None:
    view = memoryview(value)
    while view:
        connection.settimeout(_remaining_seconds(deadline))
        sent = connection.send(view)
        if sent <= 0:
            _fail("publishable_provider_attestation_unavailable")
        view = view[sent:]


def _receive_headers(connection: socket.socket, *, deadline: float) -> tuple[bytes, bytes]:
    received = bytearray()
    marker = b"\r\n\r\n"
    while marker not in received:
        if len(received) > _MAX_RESPONSE_HEADERS_BYTES:
            _fail("publishable_provider_attestation_response_invalid")
        connection.settimeout(_remaining_seconds(deadline))
        chunk = connection.recv(min(4_096, _MAX_RESPONSE_HEADERS_BYTES + 1 - len(received)))
        if not chunk:
            _fail("publishable_provider_attestation_unavailable")
        received.extend(chunk)
    header, body = bytes(received).split(marker, 1)
    if len(header) > _MAX_RESPONSE_HEADERS_BYTES:
        _fail("publishable_provider_attestation_response_invalid")
    return header, body


def _parse_response_headers(value: bytes) -> tuple[int, int]:
    try:
        lines = value.decode("latin-1").split("\r\n")
    except UnicodeDecodeError as exc:
        raise ProviderAttestationError("publishable_provider_attestation_response_invalid") from exc
    if not lines or not lines[0].startswith("HTTP/1.1 "):
        _fail("publishable_provider_attestation_response_invalid")
    status_parts = lines[0].split(" ", 2)
    if len(status_parts) < 2 or len(status_parts[1]) != 3 or not status_parts[1].isdigit():
        _fail("publishable_provider_attestation_response_invalid")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or line[0].isspace() or ":" not in line:
            _fail("publishable_provider_attestation_response_invalid")
        name, raw = line.split(":", 1)
        normalized = name.casefold()
        if not name.replace("-", "").isalnum() or normalized in headers:
            _fail("publishable_provider_attestation_response_invalid")
        headers[normalized] = raw.strip()
    if "transfer-encoding" in headers or set(headers) & {"content-range"}:
        _fail("publishable_provider_attestation_response_invalid")
    length = headers.get("content-length")
    if length is None or not length.isascii() or not length.isdigit() or len(length) > 10:
        _fail("publishable_provider_attestation_response_invalid")
    return int(status_parts[1]), int(length)


def _receive_body(
    connection: socket.socket,
    *,
    initial: bytes,
    content_length: int,
    deadline: float,
) -> bytes:
    if len(initial) > content_length:
        _fail("publishable_provider_attestation_response_invalid")
    received = bytearray(initial)
    while len(received) < content_length:
        connection.settimeout(_remaining_seconds(deadline))
        chunk = connection.recv(min(4_096, content_length - len(received)))
        if not chunk:
            _fail("publishable_provider_attestation_unavailable")
        received.extend(chunk)
    return bytes(received)


def _evidence_response(value: dict[str, object]) -> dict[str, object]:
    response = value.get("response")
    if type(response) is not dict:
        _fail("publishable_provider_attestation_evidence_invalid")
    return response


def _decode_response(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ProviderAttestationError,
        ValueError,
    ) as exc:
        raise ProviderAttestationError("publishable_provider_attestation_response_invalid") from exc
    if type(value) is not dict:
        _fail("publishable_provider_attestation_response_invalid")
    return value


def _unique_object(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            _fail("publishable_provider_attestation_response_invalid")
        result[key] = value
    return result


def _invalid_json_constant(_value: str) -> object:
    raise ValueError("invalid JSON constant")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha1(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise ProviderAttestationError(code)


__all__ = (
    "LoopbackRuntimeProbeTransport",
    "ProviderAttestationError",
    "ProviderAttestationEvidence",
    "ProviderFreeRuntimeAttestor",
    "ProviderFreeRuntimeProbe",
    "RuntimeProbeTransport",
)
