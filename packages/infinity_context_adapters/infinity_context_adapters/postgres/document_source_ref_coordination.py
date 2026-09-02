"""Postgres coordination for documents and fact source-reference writers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow


class SourceRefLike(Protocol):
    source_type: str
    source_id: str
    chunk_id: str | None


async def lock_document_for_fact_cleanup(
    session: AsyncSession,
    *,
    document_id: str,
) -> MemoryDocumentRow | None:
    """Admit document deletion before any related fact-row locks are taken."""

    return (
        await session.execute(
            select(MemoryDocumentRow)
            .where(MemoryDocumentRow.id == document_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def coordinate_document_source_ref_write(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    source_refs: Iterable[SourceRefLike],
) -> None:
    """Lock referenced canonical documents before a writer locks or writes facts.

    Only locally resolvable document references participate. External references retain
    their existing provider-neutral semantics. Locks are ordered by document id so a
    multi-document fact has the same document-before-fact order as document deletion.
    """

    refs = tuple(source_refs)
    direct_document_ids = tuple(
        sorted(
            {
                ref.source_id
                for ref in refs
                if ref.source_type == "document" and ref.source_id
            }
        )
    )
    chunk_ids = tuple(sorted({ref.chunk_id for ref in refs if ref.chunk_id}))
    if not direct_document_ids and not chunk_ids:
        return

    document_ids: set[str] = set()
    if direct_document_ids:
        document_ids.update(
            (
                await session.execute(
                    select(MemoryDocumentRow.id).where(
                        MemoryDocumentRow.id.in_(direct_document_ids),
                        MemoryDocumentRow.space_id == space_id,
                        MemoryDocumentRow.memory_scope_id == memory_scope_id,
                    )
                )
            ).scalars()
        )
    if chunk_ids:
        document_ids.update(
            (
                await session.execute(
                    select(MemoryChunkRow.document_id).where(
                        MemoryChunkRow.id.in_(chunk_ids),
                        MemoryChunkRow.space_id == space_id,
                        MemoryChunkRow.memory_scope_id == memory_scope_id,
                    )
                )
            ).scalars()
        )
    if not document_ids:
        return

    documents = tuple(
        (
            await session.execute(
                select(MemoryDocumentRow)
                .where(MemoryDocumentRow.id.in_(tuple(sorted(document_ids))))
                .order_by(MemoryDocumentRow.id)
                .with_for_update()
            )
        ).scalars()
    )
    if any(document.status != "active" for document in documents):
        raise MemoryConflictError("Fact source references a deleted document")


__all__ = (
    "coordinate_document_source_ref_write",
    "lock_document_for_fact_cleanup",
)
