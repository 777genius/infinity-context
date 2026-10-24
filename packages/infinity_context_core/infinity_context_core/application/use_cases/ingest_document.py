"""Ingest text documents into canonical documents and chunks."""

from __future__ import annotations

from infinity_context_core.application.benchmark_managed_write_admission import (
    require_managed_document_admission,
)
from infinity_context_core.application.document_fragment_metadata import (
    _chunk_metadata_for_fragment as _chunk_metadata_for_fragment,
)
from infinity_context_core.application.document_fragment_metadata import (
    _optional_int as _optional_int,
)
from infinity_context_core.application.document_fragment_metadata import (
    _source_refs_for_fragment as _source_refs_for_fragment,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.document_ingestion_replay import (
    document_idempotency_key,
    find_document_duplicate,
    replay_document_receipt,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import IngestDocumentCommand, IngestDocumentResult
from infinity_context_core.application.normalize import (
    content_hash,
    estimate_tokens,
    normalize_text,
    scoped_source_hash,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryDocument,
    MemoryDocumentId,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.features.document_ingestion.public import (
    document_content_digest,
    legacy_document_content_digest,
)
from infinity_context_core.ports.benchmark_runs import is_managed_benchmark_space_id
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAuthorityPort,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


class IngestDocumentUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        strict_v4_authority: ManagedBenchmarkStrictV4DocumentAuthorityPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._strict_v4_authority = strict_v4_authority

    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        try:
            return await self._execute_once(command)
        except MemoryConflictError as exc:
            # Flush/commit conflicts roll back the original transaction. Recover
            # only from fresh canonical reads and the same validated replay policy.
            async with self._uow_factory() as uow:
                managed = is_managed_benchmark_space_id(str(command.space_id))
                body_hash = (
                    content_hash(command.text) if managed else document_content_digest(command.text)
                )
                keys, managed_admitted = await self._keys(uow, command, body_hash)
                for key in keys:
                    existing = await uow.idempotency.find(space_id=str(command.space_id), key=key)
                    if existing is not None:
                        try:
                            return await replay_document_receipt(
                                uow,
                                command,
                                existing,
                                modern_hash=document_content_digest(command.text),
                                managed=managed_admitted,
                            )
                        except MemoryConflictError:
                            if key == keys[0]:
                                raise
                duplicate = await find_document_duplicate(
                    uow, command, body_hash=body_hash, managed=managed_admitted
                )
                if duplicate is not None:
                    if command.idempotency_key or managed:
                        try:
                            await self._record_duplicate_receipt(
                                uow, command, duplicate, key=keys[0], body_hash=body_hash
                            )
                        except MemoryConflictError:
                            # A different request may have bound this explicit
                            # key while we recovered the shared document.
                            async with self._uow_factory() as replay_uow:
                                replay_keys, replay_managed = await self._keys(
                                    replay_uow, command, body_hash
                                )
                                record = await replay_uow.idempotency.find(
                                    space_id=str(command.space_id), key=replay_keys[0]
                                )
                                if record is None:
                                    raise
                                return await replay_document_receipt(
                                    replay_uow,
                                    command,
                                    record,
                                    modern_hash=document_content_digest(command.text),
                                    managed=replay_managed,
                                )
                    return duplicate
            raise exc

    async def _keys(self, uow, command, body_hash: str) -> tuple[tuple[str, ...], bool]:
        managed_key = await require_managed_document_admission(
            uow=uow, command=command, strict_v4_authority=self._strict_v4_authority
        )
        strict = self._strict_v4_authority is not None
        key = document_idempotency_key(command, body_hash, managed_key, strict)
        if managed_key is not None or command.idempotency_key:
            return (key,), managed_key is not None
        legacy_key = document_idempotency_key(
            command, legacy_document_content_digest(command.text), None, False
        )
        return tuple(dict.fromkeys((key, legacy_key))), False

    async def _execute_once(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        managed_benchmark = is_managed_benchmark_space_id(str(command.space_id))
        body_hash = (
            content_hash(command.text)
            if managed_benchmark
            else document_content_digest(command.text)
        )
        async with self._uow_factory() as uow:
            keys, managed_admitted = await self._keys(uow, command, body_hash)
            key = keys[0]
            for lookup_key in keys:
                existing = await uow.idempotency.find(
                    space_id=str(command.space_id), key=lookup_key
                )
                if existing is not None:
                    try:
                        return await replay_document_receipt(
                            uow,
                            command,
                            existing,
                            modern_hash=document_content_digest(command.text),
                            managed=managed_admitted,
                        )
                    except MemoryConflictError:
                        if lookup_key == keys[0]:
                            raise
            duplicate = await find_document_duplicate(
                uow, command, body_hash=body_hash, managed=managed_admitted
            )
            if duplicate is not None:
                if command.idempotency_key or managed_benchmark:
                    await self._record_duplicate_receipt(
                        uow, command, duplicate, key=key, body_hash=body_hash
                    )
                return duplicate

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
            saved_document = await uow.documents.create(document)
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
            await uow.commit()
        return IngestDocumentResult(
            document=saved_document,
            chunks=tuple(stored_chunks),
            duplicate_chunks=duplicate_chunks,
            indexing_status="pending",
        )

    @staticmethod
    async def _record_duplicate_receipt(uow, command, result, *, key: str, body_hash: str) -> None:
        await uow.idempotency.save(
            IdempotencyRecord(
                space_id=str(command.space_id),
                key=key,
                fingerprint=body_hash,
                result_type="document",
                result_id=str(result.document.id),
            )
        )
        await uow.commit()


def _can_project_document_to_external_memory(classification: str) -> bool:
    return classification in {"public", "internal"}
