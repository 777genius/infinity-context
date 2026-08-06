"""Atomic cross-context process for repository resolution and binding issuance."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from infinity_context_adapters.features.code_identity import (
    PostgresCodeRepository,
    PostgresCodeScopeAuthorization,
)
from infinity_context_adapters.postgres.feature_models import CodeRepositoryBindingRow
from infinity_context_adapters.postgres.models import MemorySpaceRow
from infinity_context_core.features.code_identity.public import (
    CodeRepository,
    CodeScopeAuthorization,
    CodeScopeDescriptor,
    RegisterCodeScopeAuthorizationCommand,
    RegisterCodeScopeAuthorizationHandler,
    ResolveCodeRepositoryCommand,
    ResolveCodeRepositoryHandler,
    ResolveCodeRepositoryResult,
)
from infinity_context_core.ports.clock import ClockPort
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class CodeRepositoryEnrollmentResult:
    repository: CodeRepository
    resolution_method: str
    binding_id: str
    binding_version: int
    binding_grant: str
    scope_authorization: CodeScopeAuthorization | None = None


@dataclass(frozen=True, slots=True)
class CodeRepositoryEnrollmentProcess:
    """Keep transport mapping outside one atomic repository/binding transaction."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: ClockPort
    new_binding_id: Callable[[], str] = lambda: f"binding-{uuid4().hex}"
    new_binding_grant: Callable[[], str] = lambda: f"wg_{secrets.token_urlsafe(32)}"

    async def execute(
        self,
        command: ResolveCodeRepositoryCommand,
        *,
        initial_scope: CodeScopeDescriptor | None = None,
    ) -> CodeRepositoryEnrollmentResult:
        async with self.session_factory() as session:
            try:
                space = await session.get(MemorySpaceRow, command.space_id)
                if space is None or space.status != "active":
                    raise LookupError("Active MemorySpace not found")
                resolution = await ResolveCodeRepositoryHandler(
                    repositories=PostgresCodeRepository(session),
                    clock=self.clock,
                    ids=_RepositoryIds(),
                ).execute(command)
                scope_authorization = None
                if initial_scope is not None:
                    scope = initial_scope.resolve(resolution.repository.repository_id)
                    scope_authorization = (
                        await RegisterCodeScopeAuthorizationHandler(
                            repositories=PostgresCodeRepository(session),
                            authorizations=PostgresCodeScopeAuthorization(session),
                            clock=self.clock,
                            ids=_RepositoryIds(),
                        ).execute(
                            RegisterCodeScopeAuthorizationCommand(
                                space_id=resolution.repository.space_id,
                                scope=scope,
                            )
                        )
                    ).authorization
                result = self._issue_binding(
                    session,
                    resolution,
                    scope_authorization=scope_authorization,
                )
                await session.commit()
                return result
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("Repository enrollment conflicted with concurrent state") from exc

    def _issue_binding(
        self,
        session: AsyncSession,
        resolution: ResolveCodeRepositoryResult,
        *,
        scope_authorization: CodeScopeAuthorization | None,
    ) -> CodeRepositoryEnrollmentResult:
        binding_id = self.new_binding_id()
        binding_grant = self.new_binding_grant()
        binding_version = 1
        repository = resolution.repository
        now = self.clock.now()
        session.add(
            CodeRepositoryBindingRow(
                id=binding_id,
                repository_id=repository.repository_id,
                space_id=repository.space_id,
                version=binding_version,
                grant_hash=sha256(binding_grant.encode("utf-8")).hexdigest(),
                evidence_json=[
                    {"kind": item.kind.value, "digest": item.digest} for item in repository.evidence
                ],
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        return CodeRepositoryEnrollmentResult(
            repository=repository,
            resolution_method=resolution.method.value,
            binding_id=binding_id,
            binding_version=binding_version,
            binding_grant=binding_grant,
            scope_authorization=scope_authorization,
        )


class _RepositoryIds:
    def new_repository_id(self) -> str:
        return f"repository-{uuid4().hex}"

    def new_code_scope_authorization_id(self) -> str:
        return f"scope-authorization-{uuid4().hex}"


__all__ = (
    "CodeRepositoryEnrollmentProcess",
    "CodeRepositoryEnrollmentResult",
)
