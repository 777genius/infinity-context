"""Atomic process for strict-admin CodeScope authorization."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from infinity_context_adapters.features.code_identity import (
    PostgresCodeRepository,
    PostgresCodeScopeAuthorization,
)
from infinity_context_core.features.code_identity.public import (
    RegisterCodeScopeAuthorizationCommand,
    RegisterCodeScopeAuthorizationHandler,
    RegisterCodeScopeAuthorizationResult,
)
from infinity_context_core.ports.clock import ClockPort
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class CodeScopeAuthorizationProcess:
    session_factory: async_sessionmaker[AsyncSession]
    clock: ClockPort

    async def execute(
        self,
        command: RegisterCodeScopeAuthorizationCommand,
    ) -> RegisterCodeScopeAuthorizationResult:
        async with self.session_factory() as session:
            handler = RegisterCodeScopeAuthorizationHandler(
                repositories=PostgresCodeRepository(session),
                authorizations=PostgresCodeScopeAuthorization(session),
                clock=self.clock,
                ids=_AuthorizationIds(),
            )
            try:
                result = await handler.execute(command)
                await session.commit()
                return result
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(
                    "CodeScope authorization conflicted with concurrent state"
                ) from exc


class _AuthorizationIds:
    def new_code_scope_authorization_id(self) -> str:
        return f"scope-authorization-{uuid4().hex}"


__all__ = ("CodeScopeAuthorizationProcess",)
