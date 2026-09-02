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
    """Resolve and lock every canonical document reference before fact writes.

    A chunk id is always a canonical reference. A document source without a chunk id
    is canonical by its source id. Resolution deliberately happens without a scope
    predicate so missing and cross-scope references can be distinguished from valid
    local evidence and rejected instead of silently bypassing coordination.
    """

    refs = tuple(source_refs)
    direct_document_ids = tuple(
        sorted(
            {
                ref.source_id
                for ref in refs
                if ref.source_type == "document" and not ref.chunk_id and ref.source_id
            }
        )
    )
    chunk_ids = tuple(sorted({ref.chunk_id for ref in refs if ref.chunk_id}))
    if not direct_document_ids and not chunk_ids:
        return

    resolved_chunk_parents: dict[str, str | None] = {}
    if chunk_ids:
        resolved_chunk_parents.update(
            (
                row.id,
                row.document_id,
            )
            for row in (
                await session.execute(
                    select(MemoryChunkRow.id, MemoryChunkRow.document_id).where(
                        MemoryChunkRow.id.in_(chunk_ids)
                    )
                )
            )
        )

    # Include requested direct ids even when they do not exist. The lock query then
    # locks the complete resolvable union, and completeness is checked afterwards.
    document_ids = set(direct_document_ids)
    document_ids.update(
        document_id
        for document_id in resolved_chunk_parents.values()
        if document_id is not None
    )

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
    documents_by_id = {document.id: document for document in documents}

    # Re-read chunks only after all resolvable parent documents have been locked.
    # Document deletion follows the same document-first protocol, so their lifecycle
    # state is now stable for the remainder of this transaction.
    chunks_by_id: dict[str, MemoryChunkRow] = {}
    if chunk_ids:
        chunks_by_id.update(
            (chunk.id, chunk)
            for chunk in (
                await session.execute(
                    select(MemoryChunkRow).where(MemoryChunkRow.id.in_(chunk_ids))
                )
            ).scalars()
        )

    if set(chunks_by_id) != set(chunk_ids):
        raise MemoryConflictError("Fact source references a missing canonical chunk")
    if any(chunk.document_id is None for chunk in chunks_by_id.values()):
        raise MemoryConflictError("Fact source chunk has no canonical parent document")
    if set(documents_by_id) != document_ids:
        raise MemoryConflictError("Fact source references a missing canonical document")
    if any(
        chunk.space_id != space_id or chunk.memory_scope_id != memory_scope_id
        for chunk in chunks_by_id.values()
    ):
        raise MemoryConflictError("Fact source reference is outside the requested scope")
    if any(chunk.status != "active" for chunk in chunks_by_id.values()):
        raise MemoryConflictError("Fact source references an inactive canonical chunk")
    if any(
        document.space_id != space_id or document.memory_scope_id != memory_scope_id
        for document in documents_by_id.values()
    ):
        raise MemoryConflictError("Fact source reference is outside the requested scope")
    if any(document.status != "active" for document in documents_by_id.values()):
        raise MemoryConflictError("Fact source references a deleted document")


__all__ = (
    "coordinate_document_source_ref_write",
    "lock_document_for_fact_cleanup",
)
