"""Postgres adapter for server-owned dynamic CodeScope authorization."""

from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.features.code_identity.public import (
    CodeScopeAuthorization,
    CodeScopeAuthorizationStatus,
    CodeScopeLevel,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.feature_models import CodeScopeAuthorizationRow


class PostgresCodeScopeAuthorization:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        repository_id: str,
        space_id: str,
        code_scope_id: str,
    ) -> CodeScopeAuthorization | None:
        row = (
            await self._session.execute(
                select(CodeScopeAuthorizationRow).where(
                    CodeScopeAuthorizationRow.repository_id == repository_id,
                    CodeScopeAuthorizationRow.space_id == space_id,
                    CodeScopeAuthorizationRow.code_scope_id == code_scope_id,
                )
            )
        ).scalar_one_or_none()
        return _row_to_domain(row) if row is not None else None

    async def create(
        self,
        authorization: CodeScopeAuthorization,
    ) -> CodeScopeAuthorization:
        self._session.add(
            CodeScopeAuthorizationRow(
                id=authorization.authorization_id,
                repository_id=authorization.repository_id,
                space_id=authorization.space_id,
                code_scope_id=authorization.code_scope_id,
                scope_level=authorization.scope_level.value,
                evidence_digest=authorization.evidence_digest,
                status=authorization.status.value,
                version=authorization.version,
                created_at=authorization.created_at,
                updated_at=authorization.updated_at,
            )
        )
        return authorization


def _row_to_domain(row: CodeScopeAuthorizationRow) -> CodeScopeAuthorization:
    return CodeScopeAuthorization(
        authorization_id=row.id,
        repository_id=row.repository_id,
        space_id=row.space_id,
        code_scope_id=row.code_scope_id,
        scope_level=CodeScopeLevel(row.scope_level),
        evidence_digest=row.evidence_digest,
        status=CodeScopeAuthorizationStatus(row.status),
        version=row.version,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ("PostgresCodeScopeAuthorization",)
