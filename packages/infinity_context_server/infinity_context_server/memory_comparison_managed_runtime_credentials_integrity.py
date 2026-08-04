"""Private canonical integrity helpers for managed runtime credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping

import httpx

from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY,
    MANAGED_MEM0_DATA_PLANE_AUTH_NONE,
    managed_mem0_data_plane_auth_mode,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
    ManagedPreflightResult,
)

_CONTEXT = b"infinity-context.managed-runtime-credential.v1"


def canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    """Encode one exact JSON-safe integrity snapshot deterministically."""

    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def hmac_sha256(key: bytes, payload: bytes) -> str:
    """Return a keyed commitment after validating authority key shape."""

    if type(key) is not bytes or len(key) != 32 or type(payload) is not bytes:
        raise ValueError("managed credential integrity input is invalid")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def secret_commitments(
    key: bytes,
    *,
    run_id: str,
    infinity_origin: str,
    mem0_origin: str,
    subscription_origin: str,
    infinity_secret: str,
    mem0_secret: str | None,
    probe_secret: str,
    subscription_secret: str,
    mem0_data_plane_auth_mode: str,
) -> tuple[str, str, str, str]:
    """Commit exact role, run, origin and raw secret without publishing the key."""

    auth_mode = managed_mem0_data_plane_auth_mode(mem0_data_plane_auth_mode)
    if auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_NONE:
        if mem0_secret is not None:
            raise ValueError("keyless Mem0 data-plane auth must not carry a key")
        mem0_context = ("mem0-data-plane:none", mem0_origin, "")
    elif auth_mode == MANAGED_MEM0_DATA_PLANE_AUTH_API_KEY:
        if type(mem0_secret) is not str:
            raise ValueError("Mem0 API-key data-plane auth must carry a key")
        mem0_context = ("mem0", mem0_origin, mem0_secret)
    else:  # pragma: no cover - sealed validator above
        raise ValueError("managed Mem0 data-plane auth mode is invalid")
    contexts = (
        ("infinity-context", infinity_origin, infinity_secret),
        mem0_context,
        ("mem0-probe", mem0_origin, probe_secret),
        ("subscription-runtime", subscription_origin, subscription_secret),
    )
    values = tuple(
        hmac_sha256(
            key,
            b"\0".join(
                (
                    _CONTEXT,
                    run_id.encode(),
                    role.encode(),
                    origin.encode(),
                    secret.encode(),
                )
            ),
        )
        for role, origin, secret in contexts
    )
    if len(values) != 4:  # pragma: no cover - fixed local tuple
        raise ValueError("managed credential commitment coverage is invalid")
    return values[0], values[1], values[2], values[3]


def adapter_credential_binding(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode()).hexdigest()


def validate_mock_transport(transport: object) -> None:
    if transport is not None and type(transport) is not httpx.MockTransport:
        raise ValueError("managed credential test transport is invalid")


def runtime_authority_integrity(state: object) -> str:
    material = state.material
    payload = {
        "run_id": state.run_id,
        "issued_at": state.issued_at.isoformat(),
        "deadline": state.deadline.isoformat(),
        "request_timeout_seconds": state.request_timeout_seconds,
        "origins": [state.infinity_origin, state.mem0_origin, state.subscription_origin],
        "secret_commitments": list(state.secret_commitments),
        "mem0_data_plane_auth_mode": state.mem0_data_plane_auth_mode,
        "material_mem0_data_plane_auth_mode": material.mem0_data_plane_auth_mode,
        "provider_credential": _credential_snapshot(material.provider_credential),
        "mem0_probe_credential": _credential_snapshot(material.mem0_probe_credential),
        "backend_endpoints": [
            {
                "target": {
                    "backend_role": item.target.backend_role,
                    "target_identity_sha256": item.target.target_identity_sha256,
                },
                "base_url": item.base_url,
                "loopback": item.loopback,
                "credential": _credential_snapshot(item.credential),
            }
            for item in material.backend_endpoints
        ],
        "route": material.provider_route.public_payload(),
        "preflight_snapshot_sha256": (
            hashlib.sha256(state.preflight_snapshot).hexdigest()
            if state.preflight_snapshot is not None
            else None
        ),
        "preflight_commitment": state.preflight_commitment,
        "bound_request_identity": state.bound_request_identity,
    }
    return hmac_sha256(state.binding_key, canonical_json_bytes(payload))


def managed_preflight_request_snapshot(
    request: ManagedPreflightRequest,
    result: ManagedPreflightResult,
) -> bytes:
    """Snapshot every admitted request field plus the validated projection."""

    if (
        type(request) is not ManagedPreflightRequest
        or type(result) is not ManagedPreflightResult
    ):
        raise TypeError("managed preflight snapshot types are invalid")
    route = request.provider_route
    dataset = request.dataset
    timeouts = request.timeouts
    return canonical_json_bytes(
        {
            "validated": result.public_payload(),
            "profile_repr": repr(request.profile),
            "methodology_repr": repr(request.methodology),
            "dataset": {
                "profile_id": dataset.profile_id,
                "benchmark": dataset.benchmark,
                "dataset_sha256": dataset.dataset_sha256,
                "case_count": dataset.case_count,
                "distribution": dict(dataset.distribution),
                "corpus_count": dataset.corpus_count,
            },
            "provider_route": route.public_payload(),
            "answerer_model": request.answerer_model,
            "judge_model": request.judge_model,
            "provider_credential": _credential(request.openai_credential),
            "backend_endpoints": [
                {
                    "target": {
                        "backend_role": endpoint.target.backend_role,
                        "target_identity_sha256": endpoint.target.target_identity_sha256,
                    },
                    "base_url": endpoint.base_url,
                    "loopback": endpoint.loopback,
                    "credential": _credential(endpoint.credential),
                }
                for endpoint in request.backend_endpoints
            ],
            "timeouts": {
                "connect_seconds": timeouts.connect_seconds,
                "request_seconds": timeouts.request_seconds,
                "run_seconds": timeouts.run_seconds,
            },
            "scope": request.scope,
            "provider_kind": request.provider_kind,
            "mem0_data_plane_auth_mode": request.mem0_data_plane_auth_mode,
        }
    )


def _credential(value: object) -> dict[str, object]:
    return {
        "credential_name": getattr(value, "credential_name", None),
        "configured": getattr(value, "configured", None),
        "binding_id": getattr(value, "binding_id", None),
    }


_credential_snapshot = _credential


__all__ = (
    "canonical_json_bytes",
    "hmac_sha256",
    "managed_preflight_request_snapshot",
    "secret_commitments",
)
