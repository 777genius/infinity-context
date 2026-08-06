"""Postgres storage for rebuildable cognitive candidates and exact dependencies."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveCandidateIdentity,
    CognitiveProjectionDependencySet,
    CognitiveProjectionInvalidation,
    CognitiveScope,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.fact_selection_conditions import (
    memory_fact_selection_conditions,
)
from infinity_context_adapters.postgres.feature_models import (
    MemoryCognitiveDependencyRow,
    MemoryCognitiveProjectionRow,
)
from infinity_context_adapters.postgres.models import MemoryFactRow


class PostgresCognitiveProjectionStore:
    """Derived repository; Postgres facts remain the only canonical truth."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_if_evidence_current(
        self,
        candidate: CognitiveCandidate,
        *,
        current_visible_evidence: tuple[CanonicalEvidenceIdentity, ...],
        created_at: datetime,
    ) -> bool:
        if set(candidate.evidence_identities) != set(current_visible_evidence):
            return False
        if not await self._fact_evidence_is_current(candidate, created_at=created_at):
            return False
        await self._upsert(candidate, created_at=created_at)
        return True

    async def _fact_evidence_is_current(
        self,
        candidate: CognitiveCandidate,
        *,
        created_at: datetime,
    ) -> bool:
        evidence = candidate.evidence_identities
        if any(item.evidence_type != "fact" for item in evidence):
            return False
        fact_ids = tuple(item.evidence_id for item in evidence)
        conditions = memory_fact_selection_conditions(
            space_id=candidate.scope.space_id,
            memory_scope_ids=(candidate.scope.memory_scope_id,),
            thread_id=candidate.scope.thread_id,
            repository_id=None,
            code_scope_id=None,
            temporal_mode="current",
            reference_time=created_at,
            fact_ids=fact_ids,
        )
        rows = tuple(
            (
                await self._session.execute(
                    select(MemoryFactRow.id, MemoryFactRow.version)
                    .where(*conditions)
                    .with_for_update(read=True)
                )
            ).all()
        )
        actual = {(row.id, row.version) for row in rows}
        expected = {(item.evidence_id, item.version) for item in evidence}
        return actual == expected

    async def _upsert(
        self,
        candidate: CognitiveCandidate,
        *,
        created_at: datetime,
    ) -> None:
        key = candidate.identity.value
        existing = await self._session.get(MemoryCognitiveProjectionRow, key)
        if existing is not None:
            if (
                existing.content_hash != candidate.content_hash
                or existing.projection_version != candidate.projection_version.value
            ):
                raise ValueError("Deterministic cognitive identity collision")
            return
        scope = candidate.scope
        self._session.add(
            MemoryCognitiveProjectionRow(
                id=key,
                space_id=scope.space_id,
                memory_scope_id=scope.memory_scope_id,
                thread_id=scope.thread_id,
                kind=candidate.kind.value,
                derivation_origin=candidate.derivation_origin.value,
                content=candidate.content,
                content_hash=candidate.content_hash,
                projection_version=candidate.projection_version.value,
                confidence=candidate.confidence,
                valid_from=candidate.valid_from,
                valid_to=candidate.valid_to,
                state="active",
                invalidated_at=None,
                invalidation_reason=None,
                invalidation_event_id=None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        citations = {
            reference.identity: reference.citation for reference in candidate.evidence_refs
        }
        for identity in candidate.evidence_identities:
            self._session.add(
                MemoryCognitiveDependencyRow(
                    projection_id=key,
                    space_id=scope.space_id,
                    memory_scope_id=scope.memory_scope_id,
                    thread_id=scope.thread_id,
                    evidence_type=identity.evidence_type,
                    evidence_id=identity.evidence_id,
                    evidence_version=identity.version,
                    citation=citations[identity],
                    created_at=created_at,
                )
            )

    async def list_active_dependents(
        self,
        *,
        scope: CognitiveScope,
        evidence_type: str,
        evidence_id: str,
    ) -> tuple[CognitiveProjectionDependencySet, ...]:
        projection_rows = tuple(
            (
                await self._session.execute(
                    select(
                        MemoryCognitiveDependencyRow.projection_id,
                        MemoryCognitiveProjectionRow.space_id,
                        MemoryCognitiveProjectionRow.memory_scope_id,
                        MemoryCognitiveProjectionRow.thread_id,
                    )
                    .join(
                        MemoryCognitiveProjectionRow,
                        MemoryCognitiveProjectionRow.id
                        == MemoryCognitiveDependencyRow.projection_id,
                    )
                    .where(
                        MemoryCognitiveProjectionRow.space_id == scope.space_id,
                        MemoryCognitiveProjectionRow.memory_scope_id == scope.memory_scope_id,
                        MemoryCognitiveProjectionRow.state == "active",
                        MemoryCognitiveDependencyRow.evidence_type == evidence_type,
                        MemoryCognitiveDependencyRow.evidence_id == evidence_id,
                    )
                    .order_by(MemoryCognitiveDependencyRow.projection_id)
                )
            ).all()
        )
        projection_ids = tuple(row.projection_id for row in projection_rows)
        if not projection_ids:
            return ()
        scopes = {
            row.projection_id: CognitiveScope(
                space_id=row.space_id,
                memory_scope_id=row.memory_scope_id,
                thread_id=row.thread_id,
            )
            for row in projection_rows
        }
        dependency_rows = tuple(
            (
                await self._session.execute(
                    select(MemoryCognitiveDependencyRow)
                    .where(MemoryCognitiveDependencyRow.projection_id.in_(projection_ids))
                    .order_by(
                        MemoryCognitiveDependencyRow.projection_id,
                        MemoryCognitiveDependencyRow.id,
                    )
                )
            ).scalars()
        )
        grouped: dict[str, list[CanonicalEvidenceIdentity]] = {}
        for row in dependency_rows:
            grouped.setdefault(row.projection_id, []).append(
                CanonicalEvidenceIdentity(
                    evidence_type=row.evidence_type,
                    evidence_id=row.evidence_id,
                    version=row.evidence_version,
                    scope=scopes[row.projection_id],
                )
            )
        return tuple(
            CognitiveProjectionDependencySet(
                candidate_id=CognitiveCandidateIdentity(projection_id),
                scope=scopes[projection_id],
                evidence_identities=tuple(grouped[projection_id]),
            )
            for projection_id in projection_ids
        )

    async def invalidate(self, invalidation: CognitiveProjectionInvalidation) -> bool:
        result = await self._session.execute(
            update(MemoryCognitiveProjectionRow)
            .where(
                MemoryCognitiveProjectionRow.id == invalidation.candidate_id.value,
                MemoryCognitiveProjectionRow.state == "active",
            )
            .values(
                state="invalidated",
                invalidated_at=invalidation.invalidated_at,
                invalidation_reason=invalidation.reason_code,
                invalidation_event_id=invalidation.source_event_id,
                updated_at=invalidation.invalidated_at,
            )
        )
        return result.rowcount == 1


def create_postgres_cognitive_projection_store(
    session: AsyncSession,
) -> PostgresCognitiveProjectionStore:
    return PostgresCognitiveProjectionStore(session)


__all__ = (
    "PostgresCognitiveProjectionStore",
    "create_postgres_cognitive_projection_store",
)
