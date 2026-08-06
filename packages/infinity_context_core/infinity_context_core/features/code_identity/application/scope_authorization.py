"""Application policy for admin-attested dynamic CodeScopes."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.code_identity.domain import (
    CodeRepositoryStatus,
    CodeScope,
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
    space_id: str
    scope: CodeScope


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
        scope = command.scope
        if scope.repository_id is None or scope.scope_level not in {
            CodeScopeLevel.REPOSITORY,
            CodeScopeLevel.BRANCH,
            CodeScopeLevel.COMMIT,
        }:
            raise ValueError("Only repository, branch or commit CodeScopes can be authorized")
        repository = await self.repositories.get(scope.repository_id)
        if repository is None or repository.space_id != command.space_id:
            raise LookupError("CodeRepository not found in requested space")
        if repository.status is not CodeRepositoryStatus.ACTIVE:
            raise ValueError("Only an active CodeRepository can authorize CodeScopes")
        existing = await self.authorizations.get(
            repository_id=scope.repository_id,
            space_id=command.space_id,
            code_scope_id=scope.code_scope_id,
        )
        if existing is not None:
            if existing.status is not CodeScopeAuthorizationStatus.ACTIVE:
                raise ValueError("CodeScope authorization is revoked")
            if (
                existing.scope_level is not scope.scope_level
                or existing.evidence_digest != scope.authorization_evidence_digest
            ):
                raise ValueError("CodeScope authorization conflicts with existing attestation")
            return RegisterCodeScopeAuthorizationResult(existing, created=False)
        authorization = CodeScopeAuthorization.create(
            authorization_id=self.ids.new_code_scope_authorization_id(),
            repository_id=scope.repository_id,
            space_id=command.space_id,
            code_scope_id=scope.code_scope_id,
            scope_level=scope.scope_level,
            evidence_digest=scope.authorization_evidence_digest,
            now=self.clock.now(),
        )
        saved = await self.authorizations.create(authorization)
        return RegisterCodeScopeAuthorizationResult(saved, created=True)


__all__ = (
    "RegisterCodeScopeAuthorizationCommand",
    "RegisterCodeScopeAuthorizationHandler",
    "RegisterCodeScopeAuthorizationResult",
)
