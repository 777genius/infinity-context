"""Canonical evidence liveness checks for document deletion."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.domain.entities import MemoryFact, SourceRef
from infinity_context_core.features.memory_facts.public import MemoryFactIdentity
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemorySourceRefRow,
)


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceState:
    chunks_by_id: dict[str, MemoryChunkRow]
    documents_by_id: dict[str, MemoryDocumentRow]
    episodes_by_id: dict[str, MemoryEpisodeRow]


async def load_candidate_evidence_state(
    session: AsyncSession,
    identities: tuple[MemoryFactIdentity, ...],
) -> CanonicalEvidenceState:
    """Load state already locked by the document-first deletion protocol."""

    if not identities:
        return CanonicalEvidenceState({}, {}, {})
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
        ref.source_id
        for ref in refs
        if ref.source_type == "document" and ref.chunk_id is None and ref.source_id
    }
    document_ids.update(chunk.document_id for chunk in chunks if chunk.document_id is not None)
    episode_ids = {chunk.episode_id for chunk in chunks if chunk.episode_id is not None}
    documents = tuple(
        (
            await session.execute(
                select(MemoryDocumentRow)
                .where(MemoryDocumentRow.id.in_(document_ids))
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    episodes = tuple(
        (
            await session.execute(
                select(MemoryEpisodeRow).where(MemoryEpisodeRow.id.in_(episode_ids))
            )
        ).scalars()
    )
    return CanonicalEvidenceState(
        chunks_by_id={row.id: row for row in chunks},
        documents_by_id={row.id: row for row in documents},
        episodes_by_id={row.id: row for row in episodes},
    )


def source_ref_has_live_evidence(
    ref: SourceRef,
    *,
    fact: MemoryFact,
    evidence: CanonicalEvidenceState,
) -> bool:
    """Return whether a current ref retains live evidence after a deletion set."""

    if ref.chunk_id is None and ref.source_type != "document":
        return True
    if ref.chunk_id is not None:
        chunk = evidence.chunks_by_id.get(ref.chunk_id)
        if chunk is None or chunk.status != "active":
            return False
        if chunk.document_id is not None:
            owner = evidence.documents_by_id.get(chunk.document_id)
        elif chunk.episode_id is not None:
            owner = evidence.episodes_by_id.get(chunk.episode_id)
        else:
            return False
        if owner is None or owner.status != "active":
            return False
        return _matches_fact(
            fact=fact,
            owner_space_id=owner.space_id,
            owner_memory_scope_id=owner.memory_scope_id,
            owner_thread_id=owner.thread_id,
        ) and (
            chunk.space_id == owner.space_id
            and chunk.memory_scope_id == owner.memory_scope_id
            and chunk.thread_id == owner.thread_id
        )
    document = evidence.documents_by_id.get(ref.source_id)
    return bool(
        document is not None
        and document.status == "active"
        and _matches_fact(
            fact=fact,
            owner_space_id=document.space_id,
            owner_memory_scope_id=document.memory_scope_id,
            owner_thread_id=document.thread_id,
        )
    )


def _matches_fact(
    *,
    fact: MemoryFact,
    owner_space_id: str,
    owner_memory_scope_id: str,
    owner_thread_id: str | None,
) -> bool:
    fact_thread_id = str(fact.thread_id) if fact.thread_id is not None else None
    return (
        owner_space_id == str(fact.space_id)
        and owner_memory_scope_id == str(fact.memory_scope_id)
        and _thread_visible(owner_thread_id, fact_thread_id)
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


__all__ = (
    "CanonicalEvidenceState",
    "load_candidate_evidence_state",
    "source_ref_has_live_evidence",
)
