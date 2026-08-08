"""Authenticated HTTP client for the managed Mem0 OSS v5 lane."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_bounded_httpx_transport import (
    BoundedHttpxTransport,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    execute_managed_mem0_v5_clean_state,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_binding import (
    ManagedMem0V5CleanupBindingPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_evidence import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
    ManagedMem0V5EvidenceKeyCapability,
    ManagedMem0V5EvidenceVerifierPort,
    ManagedMem0V5SearchReceipt,
    ManagedMem0V5SearchRecord,
    ManagedMem0V5SearchVerificationContext,
    ManagedMem0V5StorageVerificationContext,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    REQUEST_BINDING_V2_SCHEMA,
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    ManagedMem0V5DispatchBindingPort,
    ManagedMem0V5DispatchBindingV2Port,
    ManagedMem0V5RequestBindingV2Context,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_collector import (
    ManagedMem0V5TransportObservationCollector,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5AdmitRequest,
    Mem0V5CleanStateScope,
    Mem0V5CleanupRequest,
    Mem0V5DispatchRequest,
    Mem0V5HttpError,
    Mem0V5HttpPort,
    Mem0V5StatusRequest,
    Mem0V5TransportPort,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssRunSeal
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_payload,
)
from infinity_context_server.memory_comparison_secret_validation import (
    is_bounded_text_secret,
)

_MAX_RESPONSE_BYTES = 256_000


class ManagedMem0V5BearerCapability(Protocol):
    def validate(self) -> None: ...

    def consume(self) -> str: ...


@final
class ManagedMem0V5HttpLane:
    __slots__ = (
        "_bearer",
        "_binding",
        "_admitted_runtime_binding",
        "_cleanup_binding",
        "_control",
        "_dispatch_guard",
        "_origin",
        "_timeout",
        "_transport",
        "_transport_collector",
        "_verifier",
    )

    def __init__(
        self,
        *,
        origin: str,
        bearer_capability: ManagedMem0V5BearerCapability,
        timeout_seconds: float,
        evidence_verifier: ManagedMem0V5EvidenceVerifierPort,
        dispatch_binding: ManagedMem0V5DispatchBindingV2Port,
        cleanup_binding: ManagedMem0V5CleanupBindingPort,
        dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
        transport: Mem0V5TransportPort | None = None,
    ) -> None:
        consume = _configuration_callable(bearer_capability, "consume")
        canonical_origin = _origin(origin)
        canonical_timeout = _timeout(timeout_seconds)
        verified_evidence = _evidence_verifier(evidence_verifier)
        verified_dispatch = _dispatch_binding(dispatch_binding)
        verified_cleanup = _cleanup_binding(cleanup_binding)
        verified_guard = _dispatch_guard(dispatch_guard)
        verified_transport = _transport_port(transport)
        try:
            _configuration_callable(bearer_capability, "validate")()
            bearer = consume()
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
        try:
            if not _secret(bearer):
                _fail("mem0_v5_managed_http_configuration_invalid")
            self._origin = canonical_origin
            self._timeout = canonical_timeout
            self._bearer = bearer
            self._transport = verified_transport
            self._verifier = verified_evidence
            self._binding = verified_dispatch
            self._cleanup_binding = verified_cleanup
            self._dispatch_guard = verified_guard
            self._transport_collector = ManagedMem0V5TransportObservationCollector()
            self._admitted_runtime_binding: tuple[str, str] | None = None
            self._control = Mem0V5HttpPort(
                origin=canonical_origin,
                bearer_token=bearer,
                timeout_seconds=canonical_timeout,
                transport=verified_transport,
            )
        except Exception:
            _close_capability(bearer_capability)
            raise

    @property
    def transport_observations(
        self,
    ) -> tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...]:
        return self._transport_collector.snapshot()

    def admit(
        self, *, authority: ManagedMem0V5ManifestAuthority, admission: Mem0OssFullRunAdmission
    ) -> object:
        request = Mem0V5AdmitRequest(
            admission.commitment_sha256,
            authority.ingestion_manifest_sha256,
            authority.ingestion_root_sha256,
            authority.operation_count,
            admission.request.route_sha256,
            _key("admit", admission.commitment_sha256),
        )
        result = self._control.admit(request)
        if result.admission_commitment_sha256 != admission.commitment_sha256 or not result.accepted:
            _fail("mem0_v5_managed_http_response_invalid")
        self._admitted_runtime_binding = (
            admission.commitment_sha256,
            result.runtime_binding_commitment_sha256,
        )
        return result

    def clean_state(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        scopes: tuple[Mem0V5CleanStateScope, ...],
    ) -> tuple[Mem0V5CleanStateScope, ...]:
        return execute_managed_mem0_v5_clean_state(
            authority=authority,
            admission=admission,
            scopes=scopes,
            admitted_runtime_binding=self._admitted_runtime_binding,
            control=self._control,
            verifier=self._verifier,
        )

    def dispatch(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object:
        binding = self._read_transport_observation(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        request_sha = binding.request_body_sha256
        if not is_sha256(request_sha):
            _fail("mem0_v5_managed_dispatch_binding_invalid")
        if self._dispatch_guard is not None:
            self._dispatch_guard.claim(
                admission_commitment_sha256=admission.commitment_sha256,
                operation_id_sha256=operation_id_sha256,
                request_body_sha256=request_sha,
            )
        result = self._control.dispatch(
            Mem0V5DispatchRequest(
                admission.commitment_sha256,
                operation_id_sha256,
                unit.unit_identity_sha256,
                unit.unit_sha256,
                unit.scope_sha256,
                request_sha,
                unit.sequence,
                _key("dispatch", operation_id_sha256),
            )
        )
        self._transport_collector.record(binding)
        return result

    def _read_transport_observation(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness:
        context = ManagedMem0V5RequestBindingV2Context.from_authority(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        body = {
            "schema_version": REQUEST_BINDING_V2_SCHEMA,
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id_sha256,
        }
        payload = self._post(
            "/v5/operations/request-binding",
            body,
            _key("request-binding", operation_id_sha256),
        )
        binding = self._binding.verify_request_binding_v2(
            payload=payload,
            context=context,
        )
        return binding

    def status(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object:
        result = self._control.status(
            Mem0V5StatusRequest(
                admission.commitment_sha256,
                operation_id_sha256,
                _key("status", operation_id_sha256),
            )
        )
        binding = self._read_transport_observation(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        self._transport_collector.record_idempotent(binding)
        return result

    def inspect_storage(
        self,
        *,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        body = {
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id_sha256,
        }
        payload = self._post(
            "/v5/operations/storage-observation",
            body,
            _key("observation", operation_id_sha256),
        )
        return self._verifier.verify_storage(
            payload=payload,
            context=ManagedMem0V5StorageVerificationContext(
                admission.commitment_sha256,
                operation_id_sha256,
                unit.unit_identity_sha256,
                unit.scope_sha256,
                unit.source_id,
                unit.source_sha256,
            ),
        )

    def search(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> ManagedMem0V5SearchReceipt:
        context = ManagedMem0V5SearchVerificationContext(
            admission.commitment_sha256,
            corpus_id,
            query,
            limit,
        )
        body = {
            "admission_commitment_sha256": admission.commitment_sha256,
            "corpus_id": corpus_id,
            "query": query,
            "limit": limit,
        }
        payload = self._post("/v5/runs/search", body, _key("search", canonical_sha256(body)))
        return self._verifier.verify_search(payload=payload, context=context)

    def cleanup(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
        context: CleanupVerificationContext | None = None,
    ) -> object:
        if context is None:
            context = self._cleanup_binding.cleanup_context(
                admission=admission,
                seal=seal,
                aborting=aborting,
            )
        if (
            context.admission_commitment_sha256 != admission.commitment_sha256
            or context.seal_commitment_sha256 != (None if seal is None else seal.commitment_sha256)
            or context.operation_root_sha256
            != (None if seal is None else seal.operation_root_sha256)
            or context.expected_operation_count != admission.request.expected_operation_count
            or context.aborting is not aborting
        ):
            _fail("mem0_v5_managed_cleanup_binding_invalid")
        body = cleanup_request_payload(context)
        return self._control.cleanup(
            Mem0V5CleanupRequest(
                body["admission_commitment_sha256"],
                body["seal_commitment_sha256"],
                body["operation_root_sha256"],
                body["operation_inventory_root_sha256"],
                body["expected_operation_count"],
                body["aborting"],
                _key("cleanup", canonical_sha256(body)),
            )
        )

    def _post(self, path: str, body: dict[str, object], idempotency_key: str) -> dict[str, object]:
        encoded = _canonical(body)
        headers = {
            "Authorization": "Bearer " + self._bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Request-Commitment-SHA256": hashlib.sha256(encoded).hexdigest(),
        }
        try:
            response = self._transport.request(
                "POST",
                self._origin + path,
                headers=headers,
                content=encoded,
                timeout=self._timeout,
                follow_redirects=False,
            )
            status = response.status_code
            reader = getattr(response, "read_bounded", None)
            if type(status) is not int or not callable(reader):  # noqa: E721
                raise TypeError("invalid bounded response port")
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed") from None
        try:
            content = reader(_MAX_RESPONSE_BYTES)
        except ValueError:
            raise Mem0V5HttpError("mem0_v5_http_response_invalid") from None
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed") from None
        if type(content) is not bytes:  # noqa: E721 - exact transport DTO required
            raise Mem0V5HttpError("mem0_v5_http_remote_failed")
        if status != 200:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed")
        if not 1 <= len(content) <= _MAX_RESPONSE_BYTES:
            raise Mem0V5HttpError("mem0_v5_http_response_invalid")
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Mem0V5HttpError("mem0_v5_http_response_invalid") from None
        if type(value) is not dict:  # noqa: E721 - exact JSON object required
            raise Mem0V5HttpError("mem0_v5_http_response_invalid")
        return value


@final
class _HttpxTransport(BoundedHttpxTransport):
    __slots__ = ()


def _canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        _fail("mem0_v5_managed_evidence_invalid")


def _origin(value: object) -> str:
    if type(value) is not str:  # noqa: E721 - exact configuration type required
        _fail("mem0_v5_managed_http_configuration_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _fail("mem0_v5_managed_http_configuration_invalid")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("mem0_v5_managed_http_configuration_invalid")
    return value.rstrip("/")


def _timeout(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or not 0.01 <= value <= 120:
        _fail("mem0_v5_managed_http_configuration_invalid")
    return float(value)


def _evidence_verifier(value: object) -> ManagedMem0V5EvidenceVerifierPort:
    _configuration_callable(value, "verify_storage")
    _configuration_callable(value, "verify_search")
    _configuration_callable(value, "verify_clean_state")
    return value


def _dispatch_binding(value: object) -> ManagedMem0V5DispatchBindingV2Port:
    _configuration_callable(value, "verify_request_binding_v2")
    return value


def _cleanup_binding(value: object) -> ManagedMem0V5CleanupBindingPort:
    _configuration_callable(value, "cleanup_context")
    return value


def _dispatch_guard(
    value: object,
) -> ManagedMem0V5SingleDispatchGuardPort | None:
    if value is None:
        return None
    _configuration_callable(value, "claim")
    return value


def _transport_port(value: object) -> Mem0V5TransportPort:
    try:
        selected = _HttpxTransport() if value is None else value
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
    _configuration_callable(selected, "request")
    return selected


def _configuration_callable(value: object, name: str) -> Callable[..., object]:
    try:
        candidate = getattr(value, name, None)
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
    if not callable(candidate):
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid")
    return candidate


def _close_capability(value: object) -> None:
    with suppress(Exception):
        close = getattr(value, "close", None)
        if callable(close):
            close()


def _key(kind: str, binding: str) -> str:
    return canonical_sha256({"kind": kind, "binding": binding})


def _secret(value: object) -> bool:
    return is_bounded_text_secret(value)


def _fail(code: str) -> None:
    if code in {
        "mem0_v5_managed_http_configuration_invalid",
        "mem0_v5_managed_storage_witness_authority_invalid",
    }:
        code = "mem0_v5_http_configuration_invalid"
    raise Mem0V5HttpError(code)


__all__ = (
    "HmacSha256ManagedMem0V5EvidenceVerifier",
    "ManagedMem0V5BearerCapability",
    "ManagedMem0V5CleanupBindingPort",
    "ManagedMem0V5DispatchBindingPort",
    "ManagedMem0V5DispatchBindingV2Port",
    "ManagedMem0V5EvidenceKeyCapability",
    "ManagedMem0V5EvidenceVerifierPort",
    "ManagedMem0V5HttpLane",
    "ManagedMem0V5SearchReceipt",
    "ManagedMem0V5SearchRecord",
    "ManagedMem0V5SingleDispatchGuardPort",
    "ManagedMem0V5SearchVerificationContext",
    "ManagedMem0V5StorageVerificationContext",
)
