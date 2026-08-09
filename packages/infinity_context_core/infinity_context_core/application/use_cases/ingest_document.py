"""Ingest text documents into canonical documents and chunks."""

from __future__ import annotations

from infinity_context_core.application.benchmark_managed_write_admission import (
    require_managed_document_admission,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import IngestDocumentCommand, IngestDocumentResult
from infinity_context_core.application.normalize import (
    content_hash,
    estimate_tokens,
    normalize_text,
    scoped_idempotency_key,
    scoped_source_hash,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryDocument,
    MemoryDocumentId,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.ports.benchmark_runs import is_managed_benchmark_space_id
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


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
        managed_benchmark = is_managed_benchmark_space_id(str(command.space_id))
        body_hash = content_hash(command.text)

        async with self._uow_factory() as uow:
            managed_key = None
            if managed_benchmark:
                managed_key = await require_managed_document_admission(uow=uow, command=command)
            raw_key = (
                managed_key
                or command.idempotency_key
                or (
                    f"document:{command.space_id}:{command.memory_scope_id}:"
                    f"{command.source_type}:{command.source_external_id}:{body_hash}"
                )
            )
            key = scoped_idempotency_key(
                "ingest_document",
                command.memory_scope_id,
                command.thread_id,
                raw_key,
            )
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
                memory_scope_id=str(command.memory_scope_id),
                thread_id=str(command.thread_id) if command.thread_id else None,
                content_hash=body_hash,
            )
            if existing_document is not None:
                chunks = await uow.documents.list_chunks(str(existing_document.id))
                if command.idempotency_key or managed_benchmark:
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
                memory_scope_id=command.memory_scope_id,
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
                    memory_scope_id=str(command.memory_scope_id),
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
            for piece in fragment_document_text(command.text):
                chunk_metadata = _chunk_metadata_for_fragment(
                    command.chunk_metadata,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                )
                retrieval_metadata = {**chunk_metadata, "title": saved_document.title}
                retrieval_text = document_chunk_retrieval_text(
                    text=piece.text,
                    metadata=retrieval_metadata,
                    title=saved_document.title,
                )
                chunk = MemoryChunk.create(
                    chunk_id=MemoryChunkId(self._ids.new_id("chunk")),
                    space_id=command.space_id,
                    memory_scope_id=command.memory_scope_id,
                    thread_id=command.thread_id,
                    document_id=saved_document.id,
                    episode_id=None,
                    source_type=command.source_type,
                    source_external_id=command.source_external_id,
                    source_hash=scoped_source_hash(
                        command.space_id,
                        command.memory_scope_id,
                        str(saved_document.id),
                        piece.sequence,
                        normalize_text(piece.text),
                    ),
                    kind=piece.kind,
                    text=piece.text,
                    normalized_text=normalize_text(retrieval_text),
                    sequence=piece.sequence,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    token_estimate=estimate_tokens(retrieval_text),
                    now=now,
                    metadata={
                        **retrieval_metadata,
                        "node_kind": piece.node_kind,
                        "heading": piece.heading,
                        "ordinal_in_heading": piece.ordinal_in_heading,
                    },
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
            if (
                stored_chunks
                and not managed_benchmark
                and _can_project_document_to_external_memory(saved_document.classification)
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
                            "memory_scope_id": str(saved_document.memory_scope_id),
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
                    memory_scope_id=str(command.memory_scope_id),
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


def _chunk_metadata_for_fragment(
    metadata: dict[str, object] | None,
    *,
    char_start: int,
    char_end: int,
) -> dict[str, object]:
    safe = dict(metadata or {})
    refs = _source_refs_for_fragment(
        safe.get("source_refs"),
        char_start=char_start,
        char_end=char_end,
    )
    if refs:
        safe["source_refs"] = refs
        safe["source_ref_count"] = len(refs)
    else:
        safe.pop("source_refs", None)
        safe.pop("source_ref_count", None)
    return safe


def _source_refs_for_fragment(
    value: object,
    *,
    char_start: int,
    char_end: int,
) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    refs: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ref_start = _optional_int(item.get("char_start"))
        ref_end = _optional_int(item.get("char_end"))
        if ref_start is None or ref_end is None:
            if char_start != 0:
                continue
            refs.append(dict(item))
        elif ref_start <= char_end and ref_end >= char_start:
            ref = dict(item)
            ref["chunk_char_start"] = max(ref_start, char_start) - char_start
            ref["chunk_char_end"] = max(min(ref_end, char_end) - char_start, 0)
            refs.append(ref)
        if len(refs) >= 24:
            break
    return refs


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None
