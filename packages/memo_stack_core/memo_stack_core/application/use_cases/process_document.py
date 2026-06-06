"""Re-enqueue derived processing for an existing canonical document."""

from __future__ import annotations

from memo_stack_core.application.dto import ProcessDocumentCommand, ProcessDocumentResult
from memo_stack_core.application.normalize import scoped_idempotency_key, scoped_source_hash
from memo_stack_core.domain.entities import LifecycleStatus
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryInvariantError,
    MemoryNotFoundError,
)
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ProcessDocumentUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: ProcessDocumentCommand) -> ProcessDocumentResult:
        async with self._uow_factory() as uow:
            document = await uow.documents.get_by_id(command.document_id)
            if document is None or document.status == LifecycleStatus.DELETED:
                raise MemoryNotFoundError("Document not found")
            fingerprint = scoped_source_hash("document_process", command.document_id)
            idempotency_key = (
                scoped_idempotency_key(
                    "process_document",
                    document.profile_id,
                    command.idempotency_key,
                )
                if command.idempotency_key
                else None
            )
            if idempotency_key:
                existing = await uow.idempotency.find(
                    space_id=str(document.space_id),
                    key=idempotency_key,
                )
                if existing:
                    if existing.fingerprint != fingerprint:
                        raise MemoryConflictError("Idempotency key was used with different body")
                    result_document = await uow.documents.get_by_id(existing.result_id)
                    if result_document is None:
                        raise MemoryInvariantError("Idempotency result points to missing document")
                    if result_document.status == LifecycleStatus.DELETED:
                        raise MemoryNotFoundError("Document not found")
                    result_chunks = await uow.documents.list_chunks(str(result_document.id))
                    return ProcessDocumentResult(
                        document=result_document,
                        chunks=len(result_chunks),
                        indexing_status="already_indexed_or_pending",
                    )

            chunks = await uow.documents.list_chunks(command.document_id)
            for chunk in chunks:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="vector.upsert_chunk",
                        aggregate_type="chunk",
                        aggregate_id=str(chunk.id),
                        payload={"chunk_id": str(chunk.id), "document_id": str(document.id)},
                    )
                )
            if idempotency_key:
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id=str(document.space_id),
                        key=idempotency_key,
                        fingerprint=fingerprint,
                        result_type="document_process",
                        result_id=str(document.id),
                    )
                )
            await uow.commit()

        return ProcessDocumentResult(
            document=document,
            chunks=len(chunks),
            indexing_status="pending" if chunks else "nothing_to_process",
        )
