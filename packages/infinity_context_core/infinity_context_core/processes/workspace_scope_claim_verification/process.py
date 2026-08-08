"""Cross-feature verification of signed repository workspace claims."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256

from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_core.features.agent_authorization.public import (
    AgentScopeResolutionMethod,
    WorkspaceScopeClaim,
)
from infinity_context_core.features.code_identity.public import (
    CodeScopeAuthorizationPort,
    CodeScopeAuthorizationStatus,
    WorkspaceBindingReadPort,
    WorkspaceBindingStatus,
)


@dataclass(frozen=True, slots=True)
class VerifyWorkspaceScopeClaimCommand:
    claim: WorkspaceScopeClaim
    signed_value: str
    supplied_signature: str
    binding_grant: str
    token_space_id: str
    token_repository_id: str
    token_code_scope_id: str | None
    now_epoch_seconds: int


@dataclass(frozen=True, slots=True)
class WorkspaceScopeClaimVerifier:
    bindings: WorkspaceBindingReadPort
    scope_authorizations: CodeScopeAuthorizationPort
    max_age_seconds: int = 300
    future_skew_seconds: int = 60

    async def execute(
        self,
        command: VerifyWorkspaceScopeClaimCommand,
    ) -> WorkspaceScopeClaim:
        claim = command.claim
        if (
            claim.resolution_method is not AgentScopeResolutionMethod.TRUSTED_BINDING
            or claim.binding_id is None
            or claim.binding_version is None
            or claim.drift_status != "stable"
        ):
            raise MemoryForbiddenError("Workspace claim requires a stable trusted binding")
        if claim.repository_id != command.token_repository_id:
            raise MemoryForbiddenError("Workspace claim cannot override token repository")
        binding = await self.bindings.get(claim.binding_id)
        if (
            binding is None
            or binding.status is not WorkspaceBindingStatus.ACTIVE
            or binding.repository_id != command.token_repository_id
            or binding.space_id != command.token_space_id
            or binding.version != claim.binding_version
            or not hmac.compare_digest(
                binding.grant_hash,
                sha256(command.binding_grant.encode("utf-8")).hexdigest(),
            )
        ):
            raise MemoryForbiddenError("Workspace binding grant is invalid or inactive")
        expected_signature = hmac.new(
            command.binding_grant.encode("utf-8"),
            command.signed_value.encode("ascii"),
            sha256,
        ).hexdigest()
        if not hmac.compare_digest(command.supplied_signature, expected_signature):
            raise MemoryForbiddenError("Invalid workspace scope claim signature")
        age = command.now_epoch_seconds - claim.issued_at_epoch_seconds
        if age > self.max_age_seconds or age < -self.future_skew_seconds:
            raise MemoryForbiddenError("Workspace scope claim is expired or not yet valid")
        if command.token_code_scope_id is not None:
            if claim.code_scope_id != command.token_code_scope_id:
                raise MemoryForbiddenError("Workspace claim cannot override token CodeScope")
            return claim
        authorization = await self.scope_authorizations.get(
            repository_id=claim.repository_id,
            space_id=command.token_space_id,
            code_scope_id=claim.code_scope_id,
        )
        if (
            authorization is None
            or authorization.status is not CodeScopeAuthorizationStatus.ACTIVE
        ):
            raise MemoryForbiddenError("Workspace CodeScope is not authorized by the server")
        return claim


__all__ = ("VerifyWorkspaceScopeClaimCommand", "WorkspaceScopeClaimVerifier")
