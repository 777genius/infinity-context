"""HTTP adapter for signing request-scoped workspace identity."""

from __future__ import annotations

import hashlib
import hmac
import time

from infinity_context_core.features.agent_authorization.public import (
    AgentScopeResolutionMethod,
    WorkspaceScopeClaim,
    encode_workspace_scope_claim,
)

from infinity_context_mcp.workspace_binding import ResolvedAgentScope


def signed_workspace_scope_claim(
    scope: ResolvedAgentScope | None,
) -> str | None:
    if (
        scope is None
        or scope.repository_id is None
        or scope.code_scope_id is None
        or scope.binding_id is None
        or scope.binding_version is None
        or scope.binding_grant is None
        or scope.resolution_method != "trusted_binding"
        or scope.drift_status != "stable"
    ):
        return None
    claim = WorkspaceScopeClaim(
        issued_at_epoch_seconds=int(time.time()),
        repository_id=scope.repository_id,
        code_scope_id=scope.code_scope_id,
        resolution_method=AgentScopeResolutionMethod.TRUSTED_BINDING,
        binding_id=scope.binding_id,
        binding_version=scope.binding_version,
        drift_status=scope.drift_status,
    )
    encoded = encode_workspace_scope_claim(claim)
    envelope = f"v1.{encoded}"
    signature = hmac.new(
        scope.binding_grant.encode("utf-8"),
        envelope.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{envelope}.{signature}"


__all__ = ("signed_workspace_scope_claim",)
