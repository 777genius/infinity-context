"""Production managed Mem0 runtime attestation over the vetted probe stack.

The adapter owns only the same-run runtime capability concern. Network routing,
bounded response handling, OpenAPI policy and witness verification remain in the
existing probe and runtime-attestation components.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAuthorityDescriptor,
    _register_pending_managed_mem0_runtime_authority,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
    VerifiedMem0RuntimeAttestation,
    VerifiedMem0RuntimeAttestationValidation,
    mem0_runtime_attestation_validation_is_publishable,
    validate_mem0_runtime_attestation_for_backends,
)
from infinity_context_server.memory_comparison_probe_transport import (
    VettedProbeTransport,
    vet_probe_target,
)
from infinity_context_server.memory_comparison_service_probes import probe_mem0_api

_ADAPTER_ID = "managed.mem0.runtime.http.v1"
_CLOCK_ADAPTER_ID = "managed.utc.clock.v1"
_CLOCK_IMPLEMENTATION_SHA256 = hashlib.sha256(
    b"managed-utc-clock.v1:datetime-now-utc:timezone-aware"
).hexdigest()
_IMPLEMENTATION_SOURCE_NAME = "memory_comparison_managed_mem0_runtime_http.py"
_MAX_IMPLEMENTATION_SOURCE_BYTES = 1_000_000
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_PRIVATE_NONCE_RE = re.compile(r"^[A-Za-z0-9._~:-]{32,256}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PRIVATE_TOKEN_BYTES = 4_096
_MAX_TIMEOUT_SECONDS = 120.0
_MAX_DEADLINE_BUDGET_SECONDS = 172_800.0
_MIN_NETWORK_TIMEOUT_SECONDS = 0.001
_SAFE_ERROR_CODES = frozenset(
    {
        "managed_mem0_runtime_already_used",
        "managed_mem0_runtime_binding_invalid",
        "managed_mem0_runtime_capability_invalid",
        "managed_mem0_runtime_configuration_invalid",
        "managed_mem0_runtime_deadline_exceeded",
        "managed_mem0_runtime_implementation_mismatch",
        "managed_mem0_runtime_implementation_unavailable",
        "managed_mem0_runtime_probe_failed",
        "managed_mem0_runtime_target_unsafe",
    }
)


class ManagedMem0RuntimeHttpError(RuntimeError):
    """Sanitized fail-closed adapter error with no reflected provider data."""

    def __init__(self, code: str) -> None:
        safe_code = code if code in _SAFE_ERROR_CODES else "managed_mem0_runtime_probe_failed"
        self.code = safe_code
        super().__init__(safe_code)


@dataclass(frozen=True, slots=True)
class _Mem0BackendIdentity:
    name: str
    runtime_target_identity_sha256: str


@final
class ManagedMem0RuntimeAttestationPort:
    """One-shot production implementation of the managed attestation port."""

    __slots__ = (
        "__authority_descriptor",
        "__allowed_target_hosts",
        "__base_url",
        "__consumed",
        "__deadline_budget_seconds",
        "__deadline_monotonic",
        "__implementation_sha256",
        "__lock",
        "__minimum_network_timeout_seconds",
        "__monotonic_clock",
        "__probe_nonce",
        "__probe_token",
        "__target_identity_sha256",
        "__timeout_seconds",
        "__transport",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        base_url: str,
        benchmark_probe_token: str,
        probe_nonce: str,
        timeout_seconds: float,
        deadline_budget_seconds: float,
        monotonic_clock: Callable[[], float],
        expected_implementation_sha256: str,
        allowed_target_hosts: Sequence[str] = (),
        vetted_transport: VettedProbeTransport | None = None,
    ) -> None:
        implementation_sha256 = _trusted_implementation_sha256(expected_implementation_sha256)
        token_bytes, nonce_bytes, timeout, hosts = _private_configuration(
            benchmark_probe_token=benchmark_probe_token,
            probe_nonce=probe_nonce,
            timeout_seconds=timeout_seconds,
            allowed_target_hosts=allowed_target_hosts,
        )
        try:
            monotonic, deadline_budget, deadline = _monotonic_deadline(
                monotonic_clock,
                deadline_budget_seconds,
            )
        except Exception:
            _wipe(token_bytes)
            _wipe(nonce_bytes)
            raise
        if type(base_url) is not str or not 0 < len(base_url) <= 2_048:
            _wipe(token_bytes)
            _wipe(nonce_bytes)
            raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
        try:
            parsed_base_url = urlsplit(base_url)
        except ValueError:
            _wipe(token_bytes)
            _wipe(nonce_bytes)
            raise ManagedMem0RuntimeHttpError(
                "managed_mem0_runtime_configuration_invalid"
            ) from None
        if parsed_base_url.path not in {"", "/"}:
            _wipe(token_bytes)
            _wipe(nonce_bytes)
            raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_target_unsafe")
        target = vet_probe_target(
            base_url,
            allowed_hosts=hosts,
            vetted_transport=vetted_transport,
        )
        if target is None:
            _wipe(token_bytes)
            _wipe(nonce_bytes)
            raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_target_unsafe")
        self.__base_url = target.base_url
        self.__implementation_sha256 = implementation_sha256
        self.__target_identity_sha256 = target.identity_sha256
        self.__transport = target.transport
        self.__allowed_target_hosts = hosts
        self.__timeout_seconds = timeout
        self.__monotonic_clock = monotonic
        self.__deadline_budget_seconds = deadline_budget
        self.__deadline_monotonic = deadline
        self.__minimum_network_timeout_seconds = _MIN_NETWORK_TIMEOUT_SECONDS
        self.__probe_token = token_bytes
        self.__probe_nonce = nonce_bytes
        self.__lock = threading.Lock()
        self.__consumed = False
        self.__authority_descriptor = ManagedMem0RuntimeAuthorityDescriptor(
            adapter_id=_ADAPTER_ID,
            implementation_sha256=implementation_sha256,
            target_identity_sha256=target.identity_sha256,
            probe_nonce_sha256=hashlib.sha256(bytes(nonce_bytes)).hexdigest(),
            probe_token_credential_binding_id=(
                "sha256:" + hashlib.sha256(bytes(token_bytes)).hexdigest()
            ),
            request_timeout_seconds=timeout,
            deadline_policy=MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
            deadline_budget_seconds=deadline_budget,
            minimum_network_timeout_seconds=_MIN_NETWORK_TIMEOUT_SECONDS,
            max_attempts=1,
        )
        _register_pending_managed_mem0_runtime_authority(
            self,
            self.__authority_descriptor,
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedMem0RuntimeAttestationPort is final")

    def __repr__(self) -> str:
        return "ManagedMem0RuntimeAttestationPort(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 runtime adapter is nonserializable")

    @property
    def adapter_id(self) -> str:
        """Return stable safe provenance for managed composition evidence."""

        return _ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        """Return the verified digest of the exact loaded adapter source."""

        return self.__implementation_sha256

    def authority_descriptor(self) -> ManagedMem0RuntimeAuthorityDescriptor:
        """Describe the exact pending one-shot authority without exposing secrets."""

        with self.__lock:
            if self.__consumed:
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_already_used")
            return self.__authority_descriptor

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object:
        """Refresh and validate one exact same-run managed Mem0 capability."""

        token, nonce = self.__claim_private_bindings()
        try:
            if type(run_id) is not str or not _RUN_ID_RE.fullmatch(run_id):
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_binding_invalid")
            if (
                type(probe_nonce_sha256) is not str
                or _SHA256_RE.fullmatch(probe_nonce_sha256) is None
                or not hmac.compare_digest(
                    hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
                    probe_nonce_sha256,
                )
                or type(target_identity_sha256) is not str
                or _SHA256_RE.fullmatch(target_identity_sha256) is None
                or not hmac.compare_digest(
                    self.__target_identity_sha256,
                    target_identity_sha256,
                )
            ):
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_binding_invalid")
            timeout_seconds = self.__remaining_timeout_seconds()
            outcome = probe_mem0_api(
                self.__base_url,
                require_timestamp=True,
                require_runtime_contract=True,
                timeout_seconds=timeout_seconds,
                refresh_runtime_attestation=True,
                benchmark_probe_token=token,
                run_id=run_id,
                probe_nonce=nonce,
                allowed_target_hosts=self.__allowed_target_hosts,
                vetted_transport=self.__transport,
            )
            if outcome.passed is not True:
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_probe_failed")
            verified = outcome.details.get("verified_runtime_attestation")
            if type(verified) is not VerifiedMem0RuntimeAttestation:
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_capability_invalid")
            validation = validate_mem0_runtime_attestation_for_backends(
                verified,
                (
                    _Mem0BackendIdentity(
                        name="mem0",
                        runtime_target_identity_sha256=self.__target_identity_sha256,
                    ),
                ),
                run_id,
                nonce,
                required_runtime_mode=MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
                validated_at=datetime.now(UTC),
            )
            if (
                type(validation) is not VerifiedMem0RuntimeAttestationValidation
                or not mem0_runtime_attestation_validation_is_publishable(
                    validation,
                    required_runtime_mode=MEM0_MANAGED_PLATFORM_RUNTIME_MODE,
                )
            ):
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_capability_invalid")
            return validation
        except ManagedMem0RuntimeHttpError:
            raise
        except Exception:
            raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_probe_failed") from None
        finally:
            token = ""
            nonce = ""

    def __claim_private_bindings(self) -> tuple[str, str]:
        with self.__lock:
            if self.__consumed:
                raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_already_used")
            self.__consumed = True
            try:
                token = bytes(self.__probe_token).decode("utf-8")
                nonce = bytes(self.__probe_nonce).decode("utf-8")
            except Exception:
                raise ManagedMem0RuntimeHttpError(
                    "managed_mem0_runtime_configuration_invalid"
                ) from None
            finally:
                _wipe(self.__probe_token)
                _wipe(self.__probe_nonce)
            return token, nonce

    def __remaining_timeout_seconds(self) -> float:
        try:
            now = _monotonic_now(self.__monotonic_clock)
        except ManagedMem0RuntimeHttpError:
            raise
        except Exception:
            raise ManagedMem0RuntimeHttpError(
                "managed_mem0_runtime_configuration_invalid"
            ) from None
        remaining = self.__deadline_monotonic - now
        if remaining < self.__minimum_network_timeout_seconds:
            raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_deadline_exceeded")
        return min(self.__timeout_seconds, remaining)


@final
class ManagedUtcClockPort:
    """Production timezone-aware UTC clock for managed composition."""

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedUtcClockPort is final")

    def __repr__(self) -> str:
        return "ManagedUtcClockPort()"

    @property
    def adapter_id(self) -> str:
        return _CLOCK_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _CLOCK_IMPLEMENTATION_SHA256

    def now(self) -> datetime:
        return datetime.now(UTC)


def _trusted_implementation_sha256(expected: object) -> str:
    if type(expected) is not str or _SHA256_RE.fullmatch(expected) is None:
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_implementation_mismatch")
    observed = _implementation_source_sha256()
    if not hmac.compare_digest(observed, expected):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_implementation_mismatch")
    return observed


def _implementation_source_sha256() -> str:
    """Hash only this adapter source and fail closed if it is not immutable/readable."""

    source_path = _implementation_source_sha256.__code__.co_filename
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if (
        type(source_path) is not str
        or not os.path.isabs(source_path)
        or os.path.basename(source_path) != _IMPLEMENTATION_SOURCE_NAME
        or type(no_follow) is not int
        or no_follow == 0
    ):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_implementation_unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow
    descriptor = -1
    try:
        descriptor = os.open(source_path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= _MAX_IMPLEMENTATION_SOURCE_BYTES
        ):
            raise OSError("invalid adapter source artifact")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise OSError("truncated adapter source artifact")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise OSError("adapter source artifact grew while hashing")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise OSError("adapter source artifact changed while hashing")
        return hashlib.sha256(b"".join(chunks)).hexdigest()
    except ManagedMem0RuntimeHttpError:
        raise
    except Exception:
        raise ManagedMem0RuntimeHttpError(
            "managed_mem0_runtime_implementation_unavailable"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _private_configuration(
    *,
    benchmark_probe_token: object,
    probe_nonce: object,
    timeout_seconds: object,
    allowed_target_hosts: object,
) -> tuple[bytearray, bytearray, float, tuple[str, ...]]:
    token = bytearray()
    nonce = bytearray()
    try:
        token = _private_token(benchmark_probe_token)
        nonce = _private_nonce(probe_nonce)
        timeout = _timeout(timeout_seconds)
        hosts = _host_sequence(allowed_target_hosts)
    except Exception:
        _wipe(token)
        _wipe(nonce)
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid") from None
    return token, nonce, timeout, hosts


def _private_token(value: object) -> bytearray:
    if type(value) is not str:
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    encoded = value.encode("utf-8")
    if (
        not encoded
        or len(encoded) > _MAX_PRIVATE_TOKEN_BYTES
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return bytearray(encoded)


def _private_nonce(value: object) -> bytearray:
    if type(value) is not str or _PRIVATE_NONCE_RE.fullmatch(value) is None:
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return bytearray(value.encode("utf-8"))


def _timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    timeout = float(value)
    if not isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT_SECONDS:
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return timeout


def _monotonic_deadline(
    clock: object,
    budget_seconds: object,
) -> tuple[Callable[[], float], float, float]:
    if not callable(clock):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    if isinstance(budget_seconds, bool) or not isinstance(budget_seconds, int | float):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    budget = float(budget_seconds)
    if (
        not isfinite(budget)
        or not _MIN_NETWORK_TIMEOUT_SECONDS <= budget <= _MAX_DEADLINE_BUDGET_SECONDS
    ):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    try:
        started_at = _monotonic_now(clock)
    except Exception:
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid") from None
    deadline = started_at + budget
    if not isfinite(deadline):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return clock, budget, deadline


def _monotonic_now(clock: Callable[[], object]) -> float:
    observed = clock()
    if isinstance(observed, bool) or not isinstance(observed, int | float):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    instant = float(observed)
    if not isfinite(instant):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return instant


def _host_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    hosts = tuple(value)
    if any(type(host) is not str for host in hosts):
        raise ManagedMem0RuntimeHttpError("managed_mem0_runtime_configuration_invalid")
    return hosts


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = (
    "ManagedMem0RuntimeAuthorityDescriptor",
    "ManagedMem0RuntimeAttestationPort",
    "ManagedMem0RuntimeHttpError",
    "ManagedUtcClockPort",
)
