"""Select document-sourced fact candidates in canonical lock order."""

from __future__ import annotations

from collections.abc import Collection

from infinity_context_core.features.memory_facts.application.locking import (
    memory_fact_identity_lock_key,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdentity,
    MemoryFactScope,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import MemoryFactRow, MemorySourceRefRow


async def document_fact_candidates_in_lock_order(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    document_id: str,
    chunk_ids: Collection[str],
) -> tuple[MemoryFactIdentity, ...]:
    """Return current document fact candidates ordered by the shared lock key."""

    rows = (
        await session.execute(
            select(
                MemoryFactRow.id,
                MemoryFactRow.space_id,
                MemoryFactRow.memory_scope_id,
                MemoryFactRow.thread_id,
            )
            .join(
                MemorySourceRefRow,
                (MemorySourceRefRow.fact_id == MemoryFactRow.id)
                & (MemorySourceRefRow.fact_version == MemoryFactRow.version),
            )
            .where(
                MemoryFactRow.status == "active",
                MemoryFactRow.space_id == space_id,
                MemoryFactRow.memory_scope_id == memory_scope_id,
                or_(
                    MemorySourceRefRow.chunk_id.in_(chunk_ids),
                    (MemorySourceRefRow.source_type == "document")
                    & (MemorySourceRefRow.source_id == document_id),
                ),
            )
            .distinct()
        )
    ).all()
    candidates = (
        MemoryFactIdentity(
            fact_id=row.id,
            scope=MemoryFactScope(
                space_id=row.space_id,
                memory_scope_id=row.memory_scope_id,
                thread_id=row.thread_id,
            ),
        )
        for row in rows
    )
    return tuple(sorted(candidates, key=memory_fact_identity_lock_key))
