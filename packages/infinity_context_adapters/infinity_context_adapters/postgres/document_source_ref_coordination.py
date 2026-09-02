"""Postgres coordination for documents and fact source-reference writers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemorySourceRefRow,
    MemoryThreadRow,
)


class SourceRefLike(Protocol):
    source_type: str
    source_id: str
    chunk_id: str | None


class ScopedFactLike(Protocol):
    id: object
    space_id: object
    memory_scope_id: object
    thread_id: object | None


class ScopedChunkLike(Protocol):
    document_id: object | None
    space_id: object
    memory_scope_id: object
    thread_id: object | None


async def lock_global_fact_lifecycle(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
) -> None:
    """Serialize global fact writers with lifecycle operations in one scope."""

    if session.get_bind().dialect.name != "postgresql":
        return
    identity = f"global-fact-lifecycle:{space_id}:{memory_scope_id}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": identity},
    )


async def lock_exact_thread_lifecycle(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
) -> None:
    """Serialize every canonical writer and deletion in one exact thread."""

    if session.get_bind().dialect.name != "postgresql":
        return
    identity = f"exact-thread-lifecycle:{space_id}:{memory_scope_id}:{thread_id}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": identity},
    )


async def require_exact_thread_active(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
) -> None:
    """Fail a fenced writer when its exact canonical thread is not active."""

    row = await session.get(MemoryThreadRow, thread_id, populate_existing=True)
    if row is None or (
        row.space_id != space_id or row.memory_scope_id != memory_scope_id or row.status != "active"
    ):
        raise MemoryConflictError("Exact thread lifecycle is not active")


async def fence_exact_thread_writer(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str,
) -> None:
    """Acquire the shared fence and revalidate writer admission."""

    await lock_exact_thread_lifecycle(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
    )
    await require_exact_thread_active(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
    )


async def fence_fact_scope_writer(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
) -> None:
    """Acquire the canonical lifecycle fence for a global or exact-thread fact."""

    if thread_id is None:
        await lock_global_fact_lifecycle(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )
        return
    await fence_exact_thread_writer(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
    )


async def observe_and_fence_fact_update(
    session: AsyncSession,
    *,
    fact_id: str,
) -> MemoryFactRow | None:
    """Observe immutable fact scope and acquire its canonical lifecycle fence."""

    observed = await session.get(MemoryFactRow, fact_id)
    if observed is not None:
        await fence_fact_scope_writer(
            session,
            space_id=observed.space_id,
            memory_scope_id=observed.memory_scope_id,
            thread_id=observed.thread_id,
        )
    return observed


async def fence_scoped_fact_write(session: AsyncSession, fact: ScopedFactLike) -> None:
    """Acquire the shared lifecycle fence for every canonical fact write."""

    await fence_fact_scope_writer(
        session,
        space_id=str(fact.space_id),
        memory_scope_id=str(fact.memory_scope_id),
        thread_id=str(fact.thread_id) if fact.thread_id is not None else None,
    )


def scoped_fact_update_conditions(
    fact: ScopedFactLike,
    *,
    expected_version: int,
) -> tuple[object, ...]:
    """Keep legacy saves inside the immutable scope whose fence they acquired."""

    return (
        MemoryFactRow.id == str(fact.id),
        MemoryFactRow.version == expected_version,
        MemoryFactRow.space_id == str(fact.space_id),
        MemoryFactRow.memory_scope_id == str(fact.memory_scope_id),
        MemoryFactRow.thread_id == (str(fact.thread_id) if fact.thread_id is not None else None),
    )


async def lock_document_deletion_evidence(
    session: AsyncSession,
    *,
    document_id: str,
) -> tuple[MemoryDocumentRow, tuple[MemoryChunkRow, ...]] | None:
    """Fence deletion and lock its complete canonical evidence union."""

    observed = await session.get(MemoryDocumentRow, document_id)
    if observed is None:
        return None
    (
        target_chunk_ids,
        referenced_chunk_ids,
        document_ids,
        candidate_thread_ids,
        candidate_has_global_fact,
    ) = await _observe_deletion_union(session, document=observed)
    fenced_thread_ids = {
        *candidate_thread_ids,
        *(item for item in (observed.thread_id,) if item is not None),
    }
    if candidate_has_global_fact:
        await lock_global_fact_lifecycle(
            session,
            space_id=observed.space_id,
            memory_scope_id=observed.memory_scope_id,
        )
    for thread_id in sorted(fenced_thread_ids):
        await lock_exact_thread_lifecycle(
            session,
            space_id=observed.space_id,
            memory_scope_id=observed.memory_scope_id,
            thread_id=thread_id,
        )
    documents = tuple(
        (
            await session.execute(
                select(MemoryDocumentRow)
                .where(MemoryDocumentRow.id.in_(sorted(document_ids)))
                .order_by(MemoryDocumentRow.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    by_id = {row.id: row for row in documents}
    document = by_id.get(document_id)
    if document is None:
        return None
    if (
        document.space_id != observed.space_id
        or document.memory_scope_id != observed.memory_scope_id
        or document.thread_id != observed.thread_id
    ):
        raise MemoryConflictError("Document scope changed during deletion coordination")
    (
        latest_target_chunks,
        latest_referenced_chunks,
        latest_document_ids,
        latest_candidate_thread_ids,
        latest_has_global_fact,
    ) = await _observe_deletion_union(session, document=document)
    if (
        not latest_document_ids.issubset(by_id)
        or not latest_candidate_thread_ids.issubset(fenced_thread_ids)
        or (latest_has_global_fact and not candidate_has_global_fact)
    ):
        raise MemoryConflictError("Document evidence union changed during deletion coordination")
    target_chunk_ids = latest_target_chunks
    referenced_chunk_ids = latest_referenced_chunks
    all_chunk_ids = target_chunk_ids | referenced_chunk_ids
    chunks = tuple(
        (
            await session.execute(
                select(MemoryChunkRow)
                .where(MemoryChunkRow.id.in_(sorted(all_chunk_ids)))
                .order_by(MemoryChunkRow.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    return document, tuple(
        chunk for chunk in chunks if chunk.document_id == document_id and chunk.status == "active"
    )


async def _observe_deletion_union(
    session: AsyncSession,
    *,
    document: MemoryDocumentRow,
) -> tuple[set[str], set[str], set[str], set[str], bool]:
    target_chunk_ids = set(
        (
            await session.execute(
                select(MemoryChunkRow.id).where(MemoryChunkRow.document_id == document.id)
            )
        ).scalars()
    )
    candidate_rows = tuple(
        (
            await session.execute(
                select(MemoryFactRow.id, MemoryFactRow.version, MemoryFactRow.thread_id)
                .join(
                    MemorySourceRefRow,
                    (MemorySourceRefRow.fact_id == MemoryFactRow.id)
                    & (MemorySourceRefRow.fact_version == MemoryFactRow.version),
                )
                .where(
                    MemoryFactRow.status == "active",
                    MemoryFactRow.space_id == document.space_id,
                    MemoryFactRow.memory_scope_id == document.memory_scope_id,
                    or_(
                        MemorySourceRefRow.chunk_id.in_(target_chunk_ids),
                        (MemorySourceRefRow.source_type == "document")
                        & (MemorySourceRefRow.source_id == document.id),
                    ),
                )
                .distinct()
            )
        ).all()
    )
    candidate_pairs = tuple((row.id, row.version) for row in candidate_rows)
    refs = (
        tuple(
            (
                await session.execute(
                    select(MemorySourceRefRow).where(
                        tuple_(MemorySourceRefRow.fact_id, MemorySourceRefRow.fact_version).in_(
                            candidate_pairs
                        )
                    )
                )
            ).scalars()
        )
        if candidate_pairs
        else ()
    )
    referenced_chunk_ids = {ref.chunk_id for ref in refs if ref.chunk_id is not None}
    parent_ids = set(
        (
            await session.execute(
                select(MemoryChunkRow.document_id).where(
                    MemoryChunkRow.id.in_(referenced_chunk_ids)
                )
            )
        ).scalars()
    )
    document_ids = {document.id, *(item for item in parent_ids if item is not None)}
    document_ids.update(
        ref.source_id for ref in refs if ref.source_type == "document" and ref.source_id
    )
    candidate_thread_ids = {row.thread_id for row in candidate_rows if row.thread_id is not None}
    return (
        target_chunk_ids,
        referenced_chunk_ids,
        document_ids,
        candidate_thread_ids,
        any(row.thread_id is None for row in candidate_rows),
    )


async def lock_chunk_parent_for_write(
    session: AsyncSession,
    chunk: ScopedChunkLike,
) -> None:
    """Lock and validate a canonical chunk's document before mutation."""

    document_id = chunk.document_id
    if document_id is None:
        return
    document = (
        await session.execute(
            select(MemoryDocumentRow)
            .where(MemoryDocumentRow.id == str(document_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        document is None
        or document.status != "active"
        or (
            document.space_id != str(chunk.space_id)
            or document.memory_scope_id != str(chunk.memory_scope_id)
            or document.thread_id != (str(chunk.thread_id) if chunk.thread_id is not None else None)
        )
    ):
        raise MemoryConflictError("Chunk parent document lifecycle is not active")


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

    await coordinate_document_source_ref_batches(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        batches=((thread_id, tuple(source_refs)),),
    )


async def coordinate_document_source_ref_batches(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    batches: Iterable[tuple[str | None, Iterable[SourceRefLike]]],
) -> None:
    """Fence and validate a complete source-reference batch in lock order."""

    materialized = tuple((thread_id, tuple(refs)) for thread_id, refs in batches)
    if any(thread_id is None for thread_id, _refs in materialized):
        await lock_global_fact_lifecycle(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )
    for exact_thread_id in sorted(
        {thread_id for thread_id, _refs in materialized if thread_id is not None}
    ):
        await lock_exact_thread_lifecycle(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=exact_thread_id,
        )
    for exact_thread_id in sorted(
        {thread_id for thread_id, _refs in materialized if thread_id is not None}
    ):
        await require_exact_thread_active(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=exact_thread_id,
        )

    refs = tuple(ref for _thread_id, batch_refs in materialized for ref in batch_refs)
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
        document_id for document_id in resolved_chunk_parents.values() if document_id is not None
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
    for fact_thread_id, batch_refs in materialized:
        if any(
            ref.chunk_id is not None
            and not _thread_visible(
                owner_thread_id=chunks_by_id[ref.chunk_id].thread_id,
                fact_thread_id=fact_thread_id,
            )
            for ref in batch_refs
        ) or any(
            ref.source_type == "document"
            and ref.source_id in documents_by_id
            and not _thread_visible(
                owner_thread_id=documents_by_id[ref.source_id].thread_id,
                fact_thread_id=fact_thread_id,
            )
            for ref in batch_refs
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
    "coordinate_document_source_ref_batches",
    "coordinate_document_source_ref_write",
    "fence_fact_scope_writer",
    "fence_exact_thread_writer",
    "fence_scoped_fact_write",
    "lock_document_deletion_evidence",
    "lock_chunk_parent_for_write",
    "lock_exact_thread_lifecycle",
    "lock_global_fact_lifecycle",
    "observe_and_fence_fact_update",
    "require_exact_thread_active",
    "scoped_fact_update_conditions",
)
