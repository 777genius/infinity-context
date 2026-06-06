"""Soft-delete canonical documents and derived vector projections."""

from __future__ import annotations

from memo_stack_core.application.dto import DeleteDocumentCommand, DeleteDocumentResult
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class DeleteDocumentUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: DeleteDocumentCommand) -> DeleteDocumentResult:
        async with self._uow_factory() as uow:
            now = self._clock.now()
            result = await uow.documents.soft_delete_with_chunks(
                document_id=command.document_id,
                now=now,
            )
            if result is None:
                raise MemoryNotFoundError("Document not found")
            document, chunk_ids = result
            deleted_facts = await uow.facts.delete_facts_sourced_only_by_chunks(
                space_id=str(document.space_id),
                profile_id=str(document.profile_id),
                document_id=str(document.id),
                chunk_ids=chunk_ids,
                now=now,
            )
            if chunk_ids:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="vector.delete_chunks",
                        aggregate_type="document",
                        aggregate_id=str(document.id),
                        payload={"document_id": str(document.id), "chunk_ids": list(chunk_ids)},
                    )
                )
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="cognee.forget_document",
                        aggregate_type="document",
                        aggregate_id=str(document.id),
                        payload={
                            "document_id": str(document.id),
                            "chunk_ids": list(chunk_ids),
                            "space_id": str(document.space_id),
                            "profile_id": str(document.profile_id),
                        },
                    )
                )
            for fact_id, _version in deleted_facts:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="graph.delete_fact",
                        aggregate_type="fact",
                        aggregate_id=fact_id,
                        payload={"fact_id": fact_id},
                    )
                )
            await uow.commit()
        return DeleteDocumentResult(
            document=document,
            deleted_chunks=len(chunk_ids),
            deleted_facts=len(deleted_facts),
            indexing_status="pending" if chunk_ids else "already_deleted",
        )
