"""Transport and wire-validation support for managed HTTP policy lifecycle."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx

from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_http_policy_receipts import (
    ManagedHttpPolicyReceiptError,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedHttpPolicyLifecycleError(RuntimeError):
    """Stable machine-readable and secret-free lifecycle failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DeadlineTransport(httpx.BaseTransport):
    def __init__(
        self,
        inner: httpx.BaseTransport,
        *,
        configured_timeout: float,
        deadline: datetime,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._configured_timeout = configured_timeout
        self._deadline = deadline
        self._clock = clock
        self._closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_closed")
        remaining = (
            self._deadline - _aware(self._clock(), "managed_http_policy_clock_invalid")
        ).total_seconds()
        if not math.isfinite(remaining) or remaining <= 0:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")
        timeout = min(self._configured_timeout, remaining)
        request.extensions["timeout"] = {
            "connect": timeout,
            "read": timeout,
            "write": timeout,
            "pool": timeout,
        }
        return self._inner.handle_request(request)

    def close(self) -> None:
        if self._closed:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_double_close")
        self._closed = True
        self._inner.close()


def _object_response(response: httpx.Response, code: str) -> dict[str, object]:
    if response.status_code != 200:
        raise ManagedHttpPolicyLifecycleError(code)
    try:
        payload = response.json()
    except ValueError:
        raise ManagedHttpPolicyLifecycleError(code) from None
    if not isinstance(payload, Mapping):
        raise ManagedHttpPolicyLifecycleError(code)
    return dict(payload)


def _receipt(accessor: Callable[[object], object], value: object):
    try:
        return accessor(value)
    except ManagedHttpPolicyReceiptError as exc:
        raise ManagedHttpPolicyLifecycleError(exc.code) from None


def _attestation(value: object, commitment: object) -> None:
    if type(value) is not VerifiedManagedCompositionAttestation:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_attestation_invalid")
    _digest(commitment, "managed_http_policy_attestation_commitment_invalid")


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


def _aware(value: object, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ManagedHttpPolicyLifecycleError(code)
    return value


__all__ = ("ManagedHttpPolicyLifecycleError",)
