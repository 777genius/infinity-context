"""Canonical evidence liveness checks for document deletion."""

from __future__ import annotations

from infinity_context_core.domain.entities import MemoryFact, SourceRef
from infinity_context_core.features.memory_facts.public import MemoryFactIdentity
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemorySourceRefRow,
)


async def load_candidate_evidence_state(
    session: AsyncSession,
    identities: tuple[MemoryFactIdentity, ...],
) -> tuple[dict[str, MemoryChunkRow], dict[str, MemoryDocumentRow]]:
    """Load state already locked by the document-first deletion protocol."""

    if not identities:
        return {}, {}
    candidate_rows = tuple(
        (
            await session.execute(
                select(MemoryFactRow.id, MemoryFactRow.version).where(
                    MemoryFactRow.id.in_(tuple(identity.fact_id for identity in identities))
                )
            )
        ).all()
    )
    refs = tuple(
        (
            await session.execute(
                select(MemorySourceRefRow).where(
                    tuple_(MemorySourceRefRow.fact_id, MemorySourceRefRow.fact_version).in_(
                        candidate_rows
                    )
                )
            )
        ).scalars()
    )
    chunk_ids = {ref.chunk_id for ref in refs if ref.chunk_id is not None}
    chunks = tuple(
        (
            await session.execute(
                select(MemoryChunkRow)
                .where(MemoryChunkRow.id.in_(chunk_ids))
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    document_ids = {
        ref.source_id for ref in refs if ref.source_type == "document" and ref.source_id
    }
    document_ids.update(chunk.document_id for chunk in chunks if chunk.document_id is not None)
    documents = tuple(
        (
            await session.execute(
                select(MemoryDocumentRow)
                .where(MemoryDocumentRow.id.in_(document_ids))
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    return ({row.id: row for row in chunks}, {row.id: row for row in documents})


def source_ref_has_live_evidence(
    ref: SourceRef,
    *,
    fact: MemoryFact,
    chunks_by_id: dict[str, MemoryChunkRow],
    documents_by_id: dict[str, MemoryDocumentRow],
) -> bool:
    """Return whether a current ref retains live evidence after a deletion set."""

    if ref.chunk_id is None and ref.source_type != "document":
        return True
    if ref.chunk_id is not None:
        chunk = chunks_by_id.get(ref.chunk_id)
        if chunk is None or chunk.status != "active" or chunk.document_id is None:
            return False
        document = documents_by_id.get(chunk.document_id)
        if document is None or document.status != "active":
            return False
        if ref.source_type == "document" and ref.source_id != document.id:
            return False
        return _matches_fact(fact=fact, document=document, chunk=chunk)
    document = documents_by_id.get(ref.source_id)
    return bool(
        document is not None
        and document.status == "active"
        and _matches_fact(fact=fact, document=document)
    )


def _matches_fact(
    *, fact: MemoryFact, document: MemoryDocumentRow, chunk: MemoryChunkRow | None = None
) -> bool:
    fact_thread_id = str(fact.thread_id) if fact.thread_id is not None else None
    if (
        document.space_id != str(fact.space_id)
        or document.memory_scope_id != str(fact.memory_scope_id)
        or not _thread_visible(document.thread_id, fact_thread_id)
    ):
        return False
    return chunk is None or (
        chunk.space_id == document.space_id
        and chunk.memory_scope_id == document.memory_scope_id
        and chunk.thread_id == document.thread_id
        and chunk.document_id == document.id
    )


def _thread_visible(owner_thread_id: str | None, fact_thread_id: str | None) -> bool:
    return (
        owner_thread_id is None
        if fact_thread_id is None
        else owner_thread_id
        in {
            None,
            fact_thread_id,
        }
    )


__all__ = ("load_candidate_evidence_state", "source_ref_has_live_evidence")
