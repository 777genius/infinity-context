"""Stable production eligibility and implementation identity for managed-v5 policy."""

from __future__ import annotations

import hashlib

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    lifecycle_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_RETRYABLE_DELETE_FAILURE_CODES = frozenset(
    {
        "managed_http_policy_infinity_context_delete_failed",
        "managed_v5_policy_mem0_cleanup_failed",
    }
)


def managed_http_policy_production_blockers(
    cases: tuple[ManagedRunCase, ...],
) -> tuple[str, ...]:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(case) is not ManagedRunCase for case in cases)
    ):
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_cases_invalid")
    return ()


def managed_v5_policy_lifecycle_implementation_sha256() -> str:
    return hashlib.sha256(
        (
            "managed-infinity-v5-policy-v1\0"
            + lifecycle_implementation_sha256()
            + "\0exact-owner-bound-ingest\0split-v5-cleanup"
        ).encode()
    ).hexdigest()


def managed_v5_target_identity(bindings: FullComparisonRunBindings, role: str) -> str:
    matches = tuple(
        target.target_identity_sha256
        for target in bindings.backend_targets
        if target.backend_role == role
    )
    if len(matches) != 1:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_target_binding_invalid")
    return matches[0]


def managed_v5_retryable_delete_failure(error: ManagedHttpPolicyLifecycleError) -> bool:
    return error.code in _RETRYABLE_DELETE_FAILURE_CODES


__all__ = (
    "managed_http_policy_production_blockers",
    "managed_v5_policy_lifecycle_implementation_sha256",
    "managed_v5_target_identity",
    "managed_v5_retryable_delete_failure",
)
