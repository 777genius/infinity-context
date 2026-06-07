"""Postgres repository implementations."""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256

from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.domain.entities import (
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
    MemoryProfile,
    MemorySpace,
    MemorySuggestion,
    SourceRef,
)
from memo_stack_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.captures import CaptureRepositoryPort
from memo_stack_core.ports.repositories import (
    ChunkRepositoryPort,
    DocumentRepositoryPort,
    EpisodeRepositoryPort,
    FactRelationRepositoryPort,
    FactRepositoryPort,
    IdempotencyRepositoryPort,
    ResolvedScope,
    ScopeRepositoryPort,
    SessionDeleteResult,
    SessionStatus,
    SuggestionRepositoryPort,
    UpsertChunkResult,
)
from memo_stack_core.ports.unit_of_work import OutboxPort
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_adapters.postgres.mappers import (
    apply_capture_to_row,
    apply_suggestion_to_row,
    capture_row_to_domain,
    capture_to_row,
    chunk_row_to_domain,
    chunk_to_row,
    document_row_to_domain,
    document_to_row,
    episode_to_row,
    fact_relation_row_to_domain,
    fact_relation_to_row,
    fact_row_to_domain,
    profile_row_to_domain,
    source_ref_to_json,
    space_row_to_domain,
    suggestion_row_to_domain,
    suggestion_to_row,
)
from memo_stack_adapters.postgres.models import (
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
    MemoryProfileRow,
    MemorySourceRefRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)


class PostgresScopeRepository(ScopeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_space(self, space: MemorySpace) -> MemorySpace:
        existing = (
            await self._session.execute(
                select(MemorySpaceRow).where(MemorySpaceRow.slug == space.slug)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return space_row_to_domain(existing)
        self._session.add(
            MemorySpaceRow(
                id=str(space.id),
                slug=space.slug,
                name=space.name,
                status=space.status.value,
                created_at=space.created_at,
                updated_at=space.updated_at,
            )
        )
        return space

    async def list_spaces(self, *, limit: int) -> list[MemorySpace]:
        rows = (
            await self._session.execute(
                select(MemorySpaceRow)
                .where(MemorySpaceRow.status == "active")
                .order_by(MemorySpaceRow.updated_at.desc(), MemorySpaceRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [space_row_to_domain(row) for row in rows]

    async def create_profile(self, profile: MemoryProfile) -> MemoryProfile:
        existing = (
            await self._session.execute(
                select(MemoryProfileRow).where(
                    MemoryProfileRow.space_id == str(profile.space_id),
                    MemoryProfileRow.external_ref == profile.external_ref,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return profile_row_to_domain(existing)
        space = await self._session.get(MemorySpaceRow, str(profile.space_id))
        if space is None or space.status != "active":
            raise MemoryNotFoundError("Space not found")
        self._session.add(
            MemoryProfileRow(
                id=str(profile.id),
                space_id=str(profile.space_id),
                external_ref=profile.external_ref,
                name=profile.name,
                status=profile.status.value,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
        )
        return profile

    async def list_profiles(self, *, space_id: str, limit: int) -> list[MemoryProfile]:
        rows = (
            await self._session.execute(
                select(MemoryProfileRow)
                .where(
                    MemoryProfileRow.space_id == space_id,
                    MemoryProfileRow.status == "active",
                )
                .order_by(MemoryProfileRow.updated_at.desc(), MemoryProfileRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [profile_row_to_domain(row) for row in rows]

    async def ensure_scope(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
        thread_external_ref: str | None,
        now: datetime,
    ) -> ResolvedScope:
        space_slug = space_slug.strip()
        profile_external_ref = profile_external_ref.strip()
        if not space_slug:
            space_slug = "default"
        if not profile_external_ref:
            profile_external_ref = "default"

        space = (
            await self._session.execute(
                select(MemorySpaceRow).where(MemorySpaceRow.slug == space_slug)
            )
        ).scalar_one_or_none()
        if space is None:
            await self._insert_ignore(
                MemorySpaceRow,
                values={
                    "id": _stable_id("space", space_slug),
                    "slug": space_slug,
                    "name": space_slug,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                },
                index_elements=(MemorySpaceRow.slug,),
            )
            space = (
                await self._session.execute(
                    select(MemorySpaceRow).where(MemorySpaceRow.slug == space_slug)
                )
            ).scalar_one()

        profile = (
            await self._session.execute(
                select(MemoryProfileRow).where(
                    MemoryProfileRow.space_id == space.id,
                    MemoryProfileRow.external_ref == profile_external_ref,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            await self._insert_ignore(
                MemoryProfileRow,
                values={
                    "id": _stable_id("profile", space.id, profile_external_ref),
                    "space_id": space.id,
                    "external_ref": profile_external_ref,
                    "name": profile_external_ref,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                },
                index_elements=(MemoryProfileRow.space_id, MemoryProfileRow.external_ref),
            )
            profile = (
                await self._session.execute(
                    select(MemoryProfileRow).where(
                        MemoryProfileRow.space_id == space.id,
                        MemoryProfileRow.external_ref == profile_external_ref,
                    )
                )
            ).scalar_one()

        thread_id = None
        if thread_external_ref:
            thread = (
                await self._session.execute(
                    select(MemoryThreadRow).where(
                        MemoryThreadRow.space_id == space.id,
                        MemoryThreadRow.profile_id == profile.id,
                        MemoryThreadRow.external_ref == thread_external_ref,
                    )
                )
            ).scalar_one_or_none()
            if thread is None:
                await self._insert_ignore(
                    MemoryThreadRow,
                    values={
                        "id": _stable_id("thread", space.id, profile.id, thread_external_ref),
                        "space_id": space.id,
                        "profile_id": profile.id,
                        "external_ref": thread_external_ref,
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    index_elements=(
                        MemoryThreadRow.space_id,
                        MemoryThreadRow.profile_id,
                        MemoryThreadRow.external_ref,
                    ),
                )
                thread = (
                    await self._session.execute(
                        select(MemoryThreadRow).where(
                            MemoryThreadRow.space_id == space.id,
                            MemoryThreadRow.profile_id == profile.id,
                            MemoryThreadRow.external_ref == thread_external_ref,
                        )
                    )
                ).scalar_one()
            elif thread.status == "deleted":
                thread.status = "active"
                thread.updated_at = now
            thread_id = thread.id

        return ResolvedScope(space_id=space.id, profile_id=profile.id, thread_id=thread_id)

    async def _insert_ignore(
        self,
        row_type: type,
        *,
        values: dict[str, object],
        index_elements: tuple[object, ...],
    ) -> None:
        dialect_name = self._session.get_bind().dialect.name
        table = row_type.__table__
        if dialect_name == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=index_elements)
            )
        elif dialect_name == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=index_elements)
            )
        else:
            self._session.add(row_type(**values))
            await self._session.flush()
            return
        await self._session.execute(statement)
        await self._session.flush()

    async def delete_thread_memory(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> SessionDeleteResult:
        chunk_ids = await self._soft_delete_ids(
            MemoryChunkRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        fact_ids = await self._soft_delete_ids(
            MemoryFactRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        episode_ids = await self._soft_delete_ids(
            MemoryEpisodeRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        document_ids = await self._soft_delete_ids(
            MemoryDocumentRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        jobs = await self._delete_outbox_for_aggregate_ids(
            (*chunk_ids, *fact_ids, *episode_ids, *document_ids)
        )
        return SessionDeleteResult(
            deleted_chunks=len(chunk_ids),
            deleted_facts=len(fact_ids),
            deleted_jobs=jobs,
            deleted_chunk_ids=chunk_ids,
            deleted_fact_ids=fact_ids,
        )

    async def thread_status(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> SessionStatus:
        chunks = await self._active_count(
            MemoryChunkRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        facts = await self._active_count(
            MemoryFactRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        aggregate_ids = await self._aggregate_ids_for_thread(
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
        )
        jobs = await self._outbox_count_for_aggregate_ids(aggregate_ids)
        pending = await self._outbox_count_for_aggregate_ids(
            aggregate_ids,
            statuses=("pending", "retry_pending"),
        )
        return SessionStatus(chunks=chunks, facts=facts, jobs=jobs, pending_jobs=pending)

    async def _soft_delete_ids(
        self,
        model: (
            type[MemoryChunkRow]
            | type[MemoryFactRow]
            | type[MemoryEpisodeRow]
            | type[MemoryDocumentRow]
        ),
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> tuple[str, ...]:
        ids = await self._ids_for_thread(
            model,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            active_only=True,
        )
        if not ids:
            return ()
        await self._session.execute(
            update(model)
            .where(
                model.id.in_(ids),
            )
            .values(status="deleted")
        )
        return ids

    async def _aggregate_ids_for_thread(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> tuple[str, ...]:
        chunks = await self._ids_for_thread(
            MemoryChunkRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            active_only=False,
        )
        facts = await self._ids_for_thread(
            MemoryFactRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            active_only=False,
        )
        episodes = await self._ids_for_thread(
            MemoryEpisodeRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            active_only=False,
        )
        documents = await self._ids_for_thread(
            MemoryDocumentRow,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            active_only=False,
        )
        return (*chunks, *facts, *episodes, *documents)

    async def _ids_for_thread(
        self,
        model: (
            type[MemoryChunkRow]
            | type[MemoryFactRow]
            | type[MemoryEpisodeRow]
            | type[MemoryDocumentRow]
        ),
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
        active_only: bool,
    ) -> tuple[str, ...]:
        conditions = [
            model.space_id == space_id,
            model.profile_id == profile_id,
            model.thread_id == thread_id,
        ]
        if active_only:
            conditions.append(model.status != "deleted")
        rows = (await self._session.execute(select(model.id).where(*conditions))).scalars()
        return tuple(str(row_id) for row_id in rows)

    async def _delete_outbox_for_aggregate_ids(self, aggregate_ids: tuple[str, ...]) -> int:
        if not aggregate_ids:
            return 0
        result = await self._session.execute(
            delete(MemoryOutboxRow).where(MemoryOutboxRow.aggregate_id.in_(aggregate_ids))
        )
        return int(result.rowcount or 0)

    async def _outbox_count_for_aggregate_ids(
        self,
        aggregate_ids: tuple[str, ...],
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        if not aggregate_ids:
            return 0
        conditions = [MemoryOutboxRow.aggregate_id.in_(aggregate_ids)]
        if statuses is not None:
            conditions.append(MemoryOutboxRow.status.in_(statuses))
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemoryOutboxRow).where(*conditions)
                )
            ).scalar_one()
        )

    async def _active_count(
        self,
        model: type[MemoryChunkRow] | type[MemoryFactRow],
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.space_id == space_id,
                        model.profile_id == profile_id,
                        model.thread_id == thread_id,
                        model.status != "deleted",
                    )
                )
            ).scalar_one()
        )


class PostgresFactRepository(FactRepositoryPort):
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now

    async def create(self, fact: MemoryFact) -> MemoryFact:
        row = MemoryFactRow(
            id=str(fact.id),
            space_id=str(fact.space_id),
            profile_id=str(fact.profile_id),
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
                profile_id=str(fact.profile_id),
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
                profile_id=current.profile_id,
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
        profile_ids: tuple[str, ...],
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
            MemoryFactRow.profile_id.in_(profile_ids),
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
        profile_id: str,
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
            MemoryFactRow.profile_id == profile_id,
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
        profile_id: str,
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
                        MemoryFactRow.profile_id == profile_id,
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


class PostgresEpisodeRepository(EpisodeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, episode: MemoryEpisode) -> MemoryEpisode:
        self._session.add(episode_to_row(episode))
        return episode


class PostgresDocumentRepository(DocumentRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, document: MemoryDocument) -> MemoryDocument:
        self._session.add(document_to_row(document))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Canonical document conflicted with existing data") from exc
        return document

    async def get_by_id(self, document_id: str) -> MemoryDocument | None:
        row = await self._session.get(MemoryDocumentRow, document_id)
        return document_row_to_domain(row) if row is not None else None

    async def find_active_by_content_hash(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str | None,
        content_hash: str,
    ) -> MemoryDocument | None:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.profile_id == profile_id,
            MemoryDocumentRow.content_hash == content_hash,
            MemoryDocumentRow.status == "active",
        ]
        if thread_id is None:
            conditions.append(MemoryDocumentRow.thread_id.is_(None))
            order_by = (MemoryDocumentRow.created_at.desc(), MemoryDocumentRow.id.desc())
        else:
            conditions.append(
                or_(MemoryDocumentRow.thread_id == thread_id, MemoryDocumentRow.thread_id.is_(None))
            )
            order_by = (
                case((MemoryDocumentRow.thread_id == thread_id, 0), else_=1),
                MemoryDocumentRow.created_at.desc(),
                MemoryDocumentRow.id.desc(),
            )
        row = (
            await self._session.execute(
                select(MemoryDocumentRow).where(*conditions).order_by(*order_by).limit(1)
            )
        ).scalar_one_or_none()
        return document_row_to_domain(row) if row is not None else None

    async def list_chunks(
        self,
        document_id: str,
        *,
        limit: int | None = None,
        cursor_sequence: int | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryChunk]:
        conditions = [
            MemoryChunkRow.document_id == document_id,
            MemoryChunkRow.status == "active",
        ]
        if cursor_sequence is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryChunkRow.sequence > cursor_sequence,
                    (MemoryChunkRow.sequence == cursor_sequence) & (MemoryChunkRow.id > cursor_id),
                )
            )
        statement = (
            select(MemoryChunkRow)
            .where(*conditions)
            .order_by(MemoryChunkRow.sequence, MemoryChunkRow.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).scalars()
        return [chunk_row_to_domain(row) for row in rows]

    async def list_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryDocument]:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.profile_id == profile_id,
        ]
        if status:
            conditions.append(MemoryDocumentRow.status == status)
        if thread_id is not None:
            conditions.append(
                or_(MemoryDocumentRow.thread_id == thread_id, MemoryDocumentRow.thread_id.is_(None))
            )
        rows = (
            await self._session.execute(
                select(MemoryDocumentRow)
                .where(*conditions)
                .order_by(MemoryDocumentRow.updated_at.desc(), MemoryDocumentRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [document_row_to_domain(row) for row in rows]

    async def soft_delete_with_chunks(
        self,
        *,
        document_id: str,
        now: datetime,
    ) -> tuple[MemoryDocument, tuple[str, ...]] | None:
        document = await self._session.get(MemoryDocumentRow, document_id)
        if document is None:
            return None

        chunk_rows = list(
            (
                await self._session.execute(
                    select(MemoryChunkRow).where(
                        MemoryChunkRow.document_id == document_id,
                        MemoryChunkRow.status == "active",
                    )
                )
            ).scalars()
        )
        deleted_chunk_ids = tuple(row.id for row in chunk_rows)
        for row in chunk_rows:
            row.status = "deleted"
            row.updated_at = now
        if document.status != "deleted":
            document.status = "deleted"
            document.updated_at = now
        return document_row_to_domain(document), deleted_chunk_ids


class PostgresChunkRepository(ChunkRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chunk_id: str) -> MemoryChunk | None:
        row = await self._session.get(MemoryChunkRow, chunk_id)
        return chunk_row_to_domain(row) if row is not None else None

    async def upsert(self, chunk: MemoryChunk) -> UpsertChunkResult:
        existing = (
            await self._session.execute(
                select(MemoryChunkRow).where(
                    MemoryChunkRow.space_id == str(chunk.space_id),
                    MemoryChunkRow.profile_id == str(chunk.profile_id),
                    MemoryChunkRow.source_hash == chunk.source_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return UpsertChunkResult(chunk_id=existing.id, duplicate=True)
        self._session.add(chunk_to_row(chunk))
        return UpsertChunkResult(chunk_id=str(chunk.id), duplicate=False)

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None,
    ) -> list[MemoryChunk]:
        if not chunk_ids:
            return []
        conditions = [
            MemoryChunkRow.id.in_(chunk_ids),
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.profile_id.in_(profile_ids),
            MemoryChunkRow.status == "active",
            MemoryChunkRow.classification != "restricted",
        ]
        if thread_id is not None:
            conditions.append(
                or_(MemoryChunkRow.thread_id == thread_id, MemoryChunkRow.thread_id.is_(None))
            )
        rows = (
            await self._session.execute(
                select(MemoryChunkRow).where(*conditions).order_by(MemoryChunkRow.created_at.desc())
            )
        ).scalars()
        by_id = {row.id: chunk_row_to_domain(row) for row in rows}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    async def keyword_search(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryChunk]:
        terms = _terms(query)
        conditions = [
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.profile_id.in_(profile_ids),
            MemoryChunkRow.status == "active",
            MemoryChunkRow.classification != "restricted",
        ]
        if thread_id is not None:
            conditions.append(
                or_(MemoryChunkRow.thread_id == thread_id, MemoryChunkRow.thread_id.is_(None))
            )
        rows = list(
            (
                await self._session.execute(
                    select(MemoryChunkRow)
                    .where(*conditions)
                    .order_by(MemoryChunkRow.created_at.desc())
                    .limit(_retrieval_candidate_limit(limit))
                )
            ).scalars()
        )
        if terms:
            rows.sort(key=lambda row: _score(row.normalized_text, terms), reverse=True)
            rows = [row for row in rows if _score(row.normalized_text, terms) > 0]
        return [chunk_row_to_domain(row) for row in rows[:limit]]


class PostgresCaptureRepository(CaptureRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, capture: CanonicalCapture) -> CanonicalCapture:
        self._session.add(capture_to_row(capture))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Canonical capture conflicted with existing data") from exc
        return capture

    async def get_by_id(self, capture_id: str) -> CanonicalCapture | None:
        row = await self._session.get(MemoryCaptureRow, capture_id)
        return capture_row_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(
        self,
        *,
        space_id: str,
        idempotency_key: str,
    ) -> CanonicalCapture | None:
        row = (
            await self._session.execute(
                select(MemoryCaptureRow).where(
                    MemoryCaptureRow.space_id == space_id,
                    MemoryCaptureRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return capture_row_to_domain(row) if row is not None else None

    async def get_for_update(self, capture_id: str) -> CanonicalCapture | None:
        row = (
            await self._session.execute(
                select(MemoryCaptureRow)
                .where(MemoryCaptureRow.id == capture_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return capture_row_to_domain(row) if row is not None else None

    async def save(self, capture: CanonicalCapture) -> CanonicalCapture:
        row = await self._session.get(MemoryCaptureRow, str(capture.id))
        if row is None:
            msg = "Capture row missing during save"
            raise RuntimeError(msg)
        apply_capture_to_row(capture, row)
        return capture

    async def list_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[CanonicalCapture]:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.profile_id == profile_id,
        ]
        if status:
            conditions.append(MemoryCaptureRow.status == status)
        if consolidation_status:
            conditions.append(MemoryCaptureRow.consolidation_status == consolidation_status)
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryCaptureRow.created_at < cursor_created_at,
                    (MemoryCaptureRow.created_at == cursor_created_at)
                    & (MemoryCaptureRow.id < cursor_id),
                )
            )
        rows = (
            await self._session.execute(
                select(MemoryCaptureRow)
                .where(*conditions)
                .order_by(MemoryCaptureRow.created_at.desc(), MemoryCaptureRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [capture_row_to_domain(row) for row in rows]

    async def count_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
        consolidation_statuses: tuple[str, ...],
    ) -> int:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.profile_id == profile_id,
        ]
        if status:
            conditions.append(MemoryCaptureRow.status == status)
        if consolidation_statuses:
            conditions.append(MemoryCaptureRow.consolidation_status.in_(consolidation_statuses))
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemoryCaptureRow).where(*conditions)
                )
            ).scalar_one()
        )


class PostgresSuggestionRepository(SuggestionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        self._session.add(suggestion_to_row(suggestion))
        return suggestion

    async def get_by_id(self, suggestion_id: str) -> MemorySuggestion | None:
        row = await self._session.get(MemorySuggestionRow, suggestion_id)
        return suggestion_row_to_domain(row) if row is not None else None

    async def get_for_update(self, suggestion_id: str) -> MemorySuggestion | None:
        row = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(MemorySuggestionRow.id == suggestion_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return suggestion_row_to_domain(row) if row is not None else None

    async def save(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        row = await self._session.get(MemorySuggestionRow, str(suggestion.id))
        if row is None:
            msg = "Suggestion row missing during save"
            raise RuntimeError(msg)
        apply_suggestion_to_row(suggestion, row)
        return suggestion

    async def list_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> list[MemorySuggestion]:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.profile_id == profile_id,
        ]
        if status:
            conditions.append(MemorySuggestionRow.status == status)
        if operation:
            conditions.append(MemorySuggestionRow.operation == operation)
        if category:
            conditions.append(MemorySuggestionRow.category == category)
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(*conditions)
                .order_by(MemorySuggestionRow.updated_at.desc())
                .limit(_retrieval_candidate_limit(limit) if tag else limit)
            )
        ).scalars()
        suggestions = [suggestion_row_to_domain(row) for row in rows]
        if tag:
            suggestions = [suggestion for suggestion in suggestions if tag in suggestion.tags]
        return suggestions[:limit]

    async def find_pending_duplicate(
        self,
        *,
        space_id: str,
        profile_id: str,
        candidate_fingerprint: str,
        operation: str,
        target_fact_id: str | None,
    ) -> MemorySuggestion | None:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.profile_id == profile_id,
            MemorySuggestionRow.status == "pending",
            MemorySuggestionRow.candidate_fingerprint == candidate_fingerprint,
            MemorySuggestionRow.operation == operation,
        ]
        if target_fact_id:
            conditions.append(MemorySuggestionRow.target_fact_id == target_fact_id)
        else:
            conditions.append(MemorySuggestionRow.target_fact_id.is_(None))
        row = (
            await self._session.execute(select(MemorySuggestionRow).where(*conditions).limit(1))
        ).scalar_one_or_none()
        return suggestion_row_to_domain(row) if row is not None else None

    async def list_expired_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[MemorySuggestion]:
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(
                    MemorySuggestionRow.status == "pending",
                    MemorySuggestionRow.expires_at.is_not(None),
                    MemorySuggestionRow.expires_at <= now,
                )
                .order_by(MemorySuggestionRow.expires_at, MemorySuggestionRow.id)
                .limit(limit)
            )
        ).scalars()
        return [suggestion_row_to_domain(row) for row in rows]

    async def list_pending_for_capture(
        self,
        *,
        capture_id: str,
        limit: int,
    ) -> list[MemorySuggestion]:
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(
                    MemorySuggestionRow.status == "pending",
                    MemorySuggestionRow.created_from_capture_id == capture_id,
                )
                .order_by(MemorySuggestionRow.created_at, MemorySuggestionRow.id)
                .limit(limit)
            )
        ).scalars()
        return [suggestion_row_to_domain(row) for row in rows]

    async def count_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
    ) -> int:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.profile_id == profile_id,
        ]
        if status:
            conditions.append(MemorySuggestionRow.status == status)
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemorySuggestionRow).where(*conditions)
                )
            ).scalar_one()
        )


class PostgresIdempotencyRepository(IdempotencyRepositoryPort):
    def __init__(self, session: AsyncSession, now: datetime) -> None:
        self._session = session
        self._now = now

    async def find(self, *, space_id: str, key: str) -> IdempotencyRecord | None:
        row = (
            await self._session.execute(
                select(MemoryIdempotencyRecordRow).where(
                    MemoryIdempotencyRecordRow.space_id == space_id,
                    MemoryIdempotencyRecordRow.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IdempotencyRecord(
            space_id=row.space_id,
            key=row.key,
            fingerprint=row.fingerprint,
            result_type=row.result_type,
            result_id=row.result_id,
        )

    async def save(self, record: IdempotencyRecord) -> None:
        self._session.add(
            MemoryIdempotencyRecordRow(
                space_id=record.space_id,
                key=record.key,
                fingerprint=record.fingerprint,
                result_type=record.result_type,
                result_id=record.result_id,
                created_at=self._now,
            )
        )


def _terms(query: str) -> tuple[str, ...]:
    return tuple(term for term in re.findall(r"\w+", query.lower()) if len(term) >= 3)


def _score(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    unique_terms = tuple(dict.fromkeys(terms))
    unique_hits = sum(1 for term in unique_terms if term in lowered)
    if unique_hits == 0:
        return 0
    capped_frequency = sum(min(lowered.count(term), 3) for term in unique_terms)
    density_penalty = len(lowered) // 800
    return unique_hits * 1000 + capped_frequency * 10 - density_penalty


def _retrieval_candidate_limit(limit: int) -> int:
    if limit <= 0:
        return 0
    return min(max(limit * 20, limit), 2000)


def _not_expired(model: type, now: datetime | None):
    comparable_now = now if now is not None else func.now()
    return or_(model.expires_at.is_(None), model.expires_at > comparable_now)


def _tags_match(
    values: list[str],
    *,
    tags_any: tuple[str, ...],
    tags_all: tuple[str, ...],
    tags_none: tuple[str, ...],
) -> bool:
    tags = set(values)
    return (
        (not tags_any or bool(tags.intersection(tags_any)))
        and (not tags_all or set(tags_all).issubset(tags))
        and (not tags_none or not tags.intersection(tags_none))
    )


def _source_ref_points_to_deleted_document(
    ref: MemorySourceRefRow,
    *,
    document_id: str,
    chunk_ids: set[str],
) -> bool:
    if ref.chunk_id is not None:
        return ref.chunk_id in chunk_ids
    return ref.source_type == "document" and ref.source_id == document_id


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class PostgresOutbox(OutboxPort):
    def __init__(self, session: AsyncSession, now: datetime) -> None:
        self._session = session
        self._now = now

    async def enqueue(self, event: OutboxEvent) -> None:
        self._session.add(
            MemoryOutboxRow(
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_version=event.aggregate_version,
                workload_class=event.workload_class,
                fairness_key=event.fairness_key or f"{event.aggregate_type}:{event.aggregate_id}",
                payload_json=event.payload,
                status="pending",
                attempt_count=0,
                next_attempt_at=self._now,
                created_at=self._now,
                updated_at=self._now,
            )
        )
