"""Postgres coordination for documents and fact source-reference writers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow


class SourceRefLike(Protocol):
    source_type: str
    source_id: str
    chunk_id: str | None


async def lock_thread_fact_writes(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
) -> None:
    """Serialize thread deletion with every fact write in that exact thread."""

    if session.get_bind().dialect.name != "postgresql":
        return
    identity = f"thread-fact-writes:{space_id}:{memory_scope_id}:{thread_id}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": identity},
    )


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
    thread_id: str | None,
    source_refs: Iterable[SourceRefLike],
) -> None:
    """Resolve and lock every canonical document reference before fact writes.

    A chunk id is always a canonical reference. A document source without a chunk id
    is canonical by its source id. Resolution deliberately happens without a scope
    predicate so missing and cross-scope references can be distinguished from valid
    local evidence and rejected instead of silently bypassing coordination.
    """

    if thread_id is not None:
        await lock_thread_fact_writes(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )

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

    if set(resolved_chunk_parents) != set(chunk_ids):
        raise MemoryConflictError("Fact source references a missing canonical chunk")
    if any(document_id is None for document_id in resolved_chunk_parents.values()):
        raise MemoryConflictError("Fact source chunk has no canonical parent document")

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
                    select(MemoryChunkRow)
                    .where(MemoryChunkRow.id.in_(chunk_ids))
                    .order_by(MemoryChunkRow.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )

    if set(chunks_by_id) != set(chunk_ids):
        raise MemoryConflictError("Fact source references a missing canonical chunk")
    if any(chunk.document_id is None for chunk in chunks_by_id.values()):
        raise MemoryConflictError("Fact source chunk has no canonical parent document")
    if {
        chunk_id: chunk.document_id for chunk_id, chunk in chunks_by_id.items()
    } != resolved_chunk_parents:
        raise MemoryConflictError("Fact source chunk parent changed during coordination")
    if set(documents_by_id) != document_ids:
        raise MemoryConflictError("Fact source references a missing canonical document")
    if any(
        chunk.space_id != space_id or chunk.memory_scope_id != memory_scope_id
        for chunk in chunks_by_id.values()
    ):
        raise MemoryConflictError("Fact source reference is outside the requested scope")
    if any(
        document.space_id != space_id or document.memory_scope_id != memory_scope_id
        for document in documents_by_id.values()
    ):
        raise MemoryConflictError("Fact source reference is outside the requested scope")
    if any(document.status != "active" for document in documents_by_id.values()):
        raise MemoryConflictError("Fact source references a deleted document")
    if any(chunk.status != "active" for chunk in chunks_by_id.values()):
        raise MemoryConflictError("Fact source references an inactive canonical chunk")
    if any(
        chunks_by_id[ref.chunk_id].document_id != ref.source_id
        for ref in refs
        if ref.source_type == "document" and ref.chunk_id is not None
    ):
        raise MemoryConflictError("Fact source chunk does not belong to its document")
    if any(
        not _thread_visible(owner_thread_id=chunk.thread_id, fact_thread_id=thread_id)
        for chunk in chunks_by_id.values()
    ) or any(
        not _thread_visible(owner_thread_id=document.thread_id, fact_thread_id=thread_id)
        for document in documents_by_id.values()
    ):
        raise MemoryConflictError("Fact source reference is outside the requested thread scope")
    if any(
        chunk.thread_id != documents_by_id[chunk.document_id].thread_id
        for chunk in chunks_by_id.values()
    ):
        raise MemoryConflictError("Fact source chunk and document scopes do not match")


def _thread_visible(*, owner_thread_id: str | None, fact_thread_id: str | None) -> bool:
    if fact_thread_id is None:
        return owner_thread_id is None
    return owner_thread_id is None or owner_thread_id == fact_thread_id


__all__ = (
    "coordinate_document_source_ref_write",
    "lock_document_for_fact_cleanup",
    "lock_thread_fact_writes",
)
