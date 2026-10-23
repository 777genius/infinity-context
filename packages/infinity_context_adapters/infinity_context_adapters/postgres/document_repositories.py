"""Canonical document/chunk persistence and lexical query construction."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryDocument,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.repositories import (
    CanonicalChunkVersion,
    ChunkKeywordSearch,
    ChunkRepositoryPort,
    DocumentRepositoryPort,
    UpsertChunkResult,
)
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.canonical_retrieval_batching import (
    keyword_search_many,
)
from infinity_context_adapters.postgres.document_source_ref_coordination import (
    fence_exact_thread_writer,
    lock_chunk_parent_for_write,
    lock_document_deletion_evidence,
)
from infinity_context_adapters.postgres.mappers import (
    chunk_row_to_domain,
    chunk_to_row,
    document_row_to_domain,
    document_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
)
from infinity_context_adapters.postgres.repository_helpers import (
    _canonical_chunk_visibility_conditions,
    _escape_like,
    _grouped_sql_matches,
    _grouped_sql_score,
    _retrieval_candidate_limit,
    _score,
    _terms,
)


def _keyword_search_statement(
    *,
    space_id: str,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
    query: str,
    limit: int,
):
    terms = _terms(query)
    conditions = [
        MemoryChunkRow.space_id == space_id,
        MemoryChunkRow.memory_scope_id.in_(memory_scope_ids),
        *_canonical_chunk_visibility_conditions(MemoryChunkRow),
    ]
    if thread_id is not None:
        conditions.append(
            or_(MemoryChunkRow.thread_id == thread_id, MemoryChunkRow.thread_id.is_(None))
        )
    statement = select(MemoryChunkRow).where(*conditions)
    if terms:
        term_matches = _grouped_sql_matches(MemoryChunkRow.normalized_text, terms)
        lexical_score = _grouped_sql_score(term_matches)
        statement = statement.where(or_(*term_matches)).order_by(
            lexical_score.desc(),
            MemoryChunkRow.sequence.asc(),
            MemoryChunkRow.created_at.asc(),
            MemoryChunkRow.id.asc(),
        )
    else:
        statement = statement.order_by(MemoryChunkRow.created_at.desc(), MemoryChunkRow.id.desc())
    return statement.limit(_retrieval_candidate_limit(limit)), terms


class PostgresDocumentRepository(DocumentRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, document: MemoryDocument) -> MemoryDocument:
        if document.thread_id is not None:
            await fence_exact_thread_writer(
                self._session,
                space_id=str(document.space_id),
                memory_scope_id=str(document.memory_scope_id),
                thread_id=str(document.thread_id),
            )
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
        memory_scope_id: str,
        thread_id: str | None,
        content_hash: str,
    ) -> MemoryDocument | None:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.memory_scope_id == memory_scope_id,
            MemoryDocumentRow.content_hash == content_hash,
            MemoryDocumentRow.status == "active",
            MemoryDocumentRow.retrieval_projected.is_(False),
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

    async def list_chunks_by_document_ids(
        self,
        document_ids: tuple[str, ...],
        *,
        limit_per_document: int,
    ) -> list[MemoryChunk]:
        if not document_ids:
            return []
        document_rank = (
            func.row_number()
            .over(
                partition_by=MemoryChunkRow.document_id,
                order_by=(MemoryChunkRow.sequence.asc(), MemoryChunkRow.id.asc()),
            )
            .label("document_row_rank")
        )
        statement = (
            select(MemoryChunkRow, document_rank)
            .where(
                MemoryChunkRow.document_id.in_(document_ids),
                MemoryChunkRow.status == "active",
            )
            .order_by(
                MemoryChunkRow.document_id.asc(),
                MemoryChunkRow.sequence.asc(),
                MemoryChunkRow.id.asc(),
            )
        )
        rows = (await self._session.execute(statement)).all()
        return [
            chunk_row_to_domain(row)
            for row, document_row_rank in rows
            if document_row_rank <= limit_per_document
        ]

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryDocument]:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.memory_scope_id == memory_scope_id,
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

    async def list_exact_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str,
        limit: int,
        source_external_id: str | None,
        cursor_updated_at: datetime | None,
        cursor_id: str | None,
    ) -> list[MemoryDocument]:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.memory_scope_id == memory_scope_id,
            MemoryDocumentRow.thread_id == thread_id
            if thread_id is not None
            else MemoryDocumentRow.thread_id.is_(None),
            MemoryDocumentRow.status == status,
        ]
        if source_external_id is not None:
            conditions.append(MemoryDocumentRow.source_external_id == source_external_id)
        if cursor_updated_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryDocumentRow.updated_at < cursor_updated_at,
                    (MemoryDocumentRow.updated_at == cursor_updated_at)
                    & (MemoryDocumentRow.id < cursor_id),
                )
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
    ) -> tuple[MemoryDocument, tuple[CanonicalChunkVersion, ...]] | None:
        locked = await lock_document_deletion_evidence(
            self._session,
            document_id=document_id,
        )
        if locked is None:
            return None
        document, locked_chunks = locked
        chunk_rows = list(locked_chunks)
        deleted_chunk_versions = tuple(
            CanonicalChunkVersion(
                chunk_id=row.id,
                canonical_version=row.retrieval_version,
            )
            for row in chunk_rows
        )
        for row in chunk_rows:
            row.status = "deleted"
            row.retrieval_version += 1
            row.updated_at = now
        if document.status != "deleted":
            document.status = "deleted"
            document.updated_at = now
        return document_row_to_domain(document), deleted_chunk_versions


class PostgresChunkRepository(ChunkRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chunk_id: str) -> MemoryChunk | None:
        row = await self._session.get(MemoryChunkRow, chunk_id)
        return chunk_row_to_domain(row) if row is not None else None

    async def get_for_update(self, chunk_id: str) -> MemoryChunk | None:
        row = (
            await self._session.execute(
                select(MemoryChunkRow).where(MemoryChunkRow.id == chunk_id).with_for_update()
            )
        ).scalar_one_or_none()
        return chunk_row_to_domain(row) if row is not None else None

    async def upsert(self, chunk: MemoryChunk) -> UpsertChunkResult:
        if chunk.thread_id is not None:
            await fence_exact_thread_writer(
                self._session,
                space_id=str(chunk.space_id),
                memory_scope_id=str(chunk.memory_scope_id),
                thread_id=str(chunk.thread_id),
            )
        await lock_chunk_parent_for_write(self._session, chunk)
        existing = (
            await self._session.execute(
                select(MemoryChunkRow).where(
                    MemoryChunkRow.space_id == str(chunk.space_id),
                    MemoryChunkRow.memory_scope_id == str(chunk.memory_scope_id),
                    MemoryChunkRow.source_hash == chunk.source_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return UpsertChunkResult(chunk_id=existing.id, duplicate=True)
        self._session.add(chunk_to_row(chunk))
        return UpsertChunkResult(chunk_id=str(chunk.id), duplicate=False)

    async def list_for_episode(
        self,
        episode_id: str,
        *,
        limit: int | None = None,
        cursor_sequence: int | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryChunk]:
        conditions = [
            MemoryChunkRow.episode_id == episode_id,
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
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryChunk]:
        conditions = [
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.memory_scope_id == memory_scope_id,
        ]
        if thread_id is not None:
            conditions.append(
                or_(MemoryChunkRow.thread_id == thread_id, MemoryChunkRow.thread_id.is_(None))
            )
        if status is not None:
            conditions.append(MemoryChunkRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryChunkRow)
                .where(*conditions)
                .order_by(MemoryChunkRow.updated_at.desc(), MemoryChunkRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [chunk_row_to_domain(row) for row in rows]

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
    ) -> list[MemoryChunk]:
        if not chunk_ids:
            return []
        conditions = [
            MemoryChunkRow.id.in_(chunk_ids),
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.memory_scope_id.in_(memory_scope_ids),
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

    async def list_by_source_external_id_groups(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        source_external_id_groups: tuple[str, ...],
        exclude_chunk_ids: tuple[str, ...],
        limit: int,
        limit_per_group: int | None = None,
    ) -> list[MemoryChunk]:
        groups = tuple(
            dict.fromkeys(
                group.strip() for group in source_external_id_groups if group and group.strip()
            )
        )
        if (limit <= 0 and not limit_per_group) or not groups:
            return []
        source_conditions = tuple(
            or_(
                MemoryChunkRow.source_external_id == group,
                MemoryChunkRow.source_external_id.like(
                    f"{_escape_like(group)}:%",
                    escape="\\",
                ),
            )
            for group in groups
        )
        group_match_rank = case(
            *[(condition, index) for index, condition in enumerate(source_conditions)],
            else_=len(groups),
        )
        conditions = [
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.memory_scope_id.in_(memory_scope_ids),
            MemoryChunkRow.status == "active",
            MemoryChunkRow.classification != "restricted",
            or_(*source_conditions),
        ]
        if exclude_chunk_ids:
            conditions.append(MemoryChunkRow.id.not_in(exclude_chunk_ids))
        if thread_id is not None:
            conditions.append(
                or_(MemoryChunkRow.thread_id == thread_id, MemoryChunkRow.thread_id.is_(None))
            )
        if limit_per_group is not None:
            group_row_rank = (
                func.row_number()
                .over(
                    partition_by=group_match_rank,
                    order_by=(
                        MemoryChunkRow.source_external_id.asc(),
                        MemoryChunkRow.sequence.asc(),
                        MemoryChunkRow.id.asc(),
                    ),
                )
                .label("group_row_rank")
            )
            rows = (
                await self._session.execute(
                    select(MemoryChunkRow, group_row_rank).where(*conditions)
                )
            ).all()
            ranked = [
                (int(group_row_rank), chunk_row_to_domain(row))
                for row, group_row_rank in rows
                if int(group_row_rank) <= limit_per_group
            ]
            ranked.sort(
                key=lambda item: (
                    item[0],
                    str(item[1].source_external_id or ""),
                    item[1].sequence,
                    str(item[1].id),
                )
            )
            return [chunk for _, chunk in ranked]
        rows = (
            await self._session.execute(
                select(MemoryChunkRow)
                .where(*conditions)
                .order_by(
                    MemoryChunkRow.source_external_id.asc(),
                    MemoryChunkRow.sequence.asc(),
                    MemoryChunkRow.id.asc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [chunk_row_to_domain(row) for row in rows]

    async def keyword_search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryChunk]:
        statement, terms = _keyword_search_statement(
            space_id=space_id,
            memory_scope_ids=memory_scope_ids,
            thread_id=thread_id,
            query=query,
            limit=limit,
        )
        rows = list((await self._session.execute(statement)).scalars())
        if terms:
            scored_rows = [
                (score, index, row)
                for index, row in enumerate(rows)
                for score in (_score(row.normalized_text, terms),)
                if score > 0
            ]
            scored_rows.sort(key=lambda item: (-item[0], item[1]))
            rows = [row for _, _, row in scored_rows]
        return [chunk_row_to_domain(row) for row in rows[:limit]]

    async def keyword_search_many(
        self,
        requests: tuple[ChunkKeywordSearch, ...],
    ) -> list[list[MemoryChunk]]:
        return await keyword_search_many(self._session, requests)
