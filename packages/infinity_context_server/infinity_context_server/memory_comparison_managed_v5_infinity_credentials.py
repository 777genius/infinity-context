"""Dedicated one-run credentials for managed-v5 Infinity-only adapters."""

from __future__ import annotations

import hmac
import json
import math
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_integrity import (
    hmac_sha256,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)

_ISSUER_TOKEN = object()


@dataclass(slots=True, repr=False)
class _InfinityCredentialState:
    run_id: str
    origin: str
    target_identity_sha256: str
    auth_token: str
    timeout_seconds: float
    execution_transport: httpx.BaseTransport | None
    lifecycle_transport: httpx.BaseTransport | None
    registry_policy_transport: httpx.BaseTransport | None
    deadline: datetime
    request_identity: int
    request_commitment: str
    binding_key: bytes
    preparation_identity: int
    preparation_commitment: str
    activation_identity: int = 0
    activation_commitment: str = ""
    activation_phase: str = "unbound"
    execution_phase: str = "pending"
    lifecycle_phase: str = "pending"
    registry_policy_phase: str = "pending"
    integrity: str = ""


@final
class ManagedV5InfinityCredentialBundle:
    """Opaque exact-use capabilities for three Infinity-only adapter roles."""

    __slots__ = ("__lock", "__state")

    def __init__(self, *, state: _InfinityCredentialState, _token: object) -> None:
        if _token is not _ISSUER_TOKEN or type(state) is not _InfinityCredentialState:
            _fail("configuration_invalid")
        self.__state = state
        self.__lock = threading.RLock()

    def issue_execution_config(self, *, now: datetime) -> ManagedInfinityHttpRuntimeConfig:
        return self._consume("execution", now=now)

    def issue_lifecycle_config(self, *, now: datetime) -> ManagedInfinityHttpRuntimeConfig:
        return self._consume("lifecycle", now=now)

    def issue_registry_policy_config(self, *, now: datetime) -> ManagedInfinityHttpRuntimeConfig:
        return self._consume("registry_policy", now=now)

    def _bind_activated_preparation(self, activated: object, *, now: datetime) -> None:
        from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
            _authenticate_activated_managed_v5_public_run,
        )

        material = _authenticate_activated_managed_v5_public_run(activated)
        with self.__lock:
            state = self.__state
            if not hmac.compare_digest(state.integrity, _state_integrity(state)):
                _fail("configuration_invalid")
            if state.activation_phase != "unbound":
                _fail("replayed")
            infinity_targets = tuple(
                target
                for target in material.composition_binding.backend_targets
                if target.backend_role == "infinity-context"
            )
            if (
                type(now) is not datetime
                or now.tzinfo is None
                or now.utcoffset() is None
                or now >= state.deadline
                or material.request.run_id != state.run_id
                or material.preparation_identity != state.preparation_identity
                or not hmac.compare_digest(
                    material.preparation_commitment,
                    state.preparation_commitment,
                )
                or material.composition_binding.deadline != state.deadline
                or len(infinity_targets) != 1
                or infinity_targets[0].target_identity_sha256 != state.target_identity_sha256
            ):
                _fail("configuration_invalid")
            state.activation_identity = id(material)
            state.activation_commitment = material.integrity_mac.hex()
            state.activation_phase = "bound"
            state.integrity = _state_integrity(state)

    def _consume(self, lane: str, *, now: datetime) -> ManagedInfinityHttpRuntimeConfig:
        with self.__lock:
            state = self.__state
            if not hmac.compare_digest(state.integrity, _state_integrity(state)):
                _fail("configuration_invalid")
            if state.activation_phase != "bound":
                _fail("configuration_invalid")
            if (
                type(now) is not datetime
                or now.tzinfo is None
                or now.utcoffset() is None
                or now >= state.deadline
            ):
                _fail("expired")
            attribute = f"{lane}_phase"
            if getattr(state, attribute, None) != "pending":
                _fail("replayed")
            setattr(state, attribute, "active")
            state.integrity = _state_integrity(state)
            try:
                config = ManagedInfinityHttpRuntimeConfig(
                    target_identity_sha256=state.target_identity_sha256,
                    base_url=state.origin,
                    auth_token=state.auth_token,
                    timeout_seconds=state.timeout_seconds,
                    transport=getattr(state, f"{lane}_transport"),
                )
            except Exception:
                setattr(state, attribute, "terminal")
                state.integrity = _state_integrity(state)
                _fail("configuration_invalid")
            setattr(state, attribute, "issued")
            state.integrity = _state_integrity(state)
            return config

    def __repr__(self) -> str:
        return "ManagedV5InfinityCredentialBundle(<sealed-three-lane>)"

    def __copy__(self) -> object:
        raise TypeError("managed v5 Infinity credentials are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed v5 Infinity credentials are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed v5 Infinity credentials are nonserializable")


def _issue_managed_v5_infinity_credential_bundle(
    *,
    authority_state: object,
    expected_request: ManagedPreflightRequest,
    public_preparation: object,
    run_id: str,
    infinity_origin: str,
    deadline: datetime,
    now: datetime,
    execution_transport: httpx.BaseTransport | None,
    lifecycle_transport: httpx.BaseTransport | None,
    registry_policy_transport: httpx.BaseTransport | None,
) -> ManagedV5InfinityCredentialBundle:
    """Issue without constructing or inspecting any legacy Mem0 configuration."""

    try:
        from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
            _authenticate_managed_v5_public_run_preparation,
        )

        preparation = _authenticate_managed_v5_public_run_preparation(public_preparation)
        if type(expected_request) is not ManagedPreflightRequest:
            raise TypeError
        if expected_request is not authority_state.preflight_request:
            raise TypeError
        if run_id != authority_state.run_id or deadline != authority_state.deadline:
            raise TypeError
        if (
            preparation.request.run_id != run_id
            or preparation.composition_binding.deadline != deadline
        ):
            raise TypeError
        if now.tzinfo is None or now.utcoffset() is None:
            raise TypeError
        if now < authority_state.issued_at or now >= deadline:
            _fail("expired")
        endpoints = tuple(
            item
            for item in expected_request.backend_endpoints
            if item.target.backend_role == "infinity-context"
        )
        if len(endpoints) != 1 or endpoints[0].base_url != infinity_origin:
            raise TypeError
        expected_target = managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=infinity_origin
        )
        if endpoints[0].target.target_identity_sha256 != expected_target:
            raise TypeError
        infinity_targets = tuple(
            target
            for target in preparation.composition_binding.backend_targets
            if target.backend_role == "infinity-context"
        )
        if (
            len(infinity_targets) != 1
            or infinity_targets[0].target_identity_sha256 != expected_target
        ):
            raise TypeError
        remaining = (deadline - now).total_seconds()
        timeout = min(float(authority_state.request_timeout_seconds), remaining)
        if not math.isfinite(timeout) or timeout <= 0:
            _fail("expired")
        transports = (
            execution_transport,
            lifecycle_transport,
            registry_policy_transport,
        )
        if any(
            item is not None and not isinstance(item, httpx.BaseTransport) for item in transports
        ):
            raise TypeError
        non_null = tuple(item for item in transports if item is not None)
        if len({id(item) for item in non_null}) != len(non_null):
            raise TypeError
        if type(authority_state.preflight_commitment) is not str:
            raise TypeError
        # Recompute an HMAC-bound role commitment before copying the sole Infinity
        # secret. The commitment deliberately has no public accessor.
        request_commitment = hmac_sha256(
            authority_state.binding_key,
            b"managed-v5-infinity\0"
            + authority_state.preflight_commitment.encode()
            + b"\0"
            + run_id.encode()
            + b"\0"
            + infinity_origin.encode(),
        )
        state = _InfinityCredentialState(
            run_id=run_id,
            origin=infinity_origin,
            target_identity_sha256=expected_target,
            auth_token=authority_state.infinity_secret,
            timeout_seconds=timeout,
            execution_transport=execution_transport,
            lifecycle_transport=lifecycle_transport,
            registry_policy_transport=registry_policy_transport,
            deadline=deadline,
            request_identity=id(expected_request),
            request_commitment=request_commitment,
            binding_key=authority_state.binding_key,
            preparation_identity=id(public_preparation),
            preparation_commitment=preparation.integrity_mac.hex(),
        )
        state.integrity = _state_integrity(state)
        return ManagedV5InfinityCredentialBundle(state=state, _token=_ISSUER_TOKEN)
    except ManagedRuntimeCredentialError:
        raise
    except Exception:
        _fail("configuration_invalid")


def _fail(suffix: str) -> None:
    code = {
        "configuration_invalid": "managed_credentials_configuration_invalid",
        "expired": "managed_credentials_expired",
        "replayed": "managed_credentials_terminal",
    }[suffix]
    raise ManagedRuntimeCredentialError(code) from None


def _state_integrity(state: _InfinityCredentialState) -> str:
    payload = json.dumps(
        {
            "run_id": state.run_id,
            "origin": state.origin,
            "target_identity_sha256": state.target_identity_sha256,
            "auth_token": state.auth_token,
            "timeout_seconds": state.timeout_seconds,
            "deadline": state.deadline.isoformat(),
            "request_identity": state.request_identity,
            "request_commitment": state.request_commitment,
            "preparation_identity": state.preparation_identity,
            "preparation_commitment": state.preparation_commitment,
            "activation_identity": state.activation_identity,
            "activation_commitment": state.activation_commitment,
            "activation_phase": state.activation_phase,
            "transport_identities": [
                id(state.execution_transport),
                id(state.lifecycle_transport),
                id(state.registry_policy_transport),
            ],
            "phases": [
                state.execution_phase,
                state.lifecycle_phase,
                state.registry_policy_phase,
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac_sha256(state.binding_key, payload)


__all__ = ("ManagedV5InfinityCredentialBundle",)
