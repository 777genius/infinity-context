"""Canonical Postgres adapters for locator-only Retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from infinity_context_core.features.context_building.public import (
    CanonicalHydrationInvariantError,
    CanonicalLocatorCandidate,
    CanonicalLocatorRead,
    LocatorProviderHit,
    LocatorProviderResult,
    LocatorRetrievalRequest,
)
from sqlalchemy import case, func, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.postgres.models import MemoryChunkRow


@dataclass(frozen=True, slots=True)
class PostgresLocatorCandidateProvider:
    """Feature-owned lexical lane; it exposes identity/rank evidence only."""

    sessions: async_sessionmaker[AsyncSession]
    provider_id: str = "postgres_keyword"

    async def retrieve_locator_candidates(
        self, request: LocatorRetrievalRequest
    ) -> LocatorProviderResult:
        hits: list[LocatorProviderHit] = []
        async with self.sessions() as session:
            for variant in request.queries:
                rows = (
                    await session.execute(
                        _candidate_statement(request, variant.query).limit(
                            request.bounds.candidate_limit
                        )
                    )
                ).all()
                hits.extend(
                    LocatorProviderHit(
                        canonical_identity=row.id,
                        canonical_version=row.retrieval_version,
                        provider_id=self.provider_id,
                        query_id=variant.query_id,
                        provider_rank=rank,
                        raw_score_kind="relevance",
                        raw_score_value=float(row.relevance),
                    )
                    for rank, row in enumerate(rows, start=1)
                )
        return LocatorProviderResult(status="available", hits=tuple(hits))


@dataclass(frozen=True, slots=True)
class PostgresCanonicalLocatorReader:
    """Canonical lifecycle authority with an exact final read snapshot."""

    sessions: async_sessionmaker[AsyncSession]

    async def hydrate_locator_candidates(
        self,
        request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
    ) -> tuple[CanonicalLocatorCandidate, ...]:
        if len(set(canonical_identities)) != len(canonical_identities):
            raise CanonicalHydrationInvariantError(
                "preliminary hydration received duplicate canonical identities"
            )
        async with self.sessions() as session, session.begin():
            await _set_repeatable_read(session)
            snapshot = await _snapshot_token(session)
            rows = await _load_rows(session, request, canonical_identities)
            return _canonical_rows(rows, snapshot)

    async def hydrate_final_locator_read(
        self,
        request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
        radius: int,
    ) -> CanonicalLocatorRead:
        if len(set(canonical_identities)) != len(canonical_identities):
            raise CanonicalHydrationInvariantError(
                "final hydration received duplicate canonical identities"
            )
        async with self.sessions() as session, session.begin():
            await _set_repeatable_read(session)
            snapshot = await _snapshot_token(session)
            seeds = await _load_rows(session, request, canonical_identities)
            neighbors = await _load_neighbor_rows(session, request, seeds, radius)
            return CanonicalLocatorRead(
                seeds=_canonical_rows(seeds, snapshot),
                neighbors=_canonical_rows(neighbors, snapshot),
            )


def _candidate_statement(request: LocatorRetrievalRequest, query: str):
    terms = tuple(dict.fromkeys(term.casefold() for term in query.split() if term))
    matches = tuple(
        func.lower(MemoryChunkRow.normalized_text).contains(term, autoescape=True) for term in terms
    )
    relevance = sum((case((match, 1), else_=0) for match in matches), start=0)
    conditions = list(_hard_sql_conditions(request))
    if matches:
        conditions.append(or_(*matches))
    return (
        select(
            MemoryChunkRow.id.label("id"),
            MemoryChunkRow.retrieval_version.label("retrieval_version"),
            relevance.label("relevance"),
        )
        .where(*conditions)
        .order_by(
            relevance.desc(),
            MemoryChunkRow.retrieval_sequence_ordinal,
            MemoryChunkRow.id,
        )
    )


def _hard_sql_conditions(request: LocatorRetrievalRequest) -> tuple[object, ...]:
    scope = request.scope
    filters = request.hard_filters
    conditions: list[object] = [
        MemoryChunkRow.space_id == scope.space_id,
        MemoryChunkRow.memory_scope_id == scope.memory_scope_id,
        MemoryChunkRow.status == "active",
        MemoryChunkRow.classification.in_(("public", "internal")),
        MemoryChunkRow.document_id.is_not(None),
        MemoryChunkRow.retrieval_locator.is_not(None),
        MemoryChunkRow.retrieval_source_key.is_not(None),
        MemoryChunkRow.retrieval_projection_generation.is_not(None),
        MemoryChunkRow.retrieval_sequence_ordinal.is_not(None),
        MemoryChunkRow.retrieval_kind.is_not(None),
        MemoryChunkRow.retrieval_category.is_not(None),
    ]
    conditions.append(
        MemoryChunkRow.thread_id.is_(None)
        if scope.thread_id is None
        else MemoryChunkRow.thread_id == scope.thread_id
    )
    conditions.append(
        or_(
            *(
                (MemoryChunkRow.retrieval_source_key == pair.source_key)
                & (MemoryChunkRow.retrieval_projection_generation == pair.projection_generation)
                for pair in filters.source_generations
            )
        )
    )
    if filters.excluded_source_keys:
        conditions.append(
            not_(MemoryChunkRow.retrieval_source_key.in_(filters.excluded_source_keys))
        )
    if filters.document_keys:
        conditions.append(MemoryChunkRow.document_id.in_(filters.document_keys))
    if filters.kinds:
        conditions.append(MemoryChunkRow.retrieval_kind.in_(filters.kinds))
    if filters.category is not None:
        conditions.append(MemoryChunkRow.retrieval_category == filters.category)
    if filters.tags_any:
        conditions.append(
            or_(*(MemoryChunkRow.retrieval_tags_json.contains([tag]) for tag in filters.tags_any))
        )
    for tag in filters.tags_all:
        conditions.append(MemoryChunkRow.retrieval_tags_json.contains([tag]))
    for tag in filters.tags_none:
        conditions.append(not_(MemoryChunkRow.retrieval_tags_json.contains([tag])))
    if filters.actor_keys:
        conditions.append(
            or_(
                *(
                    MemoryChunkRow.retrieval_actor_keys_json.contains([actor])
                    for actor in filters.actor_keys
                )
            )
        )
    if filters.time_interval is not None:
        conditions.extend(
            (
                MemoryChunkRow.retrieval_start_at.is_not(None),
                MemoryChunkRow.retrieval_end_at.is_not(None),
                MemoryChunkRow.retrieval_start_at <= filters.time_interval.end_at,
                MemoryChunkRow.retrieval_end_at >= filters.time_interval.start_at,
            )
        )
    if filters.relative_time_interval is not None:
        conditions.extend(
            (
                MemoryChunkRow.retrieval_relative_start_ms.is_not(None),
                MemoryChunkRow.retrieval_relative_end_ms.is_not(None),
                MemoryChunkRow.retrieval_relative_start_ms <= filters.relative_time_interval.end_ms,
                MemoryChunkRow.retrieval_relative_end_ms >= filters.relative_time_interval.start_ms,
            )
        )
    return tuple(conditions)


async def _load_rows(
    session: AsyncSession,
    request: LocatorRetrievalRequest,
    identities: tuple[str, ...],
) -> tuple[MemoryChunkRow, ...]:
    if not identities:
        return ()
    rows = tuple(
        (
            await session.execute(
                select(MemoryChunkRow)
                .where(
                    MemoryChunkRow.id.in_(identities),
                    *_hard_sql_conditions(request),
                )
                .order_by(MemoryChunkRow.id)
            )
        ).scalars()
    )
    if len({row.id for row in rows}) != len(rows):
        raise CanonicalHydrationInvariantError(
            "canonical locator query returned duplicate identities"
        )
    return rows


async def _load_neighbor_rows(
    session: AsyncSession,
    request: LocatorRetrievalRequest,
    seeds: tuple[MemoryChunkRow, ...],
    radius: int,
) -> tuple[MemoryChunkRow, ...]:
    if radius <= 0 or not seeds:
        return ()
    clauses = []
    seed_ids = {row.id for row in seeds}
    for seed in seeds:
        if seed.retrieval_sequence_ordinal is None:
            continue
        clauses.append(
            (MemoryChunkRow.space_id == seed.space_id)
            & (MemoryChunkRow.memory_scope_id == seed.memory_scope_id)
            & (
                MemoryChunkRow.thread_id.is_(None)
                if seed.thread_id is None
                else MemoryChunkRow.thread_id == seed.thread_id
            )
            & (MemoryChunkRow.retrieval_source_key == seed.retrieval_source_key)
            & (
                MemoryChunkRow.retrieval_projection_generation
                == seed.retrieval_projection_generation
            )
            & MemoryChunkRow.retrieval_sequence_ordinal.between(
                seed.retrieval_sequence_ordinal - radius,
                seed.retrieval_sequence_ordinal + radius,
            )
        )
    if not clauses:
        return ()
    return tuple(
        row
        for row in (
            await session.execute(
                select(MemoryChunkRow)
                .where(
                    *_hard_sql_conditions(request),
                    or_(*clauses),
                )
                .order_by(
                    MemoryChunkRow.retrieval_source_key,
                    MemoryChunkRow.retrieval_projection_generation,
                    MemoryChunkRow.retrieval_sequence_ordinal,
                    MemoryChunkRow.id,
                )
            )
        ).scalars()
        if row.id not in seed_ids
    )


async def _snapshot_token(session: AsyncSession) -> str:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        value = (await session.execute(text("SELECT pg_current_snapshot()::text"))).scalar_one()
        return f"postgres:{value}"
    return f"transaction:{uuid4().hex}"


async def _set_repeatable_read(session: AsyncSession) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))


def _canonical_rows(
    rows: tuple[MemoryChunkRow, ...], snapshot: str
) -> tuple[CanonicalLocatorCandidate, ...]:
    result: list[CanonicalLocatorCandidate] = []
    for row in rows:
        if not all(
            (
                row.retrieval_locator,
                row.retrieval_source_key,
                row.retrieval_projection_generation,
                row.document_id,
            )
        ):
            continue
        result.append(
            CanonicalLocatorCandidate(
                locator=row.retrieval_locator,
                canonical_identity=row.id,
                canonical_version=row.retrieval_version,
                lifecycle_status=_lifecycle_status(row),
                space_id=row.space_id,
                memory_scope_id=row.memory_scope_id,
                thread_id=row.thread_id,
                source_key=row.retrieval_source_key,
                document_key=row.document_id,
                chunk_key=row.id,
                projection_generation=row.retrieval_projection_generation,
                kind=row.retrieval_kind or "",
                category=row.retrieval_category or "uncategorized",
                tags=tuple(row.retrieval_tags_json or ()),
                actor_keys=tuple(row.retrieval_actor_keys_json or ()),
                start_at=row.retrieval_start_at,
                end_at=row.retrieval_end_at,
                relative_start_ms=row.retrieval_relative_start_ms,
                relative_end_ms=row.retrieval_relative_end_ms,
                sequence_ordinal=row.retrieval_sequence_ordinal,
                read_snapshot=snapshot,
            )
        )
    return tuple(result)


def _lifecycle_status(row: MemoryChunkRow) -> str:
    if row.classification not in {"public", "internal"}:
        return "restricted"
    if row.status == "active":
        return "active"
    if row.status == "deleted":
        return "deleted"
    return "restricted"


__all__ = ("PostgresCanonicalLocatorReader", "PostgresLocatorCandidateProvider")
