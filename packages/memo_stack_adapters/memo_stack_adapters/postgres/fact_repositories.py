"""Postgres repositories for facts and fact relations."""

from __future__ import annotations

from datetime import datetime

from memo_stack_core.domain.entities import MemoryFact, MemoryFactRelation, SourceRef
from memo_stack_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from memo_stack_core.ports.repositories import (
    FactRelationRepositoryPort,
    FactRepositoryPort,
)
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_adapters.postgres.mappers import (
    fact_relation_row_to_domain,
    fact_relation_to_row,
    fact_row_to_domain,
    source_ref_to_json,
)
from memo_stack_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemorySourceRefRow,
)
from memo_stack_adapters.postgres.repository_helpers import (
    _not_expired,
    _retrieval_candidate_limit,
    _score,
    _source_ref_points_to_deleted_document,
    _tags_match,
    _terms,
)


class PostgresFactRepository(FactRepositoryPort):
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
        category: str | None = None,
        tags_any: tuple[str, ...] = (),
        tags_all: tuple[str, ...] = (),
        tags_none: tuple[str, ...] = (),
    ) -> list[MemoryFact]:
        conditions = [
            MemoryFactRow.space_id == space_id,
            MemoryFactRow.memory_scope_id.in_(memory_scope_ids),
            MemoryFactRow.status == "active",
            MemoryFactRow.classification != "restricted",
            _not_expired(MemoryFactRow, self._now),
        ]
        if category:
            conditions.append(MemoryFactRow.category == category)
        if thread_id is not None:
            conditions.append(
                or_(MemoryFactRow.thread_id == thread_id, MemoryFactRow.thread_id.is_(None))
            )
        statement = (
            select(MemoryFactRow)
            .where(*conditions)
            .order_by(MemoryFactRow.updated_at.desc())
            .limit(_retrieval_candidate_limit(limit))
        )
        rows = list((await self._session.execute(statement)).scalars())
        if tags_any or tags_all or tags_none:
            rows = [
                row
                for row in rows
                if _tags_match(
                    row.tags_json or [],
                    tags_any=tags_any,
                    tags_all=tags_all,
                    tags_none=tags_none,
                )
            ]
        terms = _terms(query)
        if terms:
            rows = [row for row in rows if _score(row.text, terms) > 0]
            rows.sort(key=lambda row: _score(row.text, terms), reverse=True)
        facts = []
        for row in rows[:limit]:
            refs = await self._load_source_refs(fact_id=row.id, version=row.version)
            facts.append(fact_row_to_domain(row, refs))
        return facts

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
        candidate_rows = list(
            (
                await self._session.execute(
                    select(MemoryFactRow)
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
                )
            ).scalars()
        )
        deleted: list[tuple[str, int]] = []
        for row in candidate_rows:
            refs = await self._load_source_refs(fact_id=row.id, version=row.version)
            if refs and all(
                _source_ref_points_to_deleted_document(
                    ref,
                    document_id=document_id,
                    chunk_ids=chunk_id_set,
                )
                for ref in refs
            ):
                forgotten = fact_row_to_domain(row, refs).forget(now=now)
                await self.save(forgotten)
                deleted.append((str(forgotten.id), forgotten.version))
        return tuple(deleted)

    async def _write_version(self, fact: MemoryFact) -> None:
        existing = (
            await self._session.execute(
                select(MemoryFactVersionRow).where(
                    MemoryFactVersionRow.fact_id == str(fact.id),
                    MemoryFactVersionRow.version == fact.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.text = fact.text
            existing.status = fact.status.value
            existing.source_refs_json = [source_ref_to_json(ref) for ref in fact.source_refs]
            existing.created_at = fact.updated_at
            return
        self._session.add(
            MemoryFactVersionRow(
                fact_id=str(fact.id),
                version=fact.version,
                text=fact.text,
                status=fact.status.value,
                source_refs_json=[source_ref_to_json(ref) for ref in fact.source_refs],
                reason=None,
                created_at=fact.updated_at,
            )
        )

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
    ) -> list[MemoryFactRelation]:
        conditions = [
            or_(
                MemoryFactRelationRow.source_fact_id == fact_id,
                MemoryFactRelationRow.target_fact_id == fact_id,
            )
        ]
        if status is not None:
            conditions.append(MemoryFactRelationRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryFactRelationRow)
                .where(*conditions)
                .order_by(MemoryFactRelationRow.updated_at.desc(), MemoryFactRelationRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [fact_relation_row_to_domain(row) for row in rows]
