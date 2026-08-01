"""Credential continuity seam for managed HTTP reset and ingestion."""

from __future__ import annotations

from datetime import datetime

from infinity_context_server import (
    memory_comparison_managed_runtime_credentials_capability as credential_capability,
)
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    INFINITY_COMPARISON_BACKEND,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
    ManagedMem0HttpConfig,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedPreflightRequest,
    validate_managed_preflight,
)


class ManagedHttpLifecycleCredentialError(ValueError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def consume_managed_http_lifecycle_credentials(
    *,
    preflight_request: ManagedPreflightRequest,
    credential_material: object,
    run_id: str,
    deadline: datetime,
    admitted_targets: tuple[FullComparisonBackendTarget, ...],
) -> tuple[ManagedInfinityHttpConfig, ManagedMem0HttpConfig]:
    if type(preflight_request) is not ManagedPreflightRequest:
        _fail("managed_http_lifecycle_preflight_invalid")
    try:
        preflight = validate_managed_preflight(preflight_request)
    except Exception:
        _fail("managed_http_lifecycle_preflight_invalid")
    if tuple(item.target for item in preflight.backend_endpoints) != admitted_targets:
        _fail("managed_http_lifecycle_preflight_target_mismatch")
    if (
        type(credential_material)
        is not credential_capability.ManagedBackendCredentialMaterial
    ):
        _fail("managed_http_lifecycle_credential_invalid")
    try:
        infinity, mem0 = credential_material.consume_for_http_lifecycle(
            expected_request=preflight_request,
            run_id=run_id,
            deadline=deadline,
        )
    except (TypeError, ValueError):
        _fail("managed_http_lifecycle_credential_continuity_failed")
    if (
        type(infinity) is not ManagedInfinityHttpConfig
        or type(mem0) is not ManagedMem0HttpConfig
    ):
        _fail("managed_http_lifecycle_config_invalid")
    targets = {
        item.backend_role: item.target_identity_sha256 for item in admitted_targets
    }
    if targets != {
        INFINITY_COMPARISON_BACKEND: infinity.target_identity_sha256,
        "mem0": mem0.target_identity_sha256,
    }:
        _fail("managed_http_lifecycle_config_target_mismatch")
    return infinity, mem0


def _fail(code: str) -> None:
    raise ManagedHttpLifecycleCredentialError(code)


__all__ = ()
