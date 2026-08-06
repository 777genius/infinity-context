"""PostgreSQL read adapter for trusted workspace bindings."""

from infinity_context_core.features.code_identity.public import (
    WorkspaceBindingSnapshot,
    WorkspaceBindingStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.feature_models import CodeRepositoryBindingRow


class PostgresWorkspaceBindingReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, binding_id: str) -> WorkspaceBindingSnapshot | None:
        row = await self._session.get(CodeRepositoryBindingRow, binding_id)
        if row is None:
            return None
        return WorkspaceBindingSnapshot(
            binding_id=row.id,
            repository_id=row.repository_id,
            space_id=row.space_id,
            version=row.version,
            grant_hash=row.grant_hash,
            status=WorkspaceBindingStatus(row.status),
        )


__all__ = ("PostgresWorkspaceBindingReader",)
