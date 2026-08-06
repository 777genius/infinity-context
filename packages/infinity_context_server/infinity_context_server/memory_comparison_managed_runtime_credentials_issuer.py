"""Composition-root issuer for one-run managed credential authorities."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    managed_mem0_data_plane_auth_mode,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_integrity import (
    adapter_credential_binding,
    runtime_authority_integrity,
    secret_commitments,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedCredentialPreflightMaterial,
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_targets import (
    _normalized_backend,
)
from infinity_context_server.memory_comparison_mem0_oss_ingress import (
    Mem0OssIngressCredentialAuthority,
    inspect_mem0_oss_ingress_authority,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_CHAT_ENDPOINT_PATH,
    SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRUST,
    _validated_loopback_origin,
)

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_managed_runtime_credentials import (
        ManagedRuntimeCredentialAuthority,
    )

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MAX_SECRET_BYTES = 16_384


def issue_managed_runtime_credential_authority(
    *,
    run_id: str,
    infinity_origin: str,
    infinity_auth_token: str,
    mem0_origin: str,
    mem0_api_key: str | None,
    mem0_probe_token: str | None,
    subscription_origin: str,
    subscription_bearer_token: str,
    request_timeout_seconds: float,
    issued_at: datetime,
    deadline: datetime,
    mem0_data_plane_auth_mode: str = MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    mem0_oss_ingress_authority: Mem0OssIngressCredentialAuthority | None = None,
) -> ManagedRuntimeCredentialAuthority:
    """Issue an authority before preflight from exact composition-root values."""

    from infinity_context_server import memory_comparison_managed_runtime_credentials as root

    try:
        trusted_run_id = _identifier(run_id)
        trusted_issued_at = _aware(issued_at)
        trusted_deadline = _aware(deadline)
        if trusted_issued_at >= trusted_deadline:
            _fail()
        timeout = _timeout(request_timeout_seconds)
        infinity_secret = _secret(infinity_auth_token)
        normalized_infinity, infinity_target = _normalized_backend(
            "infinity-context", infinity_origin
        )
        normalized_mem0, mem0_target = _normalized_backend("mem0", mem0_origin)
        normalized_subscription = _subscription_origin(subscription_origin)
        auth_mode = managed_mem0_data_plane_auth_mode(mem0_data_plane_auth_mode)
        ingress_descriptor = None
        if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE:
            if mem0_api_key is not None or mem0_probe_token is None:
                _fail()
            mem0_secret = None
            probe_secret = _secret(mem0_probe_token)
            if mem0_oss_ingress_authority is not None:
                ingress_descriptor = inspect_mem0_oss_ingress_authority(mem0_oss_ingress_authority)
                if ingress_descriptor.run_id_sha256 != hashlib.sha256(
                    trusted_run_id.encode()
                ).hexdigest() or not hmac.compare_digest(
                    ingress_descriptor.target_identity_sha256,
                    mem0_target.target_identity_sha256,
                ):
                    _fail()
        elif auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY:
            if mem0_oss_ingress_authority is not None:
                _fail()
            mem0_secret = _secret(mem0_api_key)
            probe_secret = mem0_secret if mem0_probe_token is None else _secret(mem0_probe_token)
        else:  # pragma: no cover - sealed validator above
            _fail()
        subscription_secret = _secret(subscription_bearer_token)
        key = secrets.token_bytes(32)
        commitments = secret_commitments(
            key,
            run_id=trusted_run_id,
            infinity_origin=normalized_infinity,
            mem0_origin=normalized_mem0,
            subscription_origin=normalized_subscription,
            infinity_secret=infinity_secret,
            mem0_secret=mem0_secret,
            probe_secret=probe_secret,
            subscription_secret=subscription_secret,
            mem0_data_plane_auth_mode=auth_mode,
        )
        provider_credential = ManagedCredentialBinding(
            "subscription-runtime", True, adapter_credential_binding(subscription_secret)
        )
        infinity_binding = ManagedCredentialBinding(
            "infinity-context", True, "sha256:" + commitments[0]
        )
        mem0_binding = ManagedCredentialBinding(
            "mem0",
            auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
            (
                "sha256:" + commitments[1]
                if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY
                else None
            ),
        )
        probe_credential = ManagedCredentialBinding(
            "mem0-probe", True, adapter_credential_binding(probe_secret)
        )
        endpoints = (
            ManagedBackendEndpoint(infinity_target, normalized_infinity, infinity_binding),
            ManagedBackendEndpoint(mem0_target, normalized_mem0, mem0_binding),
        )
        endpoint = f"{normalized_subscription}{SUBSCRIPTION_CHAT_ENDPOINT_PATH}"
        route = ProviderRouteAttestation(
            trust=SUBSCRIPTION_RUNTIME_TRUST,
            origin=normalized_subscription,
            endpoint_path=SUBSCRIPTION_CHAT_ENDPOINT_PATH,
            route_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
            transport_evidence=SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
            credential_binding_id=provider_credential.binding_id,
            request_method="POST",
            response_status=0,
        )
        material = ManagedCredentialPreflightMaterial(
            provider_credential=provider_credential,
            backend_endpoints=endpoints,
            provider_route=route,
            mem0_probe_credential=probe_credential,
            mem0_data_plane_auth_mode=auth_mode,
        )
        state = root._AuthorityState(
            run_id=trusted_run_id,
            issued_at=trusted_issued_at,
            deadline=trusted_deadline,
            request_timeout_seconds=timeout,
            infinity_origin=normalized_infinity,
            mem0_origin=normalized_mem0,
            subscription_origin=normalized_subscription,
            infinity_secret=infinity_secret,
            mem0_secret=mem0_secret,
            mem0_oss_ingress_authority=mem0_oss_ingress_authority,
            mem0_oss_ingress_descriptor=ingress_descriptor,
            mem0_data_plane_auth_mode=auth_mode,
            probe_secret=probe_secret,
            subscription_secret=subscription_secret,
            binding_key=key,
            secret_commitments=commitments,
            material=material,
            integrity="",
        )
        state.integrity = runtime_authority_integrity(state)
        return root.ManagedRuntimeCredentialAuthority(state=state, _token=root._TOKEN)
    except ManagedRuntimeCredentialError:
        raise
    except Exception:
        _fail()


def _subscription_origin(value: object) -> str:
    if type(value) is not str or value != value.strip():
        _fail()
    try:
        return _validated_loopback_origin(value)
    except Exception:
        _fail()


def _secret(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _fail()
    if size > _MAX_SECRET_BYTES:
        _fail()
    return value


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail()
    return value


def _timeout(value: object) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0 or value > 180:
        _fail()
    return float(value)


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail()
    try:
        return value.astimezone(UTC)
    except Exception:
        _fail()


def _fail() -> None:
    raise ManagedRuntimeCredentialError("managed_credentials_configuration_invalid")


__all__ = ("issue_managed_runtime_credential_authority",)
