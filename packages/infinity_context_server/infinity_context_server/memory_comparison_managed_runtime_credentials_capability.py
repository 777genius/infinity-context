"""Opaque backend credential capability consumed by HTTP composition."""

from __future__ import annotations

import hmac
import secrets
import threading
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_integrity import (
    canonical_json_bytes,
    hmac_sha256,
)

_TOKEN = object()


@final
class ManagedBackendCredentialMaterial:
    """One-shot proof that exact configs came from the admitted authority.

    The HTTP execution adapter should accept ``credential_material`` instead of
    caller-supplied configs and locally import this module inside its constructor
    to avoid a module cycle. It then calls ``consume_for_http_execution`` with
    its exact request/run/deadline. The Mem0 runtime composition separately calls
    ``consume_mem0_probe_token``. No secret-bearing property is exposed.
    """

    __slots__ = (
        "__commitment",
        "__deadline",
        "__infinity",
        "__key",
        "__lock",
        "__mem0",
        "__http_phase",
        "__probe_token",
        "__probe_phase",
        "__request",
        "__run_id",
        "__snapshot",
    )

    def __init__(
        self,
        *,
        infinity: ManagedInfinityHttpConfig,
        mem0: ManagedMem0HttpConfig,
        probe_token: str,
        request: ManagedPreflightRequest,
        run_id: str,
        deadline: datetime,
        _token: object,
    ) -> None:
        if (
            _token is not _TOKEN
            or type(infinity) is not ManagedInfinityHttpConfig
            or type(mem0) is not ManagedMem0HttpConfig
            or type(probe_token) is not str
            or type(request) is not ManagedPreflightRequest
            or type(run_id) is not str
            or type(deadline) is not datetime
        ):
            raise TypeError("managed backend credential material is invalid")
        self.__infinity = infinity
        self.__mem0 = mem0
        self.__probe_token = probe_token
        self.__request = request
        self.__run_id = run_id
        self.__deadline = deadline
        self.__key = secrets.token_bytes(32)
        self.__lock = threading.Lock()
        self.__http_phase = "pending"
        self.__probe_phase = "pending"
        self.__snapshot = self._current_snapshot()
        self.__commitment = hmac_sha256(self.__key, self.__snapshot)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBackendCredentialMaterial is final")

    def __repr__(self) -> str:
        return "ManagedBackendCredentialMaterial(<sealed-one-shot>)"

    def consume_for_http_execution(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        deadline: datetime,
    ) -> tuple[ManagedInfinityHttpConfig, ManagedMem0HttpConfig]:
        """Consume continuity and return the exact bound configs once."""

        with self.__lock:
            phase = self.__http_phase
            self.__http_phase = "terminal"
            if phase != "pending" or not self._context_matches(
                expected_request=expected_request,
                run_id=run_id,
                deadline=deadline,
            ):
                raise ValueError("managed backend credential continuity failed")
            self.__http_phase = "consumed"
            return self.__infinity, self.__mem0

    def consume_mem0_probe_token(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        deadline: datetime,
    ) -> str:
        """Consume the separately-bound exact probe credential once."""

        with self.__lock:
            phase = self.__probe_phase
            self.__probe_phase = "terminal"
            if phase != "pending" or not self._context_matches(
                expected_request=expected_request,
                run_id=run_id,
                deadline=deadline,
            ):
                raise ValueError("managed backend credential continuity failed")
            self.__probe_phase = "consumed"
            return self.__probe_token

    def _context_matches(
        self,
        *,
        expected_request: ManagedPreflightRequest,
        run_id: str,
        deadline: datetime,
    ) -> bool:
        try:
            current = self._current_snapshot()
            commitment = hmac_sha256(self.__key, current)
        except Exception:
            return False
        return (
            expected_request is self.__request
            and run_id == self.__run_id
            and deadline == self.__deadline
            and hmac.compare_digest(current, self.__snapshot)
            and hmac.compare_digest(commitment, self.__commitment)
        )

    def _current_snapshot(self) -> bytes:
        infinity = self.__infinity
        mem0 = self.__mem0
        return canonical_json_bytes(
            {
                "run_id": self.__run_id,
                "deadline": self.__deadline.isoformat(),
                "request_identity": id(self.__request),
                "infinity": {
                    "target_identity_sha256": infinity.target_identity_sha256,
                    "base_url": infinity.base_url,
                    "timeout_seconds": infinity.timeout_seconds,
                    "transport_identity": (
                        id(infinity.transport) if infinity.transport is not None else None
                    ),
                    "credential_commitment": hmac_sha256(
                        self.__key, infinity.auth_token.encode()
                    ),
                },
                "mem0": {
                    "target_identity_sha256": mem0.target_identity_sha256,
                    "base_url": mem0.base_url,
                    "timeout_seconds": mem0.timeout_seconds,
                    "send_timestamps": mem0.send_timestamps,
                    "transport_identity": (
                        id(mem0.transport) if mem0.transport is not None else None
                    ),
                    "credential_commitment": hmac_sha256(
                        self.__key, (mem0.api_key or "").encode()
                    ),
                    "probe_credential_commitment": hmac_sha256(
                        self.__key, self.__probe_token.encode()
                    ),
                },
            }
        )

    def __copy__(self) -> object:
        raise TypeError("managed backend credential material is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed backend credential material is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed backend credential material is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed backend credential material is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed backend credential material is nonserializable")


def _issue_backend_credential_material(
    *,
    infinity: ManagedInfinityHttpConfig,
    mem0: ManagedMem0HttpConfig,
    probe_token: str,
    request: ManagedPreflightRequest,
    run_id: str,
    deadline: datetime,
) -> ManagedBackendCredentialMaterial:
    return ManagedBackendCredentialMaterial(
        infinity=infinity,
        mem0=mem0,
        probe_token=probe_token,
        request=request,
        run_id=run_id,
        deadline=deadline,
        _token=_TOKEN,
    )


__all__ = ("ManagedBackendCredentialMaterial",)
