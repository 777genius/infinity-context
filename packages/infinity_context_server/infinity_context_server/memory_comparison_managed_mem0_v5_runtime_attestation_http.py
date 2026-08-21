"""Provider-free pre-readiness attestation client for the managed Mem0 v5 adapter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAuthorityDescriptor,
    _register_pending_managed_mem0_runtime_authority,
    _reserved_managed_mem0_runtime_deadline_lease_is_available,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    _AUTH_DOMAIN,
    _IDEMPOTENCY_DOMAIN,
    ATTESTATION_PATH,
    REQUEST_SCHEMA,
    ManagedMem0V5ExpectedRuntimeAuthority,
    ManagedMem0V5RuntimeAttestationHttpError,
    VerifiedManagedMem0V5RuntimeAttestationValidation,
    _canonical_sha256,
    _configuration_invalid,
    _is_sha256,
    _unique_object,
    _verify_and_issue,
    expected_managed_mem0_v5_runtime_authority_from_pin,
    managed_mem0_v5_runtime_validation_is_publishable,
    public_managed_mem0_v5_runtime_validation,
)
from infinity_context_server.memory_comparison_probe_transport import (
    VettedProbeTransport,
    vet_probe_target,
)

_ADAPTER_ID = "managed.mem0.v5.runtime.http.v1"
_SOURCE_NAMES = (
    "memory_comparison_managed_mem0_v5_runtime_attestation.py",
    "memory_comparison_managed_mem0_v5_runtime_attestation_http.py",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@final
class ManagedMem0V5RuntimeAttestationPort:
    """One network attempt before readiness, then exact local one-shot consumption."""

    __slots__ = (
        "__authority_descriptor",
        "__base_url",
        "__consumed",
        "__deadline_monotonic",
        "__expected_authority",
        "__implementation_sha256",
        "__lock",
        "__monotonic_clock",
        "__prevalidated",
        "__prevalidation_attempted",
        "__root_secret",
        "__target_identity_sha256",
        "__timeout_seconds",
        "__transport",
        "__wall_clock",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        base_url: str,
        runtime_attestation_root_secret: str,
        probe_nonce_sha256: str,
        expected_authority: ManagedMem0V5ExpectedRuntimeAuthority,
        timeout_seconds: float,
        deadline_budget_seconds: float,
        monotonic_clock: Callable[[], float],
        expected_implementation_sha256: str,
        allowed_target_hosts: Sequence[str] = (),
        vetted_transport: VettedProbeTransport | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        implementation = _trusted_implementation_sha256(expected_implementation_sha256)
        secret = _private_secret(runtime_attestation_root_secret)
        timeout = _seconds(timeout_seconds, 120.0)
        deadline_budget = _seconds(deadline_budget_seconds, 7_200.0)
        if (
            type(expected_authority) is not ManagedMem0V5ExpectedRuntimeAuthority
            or not callable(monotonic_clock)
            or not callable(wall_clock)
            or not _is_sha256(probe_nonce_sha256)
        ):
            _configuration_invalid()
        try:
            started = float(monotonic_clock())
        except Exception:
            _configuration_invalid()
        target = vet_probe_target(
            base_url, allowed_hosts=allowed_target_hosts, vetted_transport=vetted_transport
        )
        if target is None:
            raise ManagedMem0V5RuntimeAttestationHttpError("managed_mem0_v5_runtime_target_unsafe")
        self.__base_url = target.base_url
        self.__target_identity_sha256 = target.identity_sha256
        self.__transport = target.transport
        self.__timeout_seconds = timeout
        self.__deadline_monotonic = started + deadline_budget
        self.__monotonic_clock = monotonic_clock
        self.__wall_clock = wall_clock
        self.__expected_authority = expected_authority
        self.__implementation_sha256 = implementation
        self.__root_secret = secret
        self.__lock = threading.Lock()
        self.__prevalidated: (
            tuple[str, str, str, VerifiedManagedMem0V5RuntimeAttestationValidation] | None
        ) = None
        self.__prevalidation_attempted = False
        self.__consumed = False
        self.__authority_descriptor = ManagedMem0RuntimeAuthorityDescriptor(
            adapter_id=_ADAPTER_ID,
            implementation_sha256=implementation,
            target_identity_sha256=target.identity_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            probe_token_credential_binding_id="sha256:" + hashlib.sha256(secret).hexdigest(),
            request_timeout_seconds=timeout,
            deadline_policy=MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
            deadline_budget_seconds=deadline_budget,
            minimum_network_timeout_seconds=0.001,
            max_attempts=1,
            expected_runtime_mode="oss",
        )
        _register_pending_managed_mem0_runtime_authority(
            self,
            self.__authority_descriptor,
            monotonic_clock=monotonic_clock,
            deadline_monotonic=self.__deadline_monotonic,
        )

    def __repr__(self) -> str:
        return "ManagedMem0V5RuntimeAttestationPort(<sealed>)"

    @property
    def adapter_id(self) -> str:
        return _ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return self.__implementation_sha256

    def authority_descriptor(self) -> ManagedMem0RuntimeAuthorityDescriptor:
        with self.__lock:
            if self.__consumed:
                _already_used()
            return self.__authority_descriptor

    def prevalidate(
        self, *, run_id: str, probe_nonce_sha256: str, target_identity_sha256: str
    ) -> None:
        """Perform and seal the only HTTP attempt before any provider readiness call."""

        self.__require_binding(run_id, probe_nonce_sha256, target_identity_sha256)
        with self.__lock:
            if self.__consumed or self.__prevalidated is not None or self.__prevalidation_attempted:
                _already_used()
            self.__prevalidation_attempted = True
            remaining = self.__remaining_seconds()
            validity_seconds = math.ceil(min(remaining, 7_200.0))
            root_secret = bytes(self.__root_secret)
            self.__root_secret[:] = b"\0" * len(self.__root_secret)
        request = {
            "schema_version": REQUEST_SCHEMA,
            "target_origin_sha256": target_identity_sha256,
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": probe_nonce_sha256,
            "validity_seconds": validity_seconds,
        }
        try:
            auth = hmac.new(root_secret, _AUTH_DOMAIN, hashlib.sha256).hexdigest()
            response = asyncio.run(
                _post_attestation(
                    transport=self.__transport,
                    base_url=self.__base_url,
                    timeout_seconds=min(self.__timeout_seconds, remaining),
                    bearer_token=auth,
                    request=request,
                )
            )
            capability = _verify_and_issue(
                response,
                request=request,
                root_secret=root_secret,
                expected_authority=self.__expected_authority,
                now_unix=self.__wall_now(),
            )
        except ManagedMem0V5RuntimeAttestationHttpError:
            raise
        except Exception:
            raise ManagedMem0V5RuntimeAttestationHttpError(
                "managed_mem0_v5_runtime_probe_failed"
            ) from None
        finally:
            root_secret = b""
        with self.__lock:
            if self.__consumed or self.__prevalidated is not None:
                _already_used()
            self.__prevalidated = (
                run_id,
                probe_nonce_sha256,
                target_identity_sha256,
                capability,
            )

    def attest(
        self, *, run_id: str, probe_nonce_sha256: str, target_identity_sha256: str
    ) -> object:
        """Consume only the exact prefetched capability, with no second request or TTL test."""

        self.__require_binding(run_id, probe_nonce_sha256, target_identity_sha256)
        with self.__lock:
            if self.__consumed:
                _already_used()
            self.__consumed = True
            material = self.__prevalidated
            self.__prevalidated = None
        if material is None:
            raise ManagedMem0V5RuntimeAttestationHttpError(
                "managed_mem0_v5_runtime_not_prevalidated"
            )
        bound_run, bound_nonce, bound_target, capability = material
        if (bound_run, bound_nonce, bound_target) != (
            run_id,
            probe_nonce_sha256,
            target_identity_sha256,
        ) or not managed_mem0_v5_runtime_validation_is_publishable(
            capability, required_runtime_mode="oss"
        ):
            _invalid_capability()
        if _reserved_managed_mem0_runtime_deadline_lease_is_available(self):
            try:
                from infinity_context_server.memory_comparison_managed_runtime_validity import (
                    _bind_managed_live_runtime_policy_from_reserved_authority,
                )

                _bind_managed_live_runtime_policy_from_reserved_authority(
                    capability,
                    authority=self,
                    run_id=run_id,
                    probe_nonce_sha256=probe_nonce_sha256,
                    target_identity_sha256=target_identity_sha256,
                )
            except Exception:
                _invalid_capability()
        return capability

    def usage_attestation_required(self) -> bool:
        with self.__lock:
            if not self.__consumed:
                _invalid_capability()
        return False

    def __require_binding(self, run_id: object, nonce: object, target: object) -> None:
        if (
            type(run_id) is not str
            or _RUN_ID.fullmatch(run_id) is None
            or not _is_sha256(nonce)
            or not _is_sha256(target)
            or not hmac.compare_digest(str(nonce), self.__authority_descriptor.probe_nonce_sha256)
            or not hmac.compare_digest(str(target), self.__target_identity_sha256)
        ):
            raise ManagedMem0V5RuntimeAttestationHttpError(
                "managed_mem0_v5_runtime_binding_invalid"
            )

    def __remaining_seconds(self) -> float:
        try:
            remaining = self.__deadline_monotonic - float(self.__monotonic_clock())
        except Exception:
            _configuration_invalid()
        if not math.isfinite(remaining) or remaining < 0.001:
            raise ManagedMem0V5RuntimeAttestationHttpError(
                "managed_mem0_v5_runtime_deadline_exceeded"
            )
        return remaining

    def __wall_now(self) -> int:
        try:
            value = self.__wall_clock()
        except Exception:
            _configuration_invalid()
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            _configuration_invalid()
        return int(value)


async def _post_attestation(
    *,
    transport: VettedProbeTransport,
    base_url: str,
    timeout_seconds: float,
    bearer_token: str,
    request: Mapping[str, object],
) -> dict[str, object]:
    request_sha256 = _canonical_sha256(request)
    idempotency = hashlib.sha256(_IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha256)).hexdigest()
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Idempotency-Key": idempotency,
        "X-Request-Commitment-SHA256": request_sha256,
    }
    async with asyncio.timeout(timeout_seconds):
        async with transport.open_client(
            base_url=base_url, timeout_seconds=timeout_seconds
        ) as client:
            async with client.stream(
                "POST", ATTESTATION_PATH, headers=headers, json=request
            ) as response:
                if type(response.status_code) is not int or response.status_code != 200:
                    raise ManagedMem0V5RuntimeAttestationHttpError(
                        "managed_mem0_v5_runtime_probe_failed"
                    )
                raw = bytearray()
                async for chunk in response.aiter_raw(chunk_size=8_192):
                    if type(chunk) is not bytes or len(raw) + len(chunk) > 32 * 1024:
                        _invalid_capability()
                    raw.extend(chunk)
    try:
        payload = json.loads(bytes(raw), object_pairs_hook=_unique_object)
    except Exception:
        _invalid_capability()
    if type(payload) is not dict:
        _invalid_capability()
    return payload


def _trusted_implementation_sha256(expected: object) -> str:
    if not _is_sha256(expected):
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_mismatch"
        )
    observed = _implementation_source_sha256()
    if not hmac.compare_digest(observed, str(expected)):
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_mismatch"
        )
    return observed


def _implementation_source_sha256() -> str:
    http_path = _implementation_source_sha256.__code__.co_filename
    if type(http_path) is not str or not os.path.isabs(http_path):
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_unavailable"
        )
    directory = os.path.dirname(http_path)
    rows = bytearray()
    try:
        for name in sorted(_SOURCE_NAMES):
            path = os.path.join(directory, name)
            size, digest = _read_implementation_source(path, expected_name=name)
            rows.extend(name.encode("ascii"))
            rows.extend(b"\0")
            rows.extend(str(size).encode("ascii"))
            rows.extend(b"\0")
            rows.extend(digest.encode("ascii"))
            rows.extend(b"\n")
        return hashlib.sha256(rows).hexdigest()
    except ManagedMem0V5RuntimeAttestationHttpError:
        raise
    except Exception:
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_unavailable"
        ) from None


def _read_implementation_source(path: str, *, expected_name: str) -> tuple[int, str]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if (
        type(path) is not str
        or not os.path.isabs(path)
        or os.path.basename(path) != expected_name
        or no_follow == 0
    ):
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_unavailable"
        )
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1_000_000:
            raise OSError
        raw = bytearray()
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, min(64 * 1024, before.st_size - len(raw)))
            if not chunk:
                raise OSError
            raw.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise OSError
        return before.st_size, hashlib.sha256(raw).hexdigest()
    except Exception:
        raise ManagedMem0V5RuntimeAttestationHttpError(
            "managed_mem0_v5_runtime_implementation_unavailable"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _private_secret(value: object) -> bytearray:
    if type(value) is not str or value != value.strip():
        _configuration_invalid()
    encoded = value.encode()
    if not 32 <= len(encoded) <= 4_096 or any(byte < 32 or byte == 127 for byte in encoded):
        _configuration_invalid()
    return bytearray(encoded)


def _seconds(value: object, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _configuration_invalid()
    number = float(value)
    if not math.isfinite(number) or not 0.001 <= number <= maximum:
        _configuration_invalid()
    return number


def _invalid_capability() -> None:
    raise ManagedMem0V5RuntimeAttestationHttpError("managed_mem0_v5_runtime_capability_invalid")


def _already_used() -> None:
    raise ManagedMem0V5RuntimeAttestationHttpError("managed_mem0_v5_runtime_already_used")


__all__ = (
    "ManagedMem0V5ExpectedRuntimeAuthority",
    "ManagedMem0V5RuntimeAttestationHttpError",
    "ManagedMem0V5RuntimeAttestationPort",
    "VerifiedManagedMem0V5RuntimeAttestationValidation",
    "managed_mem0_v5_runtime_validation_is_publishable",
    "expected_managed_mem0_v5_runtime_authority_from_pin",
    "public_managed_mem0_v5_runtime_validation",
)
