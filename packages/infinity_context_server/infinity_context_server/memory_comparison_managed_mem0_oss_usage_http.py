"""One-shot HTTP port for signed Mem0 OSS usage attestation."""

from __future__ import annotations

import hmac
import re
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import final

from infinity_context_server.memory_comparison_mem0_oss_ingress import (
    Mem0OssIngressCredentialAuthority,
    _consume_mem0_oss_ingress_usage_probe,
    inspect_mem0_oss_ingress_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_usage_attestation import (
    VerifiedMem0OssUsageAttestation,
)
from infinity_context_server.memory_comparison_probe_transport import (
    VettedProbeTransport,
    vet_probe_target,
)
from infinity_context_server.memory_comparison_service_probes import (
    probe_mem0_oss_usage_attestation,
)

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SECRET_BYTES = 4_096
_MIN_NETWORK_TIMEOUT_SECONDS = 0.001


class ManagedMem0OssUsageHttpError(RuntimeError):
    """Fixed-code failure without reflected credentials or remote payload values."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedMem0OssUsageAttestationPort:
    """Consume one usage-probe ingress lane and return only verified evidence."""

    __slots__ = (
        "__allowed_target_hosts",
        "__base_url",
        "__benchmark_probe_token",
        "__consumed",
        "__clock",
        "__deadline",
        "__ingress_authority",
        "__lock",
        "__probe_nonce",
        "__target_identity_sha256",
        "__timeout_seconds",
        "__transport",
    )

    def __init__(
        self,
        *,
        base_url: str,
        benchmark_probe_token: str,
        probe_nonce: str,
        ingress_authority: Mem0OssIngressCredentialAuthority,
        timeout_seconds: float,
        deadline: datetime,
        clock: Callable[[], datetime],
        allowed_target_hosts: Sequence[str],
        vetted_transport: VettedProbeTransport | None = None,
    ) -> None:
        token = _secret(benchmark_probe_token)
        try:
            if type(probe_nonce) is not str or _NONCE.fullmatch(probe_nonce) is None:
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
            timeout = _timeout(timeout_seconds)
            trusted_deadline = _instant(deadline)
            if not callable(clock):
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
            hosts = _hosts(allowed_target_hosts)
            target = vet_probe_target(
                base_url,
                allowed_hosts=hosts,
                vetted_transport=vetted_transport,
            )
            descriptor = inspect_mem0_oss_ingress_authority(ingress_authority)
            if target is None or not hmac.compare_digest(
                descriptor.target_identity_sha256,
                target.identity_sha256,
            ):
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_target_unsafe")
        except ManagedMem0OssUsageHttpError:
            _wipe(token)
            raise
        except Exception:
            _wipe(token)
            raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid") from None
        self.__base_url = target.base_url
        self.__benchmark_probe_token = token
        self.__probe_nonce = probe_nonce
        self.__deadline = trusted_deadline
        self.__clock = clock
        self.__ingress_authority = ingress_authority
        self.__target_identity_sha256 = target.identity_sha256
        self.__timeout_seconds = timeout
        self.__allowed_target_hosts = hosts
        self.__transport = target.transport
        self.__lock = threading.Lock()
        self.__consumed = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedMem0OssUsageAttestationPort is final")

    def __repr__(self) -> str:
        return "ManagedMem0OssUsageAttestationPort(<sealed-one-shot>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 OSS usage port is nonserializable")

    def attest(
        self,
        *,
        run_id: str,
        target_identity_sha256: str,
    ) -> VerifiedMem0OssUsageAttestation:
        """Bind one exact run/nonce/target within the original run deadline."""

        benchmark_probe_token = ""
        ingress_api_key = ""
        with self.__lock:
            if self.__consumed:
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_already_used")
            self.__consumed = True
            if (
                type(run_id) is not str
                or _RUN_ID.fullmatch(run_id) is None
                or type(target_identity_sha256) is not str
                or _SHA256.fullmatch(target_identity_sha256) is None
                or not hmac.compare_digest(
                    target_identity_sha256,
                    self.__target_identity_sha256,
                )
            ):
                _wipe(self.__benchmark_probe_token)
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_binding_invalid")
            try:
                self.__remaining_timeout()
            except Exception:
                _wipe(self.__benchmark_probe_token)
                raise
            try:
                benchmark_probe_token = bytes(self.__benchmark_probe_token).decode()
            except Exception:
                _wipe(self.__benchmark_probe_token)
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid") from None
            _wipe(self.__benchmark_probe_token)
        try:
            ingress_api_key = _consume_mem0_oss_ingress_usage_probe(
                self.__ingress_authority,
                run_id=run_id,
                target_identity_sha256=target_identity_sha256,
            )
            validated_at, timeout_seconds = self.__remaining_timeout()
            outcome = probe_mem0_oss_usage_attestation(
                self.__base_url,
                benchmark_probe_token=benchmark_probe_token,
                ingress_api_key=ingress_api_key,
                run_id=run_id,
                probe_nonce=self.__probe_nonce,
                timeout_seconds=timeout_seconds,
                allowed_target_hosts=self.__allowed_target_hosts,
                vetted_transport=self.__transport,
                validated_at=validated_at,
            )
            verified = outcome.details.get("verified_usage_attestation")
            if outcome.passed is not True or type(verified) is not VerifiedMem0OssUsageAttestation:
                raise ManagedMem0OssUsageHttpError("mem0_oss_usage_probe_failed")
            return verified
        except ManagedMem0OssUsageHttpError:
            raise
        except Exception:
            raise ManagedMem0OssUsageHttpError("mem0_oss_usage_probe_failed") from None
        finally:
            benchmark_probe_token = ""
            ingress_api_key = ""

    def __remaining_timeout(self) -> tuple[datetime, float]:
        try:
            now = _instant(self.__clock())
        except ManagedMem0OssUsageHttpError:
            raise
        except Exception:
            raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid") from None
        remaining = (self.__deadline - now).total_seconds()
        if remaining < _MIN_NETWORK_TIMEOUT_SECONDS:
            raise ManagedMem0OssUsageHttpError("mem0_oss_usage_deadline_exceeded")
        return now, min(self.__timeout_seconds, remaining)


def _secret(value: object) -> bytearray:
    if type(value) is not str or not value or value != value.strip():
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    try:
        encoded = value.encode()
    except UnicodeEncodeError:
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid") from None
    if len(encoded) > _MAX_SECRET_BYTES:
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    return bytearray(encoded)


def _timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    result = float(value)
    if not isfinite(result) or not 0 < result <= 120:
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    return result


def _instant(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    try:
        if value.utcoffset() is None:
            raise ValueError("timezone offset is absent")
        return value.astimezone(UTC)
    except Exception:
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid") from None


def _hosts(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    result = tuple(value)
    if any(type(item) is not str for item in result):
        raise ManagedMem0OssUsageHttpError("mem0_oss_usage_configuration_invalid")
    return result


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = (
    "ManagedMem0OssUsageAttestationPort",
    "ManagedMem0OssUsageHttpError",
)
