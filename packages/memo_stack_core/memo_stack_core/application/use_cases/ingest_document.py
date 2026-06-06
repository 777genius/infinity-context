"""Ingest text documents into canonical documents and chunks."""

from __future__ import annotations

from memo_stack_core.application.chunker import chunk_text
from memo_stack_core.application.document_text import document_chunk_retrieval_text
from memo_stack_core.application.dto import IngestDocumentCommand, IngestDocumentResult
from memo_stack_core.application.normalize import (
    content_hash,
    estimate_tokens,
    normalize_text,
    scoped_idempotency_key,
    scoped_source_hash,
)
from memo_stack_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocument,
    MemoryDocumentId,
)
from memo_stack_core.domain.errors import MemoryConflictError, MemoryInvariantError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class IngestDocumentUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        body_hash = content_hash(command.text)
        raw_key = command.idempotency_key or (
            f"document:{command.space_id}:{command.profile_id}:"
            f"{command.source_type}:{command.source_external_id}:{body_hash}"
        )
        key = scoped_idempotency_key(
            "ingest_document",
            command.profile_id,
            command.thread_id,
            raw_key,
        )

        async with self._uow_factory() as uow:
            existing = await uow.idempotency.find(space_id=str(command.space_id), key=key)
            if existing:
                if existing.fingerprint != body_hash:
                    raise MemoryConflictError("Idempotency key was used with different document")
                document = await uow.documents.get_by_id(existing.result_id)
                if document is None:
                    raise MemoryInvariantError("Idempotency result points to missing document")
                chunks = await uow.documents.list_chunks(str(document.id))
                return IngestDocumentResult(
                    document=document,
                    chunks=tuple(chunks),
                    duplicate_chunks=len(chunks),
                    indexing_status="already_indexed_or_pending",
                )

            existing_document = await uow.documents.find_active_by_content_hash(
                space_id=str(command.space_id),
                profile_id=str(command.profile_id),
                thread_id=str(command.thread_id) if command.thread_id else None,
                content_hash=body_hash,
            )
            if existing_document is not None:
                chunks = await uow.documents.list_chunks(str(existing_document.id))
                if command.idempotency_key:
                    await uow.idempotency.save(
                        IdempotencyRecord(
                            space_id=str(command.space_id),
                            key=key,
                            fingerprint=body_hash,
                            result_type="document",
                            result_id=str(existing_document.id),
                        )
                    )
                    try:
                        await uow.commit()
                    except MemoryConflictError as exc:
                        existing = await uow.idempotency.find(
                            space_id=str(command.space_id),
                            key=key,
                        )
                        if existing is None:
                            raise
                        if existing.fingerprint != body_hash:
                            raise MemoryConflictError(
                                "Idempotency key was used with different document"
                            ) from exc
                        document = await uow.documents.get_by_id(existing.result_id)
                        if document is None:
                            raise MemoryInvariantError(
                                "Idempotency result points to missing document"
                            ) from exc
                        chunks = await uow.documents.list_chunks(str(document.id))
                        return IngestDocumentResult(
                            document=document,
                            chunks=tuple(chunks),
                            duplicate_chunks=len(chunks),
                            indexing_status="already_indexed_or_pending",
                        )
                return IngestDocumentResult(
                    document=existing_document,
                    chunks=tuple(chunks),
                    duplicate_chunks=len(chunks),
                    indexing_status="already_indexed_or_pending",
                )

            now = self._clock.now()
            document = MemoryDocument.create(
                document_id=MemoryDocumentId(self._ids.new_id("doc")),
                space_id=command.space_id,
                profile_id=command.profile_id,
                thread_id=command.thread_id,
                title=command.title,
                source_type=command.source_type,
                source_external_id=command.source_external_id,
                content_hash=body_hash,
                now=now,
                classification=command.classification,
            )
            try:
                saved_document = await uow.documents.create(document)
            except MemoryConflictError:
                existing_document = await uow.documents.find_active_by_content_hash(
                    space_id=str(command.space_id),
                    profile_id=str(command.profile_id),
                    thread_id=str(command.thread_id) if command.thread_id else None,
                    content_hash=body_hash,
                )
                if existing_document is None:
                    raise
                chunks = await uow.documents.list_chunks(str(existing_document.id))
                return IngestDocumentResult(
                    document=existing_document,
                    chunks=tuple(chunks),
                    duplicate_chunks=len(chunks),
                    indexing_status="already_indexed_or_pending",
                )
            stored_chunks = []
            duplicate_chunks = 0
            for piece in chunk_text(command.text):
                retrieval_text = document_chunk_retrieval_text(
                    text=piece.text,
                    title=saved_document.title,
                )
                chunk = MemoryChunk.create(
                    chunk_id=MemoryChunkId(self._ids.new_id("chunk")),
                    space_id=command.space_id,
                    profile_id=command.profile_id,
                    thread_id=command.thread_id,
                    document_id=saved_document.id,
                    episode_id=None,
                    source_type=command.source_type,
                    source_external_id=command.source_external_id,
                    source_hash=scoped_source_hash(
                        command.space_id,
                        command.profile_id,
                        str(saved_document.id),
                        piece.sequence,
                        normalize_text(piece.text),
                    ),
                    kind=MemoryChunkKind.DOCUMENT_SECTION,
                    text=piece.text,
                    normalized_text=normalize_text(retrieval_text),
                    sequence=piece.sequence,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    token_estimate=estimate_tokens(retrieval_text),
                    now=now,
                    metadata={"title": saved_document.title},
                    classification=saved_document.classification,
                )
                upsert = await uow.chunks.upsert(chunk)
                if upsert.duplicate:
                    duplicate_chunks += 1
                    continue
                stored_chunks.append(chunk)
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="vector.upsert_chunk",
                        aggregate_type="chunk",
                        aggregate_id=upsert.chunk_id,
                        payload={"chunk_id": upsert.chunk_id},
                    )
                )
            if stored_chunks and _can_project_document_to_external_memory(
                saved_document.classification
            ):
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="cognee.ingest_document",
                        aggregate_type="document",
                        aggregate_id=str(saved_document.id),
                        payload={
                            "document_id": str(saved_document.id),
                            "chunk_ids": [str(chunk.id) for chunk in stored_chunks],
                            "space_id": str(saved_document.space_id),
                            "profile_id": str(saved_document.profile_id),
                        },
                    )
                )

            await uow.idempotency.save(
                IdempotencyRecord(
                    space_id=str(command.space_id),
                    key=key,
                    fingerprint=body_hash,
                    result_type="document",
                    result_id=str(saved_document.id),
                )
            )
            try:
                await uow.commit()
            except MemoryConflictError as exc:
                existing = await uow.idempotency.find(space_id=str(command.space_id), key=key)
                if existing:
                    if existing.fingerprint != body_hash:
                        raise MemoryConflictError(
                            "Idempotency key was used with different document"
                        ) from exc
                    document = await uow.documents.get_by_id(existing.result_id)
                    if document is None:
                        raise MemoryInvariantError(
                            "Idempotency result points to missing document"
                        ) from exc
                    chunks = await uow.documents.list_chunks(str(document.id))
                    return IngestDocumentResult(
                        document=document,
                        chunks=tuple(chunks),
                        duplicate_chunks=len(chunks),
                        indexing_status="already_indexed_or_pending",
                    )
                existing_document = await uow.documents.find_active_by_content_hash(
                    space_id=str(command.space_id),
                    profile_id=str(command.profile_id),
                    thread_id=str(command.thread_id) if command.thread_id else None,
                    content_hash=body_hash,
                )
                if existing_document is None:
                    raise
                chunks = await uow.documents.list_chunks(str(existing_document.id))
                return IngestDocumentResult(
                    document=existing_document,
                    chunks=tuple(chunks),
                    duplicate_chunks=len(chunks),
                    indexing_status="already_indexed_or_pending",
                )

        return IngestDocumentResult(
            document=saved_document,
            chunks=tuple(stored_chunks),
            duplicate_chunks=duplicate_chunks,
            indexing_status="pending",
        )


def _can_project_document_to_external_memory(classification: str) -> bool:
    return classification in {"public", "internal"}
