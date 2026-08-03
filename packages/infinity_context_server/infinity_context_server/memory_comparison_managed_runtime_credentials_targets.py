"""Backend target normalization for managed runtime credentials."""

from __future__ import annotations

from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
    managed_backend_target_identity_sha256,
)


def _normalized_backend(
    role: str,
    origin: str,
) -> tuple[str, FullComparisonBackendTarget]:
    identity = managed_backend_target_identity_sha256(backend_role=role, base_url=origin)
    endpoint = ManagedBackendEndpoint(
        target=FullComparisonBackendTarget(role, identity),
        base_url=origin,
        credential=ManagedCredentialBinding(role, True, "sha256:" + "0" * 64),
    )
    return endpoint.base_url, endpoint.target


__all__ = ()
