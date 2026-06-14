"""Postgres repository implementations."""

from __future__ import annotations

from datetime import datetime

from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.domain.entities import (
    MemoryAnchor,
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemorySuggestion,
)
from memo_stack_core.domain.errors import MemoryConflictError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.captures import CaptureRepositoryPort
from memo_stack_core.ports.repositories import (
    AnchorRepositoryPort,
    ChunkRepositoryPort,
    DocumentRepositoryPort,
    EpisodeRepositoryPort,
    IdempotencyRepositoryPort,
    SuggestionRepositoryPort,
    UpsertChunkResult,
)
from memo_stack_core.ports.unit_of_work import OutboxPort
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_adapters.postgres.mappers import (
    anchor_row_to_domain,
    anchor_to_row,
    apply_anchor_to_row,
    apply_capture_to_row,
    apply_suggestion_to_row,
    capture_row_to_domain,
    capture_to_row,
    chunk_row_to_domain,
    chunk_to_row,
    document_row_to_domain,
    document_to_row,
    episode_to_row,
    suggestion_row_to_domain,
    suggestion_to_row,
)
from memo_stack_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
    MemorySuggestionRow,
)
from memo_stack_adapters.postgres.repository_helpers import (
    _retrieval_candidate_limit,
    _score,
    _terms,
)


class PostgresEpisodeRepository(EpisodeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, episode: MemoryEpisode) -> MemoryEpisode:
        self._session.add(episode_to_row(episode))
        return episode


class PostgresAnchorRepository(AnchorRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, anchor: MemoryAnchor) -> MemoryAnchor:
        self._session.add(anchor_to_row(anchor))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Semantic anchor conflicted with existing data") from exc
        return anchor

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        row = await self._session.get(MemoryAnchorRow, anchor_id)
        return anchor_row_to_domain(row) if row is not None else None

    async def find_active_by_key(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str,
        normalized_key: str,
    ) -> MemoryAnchor | None:
        row = (
            await self._session.execute(
                select(MemoryAnchorRow)
                .where(
                    MemoryAnchorRow.space_id == space_id,
                    MemoryAnchorRow.memory_scope_id == memory_scope_id,
                    MemoryAnchorRow.kind == kind,
                    MemoryAnchorRow.normalized_key == normalized_key,
                    MemoryAnchorRow.status == "active",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return anchor_row_to_domain(row) if row is not None else None

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryAnchor]:
        conditions = [
            MemoryAnchorRow.space_id == space_id,
            MemoryAnchorRow.memory_scope_id == memory_scope_id,
        ]
        if kind:
            conditions.append(MemoryAnchorRow.kind == kind)
        if status:
            conditions.append(MemoryAnchorRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryAnchorRow)
                .where(*conditions)
                .order_by(MemoryAnchorRow.updated_at.desc(), MemoryAnchorRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [anchor_row_to_domain(row) for row in rows]

    async def save(self, anchor: MemoryAnchor) -> MemoryAnchor:
        row = await self._session.get(MemoryAnchorRow, str(anchor.id))
        if row is None:
            raise MemoryConflictError("Semantic anchor was deleted before save")
        apply_anchor_to_row(anchor, row)
        await self._session.flush()
        return anchor


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
        memory_scope_id: str,
        thread_id: str | None,
        content_hash: str,
    ) -> MemoryDocument | None:
        conditions = [
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.memory_scope_id == memory_scope_id,
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
                    MemoryChunkRow.memory_scope_id == str(chunk.memory_scope_id),
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

    async def keyword_search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryChunk]:
        terms = _terms(query)
        conditions = [
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.memory_scope_id.in_(memory_scope_ids),
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
                select(MemoryCaptureRow).where(MemoryCaptureRow.id == capture_id).with_for_update()
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
        memory_scope_id: str,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[CanonicalCapture]:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.memory_scope_id == memory_scope_id,
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
        memory_scope_id: str,
        status: str | None,
        consolidation_statuses: tuple[str, ...],
    ) -> int:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.memory_scope_id == memory_scope_id,
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
        memory_scope_id: str,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> list[MemorySuggestion]:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
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
        memory_scope_id: str,
        candidate_fingerprint: str,
        operation: str,
        target_fact_id: str | None,
    ) -> MemorySuggestion | None:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
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
        memory_scope_id: str,
        status: str | None,
    ) -> int:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
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
