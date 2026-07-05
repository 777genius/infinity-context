"""Thread/session memory deletion use case."""

from infinity_context_core.application.dto import DeleteThreadMemoryCommand, DeleteThreadMemoryResult
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


class DeleteThreadMemoryUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: DeleteThreadMemoryCommand) -> DeleteThreadMemoryResult:
        async with self._uow_factory() as uow:
            result = await uow.scope.delete_thread_memory(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=str(command.thread_id),
            )
            if result.deleted_chunk_ids:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="vector.delete_chunks",
                        aggregate_type="thread",
                        aggregate_id=str(command.thread_id),
                        payload={
                            "space_id": str(command.space_id),
                            "memory_scope_id": str(command.memory_scope_id),
                            "thread_id": str(command.thread_id),
                            "chunk_ids": list(result.deleted_chunk_ids),
                        },
                    )
                )
            deleted_fact_versions = dict(result.deleted_fact_versions)
            for fact_id in result.deleted_fact_ids:
                fact_version = deleted_fact_versions.get(fact_id)
                # Keep thread-cleanup projection jobs under the thread aggregate so
                # compatibility status counts stay scoped to canonical row cleanup.
                payload: dict[str, object] = {
                    "space_id": str(command.space_id),
                    "memory_scope_id": str(command.memory_scope_id),
                    "thread_id": str(command.thread_id),
                    "fact_id": fact_id,
                }
                if fact_version is not None:
                    payload["version"] = fact_version
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="graph.delete_fact",
                        aggregate_type="thread",
                        aggregate_id=str(command.thread_id),
                        aggregate_version=fact_version,
                        payload=payload,
                    )
                )
            await uow.commit()
        return DeleteThreadMemoryResult(
            deleted_chunks=result.deleted_chunks,
            deleted_facts=result.deleted_facts,
            deleted_jobs=result.deleted_jobs,
        )
