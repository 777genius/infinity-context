"""Session boundary for workspace scope claim verification."""

from dataclasses import dataclass

from infinity_context_adapters.features.code_identity import (
    PostgresCodeScopeAuthorization,
    PostgresWorkspaceBindingReader,
)
from infinity_context_core.features.agent_authorization.public import WorkspaceScopeClaim
from infinity_context_core.processes.workspace_scope_claim_verification import (
    VerifyWorkspaceScopeClaimCommand,
    WorkspaceScopeClaimVerifier,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class WorkspaceScopeClaimVerificationProcess:
    session_factory: async_sessionmaker[AsyncSession]

    async def execute(
        self,
        command: VerifyWorkspaceScopeClaimCommand,
    ) -> WorkspaceScopeClaim:
        async with self.session_factory() as session:
            return await WorkspaceScopeClaimVerifier(
                bindings=PostgresWorkspaceBindingReader(session),
                scope_authorizations=PostgresCodeScopeAuthorization(session),
            ).execute(command)


__all__ = ("WorkspaceScopeClaimVerificationProcess",)
