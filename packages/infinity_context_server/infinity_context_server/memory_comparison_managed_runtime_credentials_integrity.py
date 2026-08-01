"""Private canonical integrity helpers for managed runtime credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping

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
    mem0_secret: str,
    probe_secret: str,
    subscription_secret: str,
) -> tuple[str, str, str, str]:
    """Commit exact role, run, origin and raw secret without publishing the key."""

    contexts = (
        ("infinity-context", infinity_origin, infinity_secret),
        ("mem0", mem0_origin, mem0_secret),
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
        }
    )


def _credential(value: object) -> dict[str, object]:
    return {
        "credential_name": getattr(value, "credential_name", None),
        "configured": getattr(value, "configured", None),
        "binding_id": getattr(value, "binding_id", None),
    }


__all__ = (
    "canonical_json_bytes",
    "hmac_sha256",
    "managed_preflight_request_snapshot",
    "secret_commitments",
)
