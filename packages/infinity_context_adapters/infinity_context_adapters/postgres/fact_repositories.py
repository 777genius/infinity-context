"""Postgres repositories for facts and fact relations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from infinity_context_core.domain.entities import MemoryFact, MemoryFactRelation, SourceRef
from infinity_context_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactFreshness,
    FactTemporalExtent,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactIdentity as CanonicalMemoryFactIdentity,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactScope as CanonicalMemoryFactScope,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactSnapshot as CanonicalMemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactSourceRef as CanonicalMemoryFactSourceRef,
)
from infinity_context_core.features.memory_facts.public import (
    MemoryFactVisibility as CanonicalMemoryFactVisibility,
)
from infinity_context_core.ports.repositories import (
    ActiveFactBatchRepositoryPort,
    ActiveFactSearch,
    FactRelationRepositoryPort,
    FactRepositoryPort,
)
from sqlalchemy import and_, delete, func, or_, select, tuple_, union, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from infinity_context_adapters.postgres.fact_selection_conditions import (
    memory_fact_code_scope_conditions,
    memory_fact_selection_conditions,
)
from infinity_context_adapters.postgres.mappers import (
    fact_relation_row_to_domain,
    fact_relation_to_row,
    fact_row_to_domain,
    source_ref_to_json,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemorySourceRefRow,
)
from infinity_context_adapters.postgres.repository_helpers import (
    _not_expired,
    _retrieval_candidate_limit,
    _score,
    _source_ref_points_to_deleted_document,
    _tags_match,
    _terms,
)

_MAX_FACT_HYDRATION_BINDS = 400


class PostgresFactRepository(FactRepositoryPort, ActiveFactBatchRepositoryPort):
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now

    async def create(self, fact: MemoryFact) -> MemoryFact:
        row = MemoryFactRow(
            id=str(fact.id),
            space_id=str(fact.space_id),
            memory_scope_id=str(fact.memory_scope_id),
            thread_id=str(fact.thread_id) if fact.thread_id else None,
            kind=fact.kind.value,
            text=fact.text,
            status=fact.status.value,
            confidence=fact.confidence.value,
            trust_level=fact.trust_level.value,
            classification=fact.classification,
            category=fact.category,
            tags_json=list(fact.tags),
            ttl_policy=fact.ttl_policy,
            expires_at=fact.expires_at,
            temporal_kind="state",
            observed_at=fact.created_at,
            valid_from=fact.created_at,
            temporal_basis="migrated_legacy",
            temporal_precision="unknown",
            epistemic_mode="world_claim",
            repository_id=fact.repository_id,
            code_scope_id=fact.code_scope_id,
            version=fact.version,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
        )
        self._session.add(row)
        await self._write_version(fact)
        await self._replace_source_refs(fact)
        return fact

    async def get_by_id(self, fact_id: str) -> MemoryFact | None:
        row = await self._session.get(MemoryFactRow, fact_id)
        if row is None:
            return None
        refs = await self._load_source_refs(fact_id=fact_id, version=row.version)
        return fact_row_to_domain(row, refs)

    async def get_by_ids(self, fact_ids: tuple[str, ...]) -> list[MemoryFact]:
        unique_ids = tuple(dict.fromkeys(fact_id for fact_id in fact_ids if fact_id.strip()))
        if not unique_ids:
            return []
        rows = list(
            (
                await self._session.execute(
                    select(MemoryFactRow).where(MemoryFactRow.id.in_(unique_ids))
                )
            ).scalars()
        )
        if not rows:
            return []
        rows_by_id = {row.id: row for row in rows}
        ref_rows = list(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(MemorySourceRefRow.fact_id.in_(tuple(rows_by_id)))
                    .order_by(
                        MemorySourceRefRow.fact_id,
                        MemorySourceRefRow.fact_version,
                        MemorySourceRefRow.id,
                    )
                )
            ).scalars()
        )
        refs_by_fact_version: dict[tuple[str, int], list[MemorySourceRefRow]] = {}
        for ref in ref_rows:
            refs_by_fact_version.setdefault((ref.fact_id, ref.fact_version), []).append(ref)
        return [
            fact_row_to_domain(
                row,
                refs_by_fact_version.get((row.id, row.version), []),
            )
            for fact_id in unique_ids
            if (row := rows_by_id.get(fact_id)) is not None
        ]

    async def get_for_update(self, fact_id: str) -> MemoryFact | None:
        statement = select(MemoryFactRow).where(MemoryFactRow.id == fact_id).with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        refs = await self._load_source_refs(fact_id=fact_id, version=row.version)
        return fact_row_to_domain(row, refs)

    async def save(self, fact: MemoryFact) -> MemoryFact:
        expected_version = fact.version - 1
        if expected_version < 1:
            raise MemoryConflictError("Stale fact version")
        result = await self._session.execute(
            update(MemoryFactRow)
            .where(
                MemoryFactRow.id == str(fact.id),
                MemoryFactRow.version == expected_version,
            )
            .values(
                space_id=str(fact.space_id),
                memory_scope_id=str(fact.memory_scope_id),
                thread_id=str(fact.thread_id) if fact.thread_id else None,
                kind=fact.kind.value,
                text=fact.text,
                status=fact.status.value,
                confidence=fact.confidence.value,
                trust_level=fact.trust_level.value,
                classification=fact.classification,
                category=fact.category,
                tags_json=list(fact.tags),
                ttl_policy=fact.ttl_policy,
                expires_at=fact.expires_at,
                repository_id=fact.repository_id,
                code_scope_id=fact.code_scope_id,
                version=fact.version,
                created_at=fact.created_at,
                updated_at=fact.updated_at,
            )
        )
        if result.rowcount == 0:
            exists = await self._session.get(MemoryFactRow, str(fact.id))
            if exists is None:
                msg = "Fact row missing during save"
                raise RuntimeError(msg)
            if (
                exists.version == fact.version
                and exists.status == fact.status.value
                and exists.status == "deleted"
            ):
                return fact
            raise MemoryConflictError("Stale fact version")
        row = await self._session.get(MemoryFactRow, str(fact.id))
        if row is not None:
            self._session.expire(row)
        else:
            msg = "Fact row missing during save"
            raise RuntimeError(msg)
        await self._write_version(fact)
        await self._replace_source_refs(fact)
        return fact

    async def list_versions(self, fact_id: str) -> list[MemoryFact]:
        rows = (
            await self._session.execute(
                select(MemoryFactVersionRow)
                .where(MemoryFactVersionRow.fact_id == fact_id)
                .order_by(MemoryFactVersionRow.version)
            )
        ).scalars()
        current = await self.get_by_id(fact_id)
        if current is None:
            return []
        versions: list[MemoryFact] = []
        for version_row in rows:
            version_fact = MemoryFact(
                id=current.id,
                space_id=current.space_id,
                memory_scope_id=current.memory_scope_id,
                thread_id=current.thread_id,
                text=version_row.text,
                kind=current.kind,
                source_refs=tuple(
                    SourceRef(
                        source_type=str(ref["source_type"]),
                        source_id=str(ref["source_id"]),
                        chunk_id=str(ref["chunk_id"]) if ref.get("chunk_id") else None,
                        char_start=(
                            int(ref["char_start"]) if ref.get("char_start") is not None else None
                        ),
                        char_end=int(ref["char_end"]) if ref.get("char_end") is not None else None,
                        quote_preview=str(ref["quote_preview"])
                        if ref.get("quote_preview") is not None
                        else None,
                    )
                    for ref in version_row.source_refs_json
                ),
                status=current.status.__class__(version_row.status),
                version=version_row.version,
                confidence=current.confidence,
                trust_level=current.trust_level,
                classification=current.classification,
                category=current.category,
                tags=current.tags,
                ttl_policy=current.ttl_policy,
                expires_at=current.expires_at,
                repository_id=current.repository_id,
                code_scope_id=current.code_scope_id,
                created_at=current.created_at,
                updated_at=version_row.created_at,
            )
            versions.append(version_fact)
        return versions

    async def find_active(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
        reference_time: datetime | None = None,
        temporal_mode: str = "current",
        repository_id: str | None = None,
        code_scope_id: str | None = None,
        category: str | None = None,
        tags_any: tuple[str, ...] = (),
        tags_all: tuple[str, ...] = (),
        tags_none: tuple[str, ...] = (),
    ) -> list[MemoryFact]:
        (facts,) = await self.find_active_many(
            (
                ActiveFactSearch(
                    space_id=space_id,
                    memory_scope_ids=memory_scope_ids,
                    thread_id=thread_id,
                    query=query,
                    limit=limit,
                    reference_time=reference_time,
                    temporal_mode=temporal_mode,
                    repository_id=repository_id,
                    code_scope_id=code_scope_id,
                    category=category,
                    tags_any=tags_any,
                    tags_all=tags_all,
                    tags_none=tags_none,
                ),
            )
        )
        return facts

    async def find_active_many(
        self,
        searches: tuple[ActiveFactSearch, ...],
    ) -> list[list[MemoryFact]]:
        if not searches:
            return []
        grouped: dict[tuple[object, ...], list[tuple[int, ActiveFactSearch]]] = {}
        for index, search in enumerate(searches):
            grouped.setdefault(_active_fact_search_group_key(search), []).append((index, search))
        results: list[list[MemoryFact]] = [[] for _ in searches]
        for indexed_searches in grouped.values():
            max_candidate_limit = max(
                (_retrieval_candidate_limit(search.limit) for _, search in indexed_searches),
                default=0,
            )
            if max_candidate_limit <= 0:
                continue
            first = indexed_searches[0][1]
            rows = list(
                (
                    await self._session.execute(
                        select(MemoryFactRow)
                        .where(*_active_fact_conditions(first, now=self._now))
                        .order_by(MemoryFactRow.updated_at.desc())
                        .limit(max_candidate_limit)
                    )
                ).scalars()
            )
            selected_ids: dict[int, tuple[str, ...]] = {}
            hydration_ids: list[str] = []
            for index, search in indexed_searches:
                candidate_rows = rows[: _retrieval_candidate_limit(search.limit)]
                if search.tags_any or search.tags_all or search.tags_none:
                    candidate_rows = [
                        row
                        for row in candidate_rows
                        if _tags_match(
                            row.tags_json or [],
                            tags_any=search.tags_any,
                            tags_all=search.tags_all,
                            tags_none=search.tags_none,
                        )
                    ]
                ids = tuple(
                    row.id
                    for row in _rank_active_fact_rows(
                        candidate_rows,
                        query=search.query,
                        limit=search.limit,
                    )
                )
                selected_ids[index] = ids
                hydration_ids.extend(ids)
            facts_by_id = await _hydrate_fact_rows_by_ids(
                self._session,
                tuple(dict.fromkeys(hydration_ids)),
            )
            for index, search in indexed_searches:
                results[index] = [
                    fact
                    for fact_id in selected_ids[index]
                    if (fact := facts_by_id.get(fact_id)) is not None
                    and _active_fact_matches_search(fact, search, now=self._now)
                ]
        return results

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_updated_at: datetime | None = None,
        cursor_id: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        enforce_code_scope: bool = False,
        repository_id: str | None = None,
        code_scope_id: str | None = None,
    ) -> list[MemoryFact]:
        conditions = [
            MemoryFactRow.space_id == space_id,
            MemoryFactRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemoryFactRow.status == status)
            if status == "active":
                conditions.append(_not_expired(MemoryFactRow, self._now))
        if category:
            conditions.append(MemoryFactRow.category == category)
        if enforce_code_scope:
            conditions.extend(
                memory_fact_code_scope_conditions(
                    MemoryFactRow,
                    repository_id=repository_id,
                    code_scope_id=code_scope_id,
                )
            )
        if thread_id is not None:
            conditions.append(
                or_(MemoryFactRow.thread_id == thread_id, MemoryFactRow.thread_id.is_(None))
            )
        if cursor_updated_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryFactRow.updated_at < cursor_updated_at,
                    (MemoryFactRow.updated_at == cursor_updated_at)
                    & (MemoryFactRow.id < cursor_id),
                )
            )
        rows = list(
            (
                await self._session.execute(
                    select(MemoryFactRow)
                    .where(*conditions)
                    .order_by(MemoryFactRow.updated_at.desc(), MemoryFactRow.id.desc())
                    .limit(_retrieval_candidate_limit(limit) if tag else limit)
                )
            ).scalars()
        )
        facts = []
        for row in rows:
            refs = await self._load_source_refs(fact_id=row.id, version=row.version)
            fact = fact_row_to_domain(row, refs)
            if tag and tag not in fact.tags:
                continue
            facts.append(fact)
        return facts

    async def delete_facts_sourced_only_by_chunks(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        document_id: str,
        chunk_ids: tuple[str, ...],
        now: datetime,
    ) -> tuple[tuple[str, int], ...]:
        if not chunk_ids and not document_id:
            return ()
        chunk_id_set = set(chunk_ids)
        candidate_ids = tuple(
            (
                await self._session.execute(
                    select(MemoryFactRow.id)
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
                            MemorySourceRefRow.chunk_id.in_(chunk_id_set),
                            (
                                (MemorySourceRefRow.source_type == "document")
                                & (MemorySourceRefRow.source_id == document_id)
                            ),
                        ),
                    )
                    .distinct()
                    .order_by(MemoryFactRow.id)
                )
            ).scalars()
        )
        deleted: list[tuple[str, int]] = []
        for fact_id in candidate_ids:
            current = await self.get_for_update(fact_id)
            if (
                current is None
                or current.status.value != "active"
                or str(current.space_id) != space_id
                or str(current.memory_scope_id) != memory_scope_id
            ):
                continue
            refs = current.source_refs
            if refs and all(
                _source_ref_points_to_deleted_document(
                    ref,
                    document_id=document_id,
                    chunk_ids=chunk_id_set,
                )
                for ref in refs
            ):
                forgotten = current.forget(now=now)
                await self.save(forgotten)
                deleted.append((str(forgotten.id), forgotten.version))
        return tuple(deleted)

    async def _write_version(self, fact: MemoryFact) -> None:
        from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
            memory_fact_snapshot_to_json,
        )

        snapshot = await self._canonical_snapshot(fact)
        payload = memory_fact_snapshot_to_json(snapshot)
        existing = (
            await self._session.execute(
                select(MemoryFactVersionRow).where(
                    MemoryFactVersionRow.fact_id == str(fact.id),
                    MemoryFactVersionRow.version == fact.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.snapshot_json == payload:
                return
            raise MemoryConflictError("Fact versions are append-only")
        self._session.add(
            MemoryFactVersionRow(
                fact_id=str(fact.id),
                version=fact.version,
                text=fact.text,
                status=fact.status.value,
                source_refs_json=[source_ref_to_json(ref) for ref in fact.source_refs],
                snapshot_json=payload,
                reason=None,
                created_at=fact.updated_at,
            )
        )

    async def _canonical_snapshot(self, fact: MemoryFact) -> CanonicalMemoryFactSnapshot:
        row = await self._session.get(MemoryFactRow, str(fact.id))
        previous = await self._previous_canonical_snapshot(fact)
        temporal_extent = (
            FactTemporalExtent(
                kind=getattr(row, "temporal_kind", "state") or "state",
                observed_at=_aware_datetime(getattr(row, "observed_at", None) or fact.created_at),
                valid_from=_aware_datetime(getattr(row, "valid_from", None)),
                valid_to=_aware_datetime(getattr(row, "valid_to", None)),
                occurred_from=_aware_datetime(getattr(row, "occurred_from", None)),
                occurred_to=_aware_datetime(getattr(row, "occurred_to", None)),
                basis=getattr(row, "temporal_basis", "migrated_legacy") or "migrated_legacy",
                precision=getattr(row, "temporal_precision", "unknown") or "unknown",
            )
            if row is not None
            else FactTemporalExtent.ongoing_state(
                observed_at=_aware_datetime(fact.created_at),
                basis="migrated_legacy",
                precision="unknown",
            )
        )
        base = CanonicalMemoryFactSnapshot(
            identity=CanonicalMemoryFactIdentity(
                fact_id=str(fact.id),
                scope=CanonicalMemoryFactScope(
                    space_id=str(fact.space_id),
                    memory_scope_id=str(fact.memory_scope_id),
                    thread_id=str(fact.thread_id) if fact.thread_id else None,
                ),
            ),
            text=fact.text,
            source_refs=tuple(_canonical_source_ref(ref) for ref in fact.source_refs),
            visibility=CanonicalMemoryFactVisibility(
                status=fact.status.value,
                version=fact.version,
                confidence=fact.confidence.value,
                trust_level=fact.trust_level.value,
                classification=fact.classification,
                ttl_policy=fact.ttl_policy,
                expires_at=_aware_datetime(fact.expires_at),
            ),
            kind=fact.kind.value,
            category=fact.category,
            tags=tuple(fact.tags),
            created_at=_aware_datetime(fact.created_at),
            updated_at=_aware_datetime(fact.updated_at),
            temporal_extent=temporal_extent,
            freshness=FactFreshness(
                last_confirmed_at=_aware_datetime(getattr(row, "last_confirmed_at", None)),
                confirmation_basis=getattr(row, "confirmation_basis", None),
            ),
            epistemic_context=FactEpistemicContext(
                mode=getattr(row, "epistemic_mode", "world_claim") or "world_claim",
                asserted_by=getattr(row, "asserted_by", None),
                perspective_subject=getattr(row, "perspective_subject", None),
            ),
            purge_after=_aware_datetime(getattr(row, "purge_after", None)),
            code_scope=(
                FactCodeScopeReference(
                    repository_id=row.repository_id,
                    code_scope_id=row.code_scope_id,
                )
                if row is not None and row.repository_id is not None
                else (previous.code_scope if previous is not None else None)
            ),
            evidence_refs=previous.evidence_refs if previous is not None else (),
        )
        if previous is None:
            return base
        return replace(
            base,
            code_scope=previous.code_scope,
            epistemic_context=previous.epistemic_context,
            evidence_refs=previous.evidence_refs,
        )

    async def _previous_canonical_snapshot(
        self,
        fact: MemoryFact,
    ) -> CanonicalMemoryFactSnapshot | None:
        from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
            memory_fact_snapshot_from_json,
        )

        if fact.version <= 1:
            return None
        previous = (
            await self._session.execute(
                select(MemoryFactVersionRow).where(
                    MemoryFactVersionRow.fact_id == str(fact.id),
                    MemoryFactVersionRow.version == fact.version - 1,
                )
            )
        ).scalar_one_or_none()
        if previous is None or not previous.snapshot_json:
            return None
        return memory_fact_snapshot_from_json(previous.snapshot_json)

    async def _replace_source_refs(self, fact: MemoryFact) -> None:
        await self._session.execute(
            delete(MemorySourceRefRow).where(
                MemorySourceRefRow.fact_id == str(fact.id),
                MemorySourceRefRow.fact_version == fact.version,
            )
        )
        for ref in fact.source_refs:
            self._session.add(
                MemorySourceRefRow(
                    fact_id=str(fact.id),
                    fact_version=fact.version,
                    source_type=ref.source_type,
                    source_id=ref.source_id,
                    chunk_id=ref.chunk_id,
                    char_start=ref.char_start,
                    char_end=ref.char_end,
                    quote_preview=ref.quote_preview,
                    page_number=ref.page_number,
                    time_start_ms=ref.time_start_ms,
                    time_end_ms=ref.time_end_ms,
                    bbox_json=list(ref.bbox) if ref.bbox is not None else None,
                )
            )

    async def _load_source_refs(self, *, fact_id: str, version: int) -> list[MemorySourceRefRow]:
        return list(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(
                        MemorySourceRefRow.fact_id == fact_id,
                        MemorySourceRefRow.fact_version == version,
                    )
                    .order_by(MemorySourceRefRow.id)
                )
            ).scalars()
        )


def _canonical_source_ref(ref: SourceRef) -> CanonicalMemoryFactSourceRef:
    return CanonicalMemoryFactSourceRef(
        source_type=ref.source_type,
        source_id=ref.source_id,
        chunk_id=ref.chunk_id,
        char_start=ref.char_start,
        char_end=ref.char_end,
        quote_preview=ref.quote_preview,
        page_number=ref.page_number,
        time_start_ms=ref.time_start_ms,
        time_end_ms=ref.time_end_ms,
        bbox=ref.bbox,
    )


def _aware_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _active_fact_conditions(
    search: ActiveFactSearch,
    *,
    now: datetime | None,
) -> tuple[object, ...]:
    reference_time = search.reference_time or now or datetime.now(UTC)
    conditions = list(
        memory_fact_selection_conditions(
            space_id=search.space_id,
            memory_scope_ids=search.memory_scope_ids,
            thread_id=search.thread_id,
            repository_id=search.repository_id,
            code_scope_id=search.code_scope_id,
            temporal_mode=search.temporal_mode,
            reference_time=reference_time,
        )
    )
    conditions.append(MemoryFactRow.classification != "restricted")
    if search.category:
        conditions.append(MemoryFactRow.category == search.category)
    return tuple(conditions)


def _active_fact_search_group_key(search: ActiveFactSearch) -> tuple[object, ...]:
    return (
        search.space_id,
        search.memory_scope_ids,
        search.thread_id,
        search.repository_id,
        search.code_scope_id,
        search.reference_time,
        search.temporal_mode,
        search.category,
        search.tags_any,
        search.tags_all,
        search.tags_none,
    )


def _rank_active_fact_rows(
    rows: list[MemoryFactRow],
    *,
    query: str,
    limit: int,
) -> list[MemoryFactRow]:
    if limit <= 0:
        return []
    terms = _terms(query)
    if not terms:
        return rows[:limit]
    scored_rows = [
        (score, index, row)
        for index, row in enumerate(rows)
        for score in (_score(row.text, terms),)
        if score > 0
    ]
    scored_rows.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored_rows[:limit]]


async def _hydrate_fact_rows_by_ids(
    session: AsyncSession,
    fact_ids: tuple[str, ...],
) -> dict[str, MemoryFact]:
    rows_by_id: dict[str, MemoryFactRow] = {}
    refs_by_fact_version: dict[tuple[str, int], list[MemorySourceRefRow]] = {}
    for fact_id_batch in _batches(fact_ids, _MAX_FACT_HYDRATION_BINDS):
        rows = list(
            (
                await session.execute(
                    select(MemoryFactRow)
                    .where(MemoryFactRow.id.in_(fact_id_batch))
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        rows_by_id.update((row.id, row) for row in rows)
        if not rows:
            continue
        refs = list(
            (
                await session.execute(
                    select(MemorySourceRefRow)
                    .where(
                        tuple_(
                            MemorySourceRefRow.fact_id,
                            MemorySourceRefRow.fact_version,
                        ).in_(tuple((row.id, row.version) for row in rows))
                    )
                    .order_by(
                        MemorySourceRefRow.fact_id,
                        MemorySourceRefRow.fact_version,
                        MemorySourceRefRow.id,
                    )
                )
            ).scalars()
        )
        for ref in refs:
            refs_by_fact_version.setdefault((ref.fact_id, ref.fact_version), []).append(ref)
    return {
        fact_id: fact_row_to_domain(
            row,
            refs_by_fact_version.get((row.id, row.version), []),
        )
        for fact_id in fact_ids
        if (row := rows_by_id.get(fact_id)) is not None
    }


def _active_fact_matches_search(
    fact: MemoryFact,
    search: ActiveFactSearch,
    *,
    now: datetime | None,
) -> bool:
    comparable_now = search.reference_time or now or datetime.now(UTC)
    expires_at = fact.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None and comparable_now.tzinfo is not None:
            comparable_now = comparable_now.replace(tzinfo=None)
        if expires_at <= comparable_now:
            return False
    return (
        str(fact.space_id) == search.space_id
        and str(fact.memory_scope_id) in search.memory_scope_ids
        and (
            fact.status.value == "active"
            or (search.temporal_mode == "as_of" and fact.status.value == "superseded")
        )
        and fact.classification != "restricted"
        and (not search.category or fact.category == search.category)
        and (
            search.thread_id is None
            or fact.thread_id is None
            or str(fact.thread_id) == search.thread_id
        )
        and _tags_match(
            list(fact.tags),
            tags_any=search.tags_any,
            tags_all=search.tags_all,
            tags_none=search.tags_none,
        )
    )


def _batches(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(values[offset : offset + size] for offset in range(0, len(values), size))


class PostgresFactRelationRepository(FactRelationRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, relation: MemoryFactRelation) -> MemoryFactRelation:
        self._session.add(fact_relation_to_row(relation))
        return relation

    async def get_by_id(self, relation_id: str) -> MemoryFactRelation | None:
        row = await self._session.get(MemoryFactRelationRow, relation_id)
        return fact_relation_row_to_domain(row) if row else None

    async def save(self, relation: MemoryFactRelation) -> MemoryFactRelation:
        row = await self._session.get(MemoryFactRelationRow, str(relation.id))
        if row is None:
            raise MemoryNotFoundError("Fact relation not found")
        row.status = relation.status.value
        row.reason = relation.reason
        row.observed_at = relation.observed_at
        row.valid_from = relation.valid_from
        row.valid_to = relation.valid_to
        row.updated_at = relation.updated_at
        return relation

    async def find_active(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: str,
    ) -> MemoryFactRelation | None:
        row = (
            await self._session.execute(
                select(MemoryFactRelationRow).where(
                    MemoryFactRelationRow.source_fact_id == source_fact_id,
                    MemoryFactRelationRow.target_fact_id == target_fact_id,
                    MemoryFactRelationRow.relation_type == relation_type,
                    MemoryFactRelationRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        return fact_relation_row_to_domain(row) if row else None

    async def list_for_fact(
        self,
        *,
        fact_id: str,
        status: str | None,
        limit: int,
        enforce_code_scope: bool = False,
        repository_id: str | None = None,
        code_scope_id: str | None = None,
    ) -> list[MemoryFactRelation]:
        conditions = [
            or_(
                MemoryFactRelationRow.source_fact_id == fact_id,
                MemoryFactRelationRow.target_fact_id == fact_id,
            )
        ]
        if status is not None:
            conditions.append(MemoryFactRelationRow.status == status)
        statement = select(MemoryFactRelationRow)
        if enforce_code_scope:
            related_fact_row = aliased(MemoryFactRow)
            statement = statement.join(
                related_fact_row,
                or_(
                    and_(
                        MemoryFactRelationRow.source_fact_id == fact_id,
                        related_fact_row.id == MemoryFactRelationRow.target_fact_id,
                    ),
                    and_(
                        MemoryFactRelationRow.target_fact_id == fact_id,
                        related_fact_row.id == MemoryFactRelationRow.source_fact_id,
                    ),
                ),
            )
            conditions.extend(
                memory_fact_code_scope_conditions(
                    related_fact_row,
                    repository_id=repository_id,
                    code_scope_id=code_scope_id,
                )
            )
            conditions.append(related_fact_row.classification != "restricted")
        rows = (
            await self._session.execute(
                statement.where(*conditions)
                .order_by(MemoryFactRelationRow.updated_at.desc(), MemoryFactRelationRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [fact_relation_row_to_domain(row) for row in rows]

    async def list_for_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        status: str | None,
        limit_per_fact: int,
    ) -> dict[str, list[MemoryFactRelation]]:
        unique_fact_ids = tuple(dict.fromkeys(str(fact_id) for fact_id in fact_ids if fact_id))
        if not unique_fact_ids:
            return {}
        safe_limit_per_fact = max(0, int(limit_per_fact))
        if safe_limit_per_fact <= 0:
            return {fact_id: [] for fact_id in unique_fact_ids}
        source_conditions = [MemoryFactRelationRow.source_fact_id.in_(unique_fact_ids)]
        target_conditions = [MemoryFactRelationRow.target_fact_id.in_(unique_fact_ids)]
        if status is not None:
            source_conditions.append(MemoryFactRelationRow.status == status)
            target_conditions.append(MemoryFactRelationRow.status == status)
        relation_matches = union(
            select(
                MemoryFactRelationRow.source_fact_id.label("fact_id"),
                MemoryFactRelationRow.id.label("relation_id"),
                MemoryFactRelationRow.updated_at.label("updated_at"),
            ).where(*source_conditions),
            select(
                MemoryFactRelationRow.target_fact_id.label("fact_id"),
                MemoryFactRelationRow.id.label("relation_id"),
                MemoryFactRelationRow.updated_at.label("updated_at"),
            ).where(*target_conditions),
        ).subquery()
        ranked_matches = select(
            relation_matches.c.fact_id,
            relation_matches.c.relation_id,
            func.row_number()
            .over(
                partition_by=relation_matches.c.fact_id,
                order_by=(
                    relation_matches.c.updated_at.desc(),
                    relation_matches.c.relation_id.desc(),
                ),
            )
            .label("relation_rank"),
        ).subquery()
        rows = (
            await self._session.execute(
                select(ranked_matches.c.fact_id, MemoryFactRelationRow)
                .join(
                    MemoryFactRelationRow,
                    MemoryFactRelationRow.id == ranked_matches.c.relation_id,
                )
                .where(ranked_matches.c.relation_rank <= safe_limit_per_fact)
                .order_by(ranked_matches.c.fact_id, ranked_matches.c.relation_rank)
            )
        ).all()
        relations_by_fact_id: dict[str, list[MemoryFactRelation]] = {
            fact_id: [] for fact_id in unique_fact_ids
        }
        for fact_id, row in rows:
            relation = fact_relation_row_to_domain(row)
            relations_by_fact_id[str(fact_id)].append(relation)
        return relations_by_fact_id
