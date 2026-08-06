"""Application policy for admin-attested dynamic CodeScopes."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.code_identity.domain import (
    CodeRepositoryStatus,
    CodeScopeAuthorization,
    CodeScopeAuthorizationStatus,
    CodeScopeLevel,
)
from infinity_context_core.features.code_identity.ports import (
    CodeRepositoryClockPort,
    CodeRepositoryPort,
    CodeScopeAuthorizationIdPort,
    CodeScopeAuthorizationPort,
)


@dataclass(frozen=True, slots=True)
class RegisterCodeScopeAuthorizationCommand:
    repository_id: str
    space_id: str
    code_scope_id: str
    scope_level: CodeScopeLevel
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class RegisterCodeScopeAuthorizationResult:
    authorization: CodeScopeAuthorization
    created: bool


@dataclass(frozen=True, slots=True)
class RegisterCodeScopeAuthorizationHandler:
    repositories: CodeRepositoryPort
    authorizations: CodeScopeAuthorizationPort
    clock: CodeRepositoryClockPort
    ids: CodeScopeAuthorizationIdPort

    async def execute(
        self,
        command: RegisterCodeScopeAuthorizationCommand,
    ) -> RegisterCodeScopeAuthorizationResult:
        repository = await self.repositories.get(command.repository_id)
        if repository is None or repository.space_id != command.space_id:
            raise LookupError("CodeRepository not found in requested space")
        if repository.status is not CodeRepositoryStatus.ACTIVE:
            raise ValueError("Only an active CodeRepository can authorize CodeScopes")
        existing = await self.authorizations.get(
            repository_id=command.repository_id,
            space_id=command.space_id,
            code_scope_id=command.code_scope_id,
        )
        if existing is not None:
            if existing.status is not CodeScopeAuthorizationStatus.ACTIVE:
                raise ValueError("CodeScope authorization is revoked")
            if (
                existing.scope_level is not CodeScopeLevel(command.scope_level)
                or existing.evidence_digest != command.evidence_digest
            ):
                raise ValueError("CodeScope authorization conflicts with existing attestation")
            return RegisterCodeScopeAuthorizationResult(existing, created=False)
        authorization = CodeScopeAuthorization.create(
            authorization_id=self.ids.new_code_scope_authorization_id(),
            repository_id=command.repository_id,
            space_id=command.space_id,
            code_scope_id=command.code_scope_id,
            scope_level=command.scope_level,
            evidence_digest=command.evidence_digest,
            now=self.clock.now(),
        )
        saved = await self.authorizations.create(authorization)
        return RegisterCodeScopeAuthorizationResult(saved, created=True)


__all__ = (
    "RegisterCodeScopeAuthorizationCommand",
    "RegisterCodeScopeAuthorizationHandler",
    "RegisterCodeScopeAuthorizationResult",
)
