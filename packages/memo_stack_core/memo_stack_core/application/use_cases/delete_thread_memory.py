"""Thread/session memory deletion use case."""

from memo_stack_core.application.dto import DeleteThreadMemoryCommand, DeleteThreadMemoryResult
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class DeleteThreadMemoryUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: DeleteThreadMemoryCommand) -> DeleteThreadMemoryResult:
        async with self._uow_factory() as uow:
            result = await uow.scope.delete_thread_memory(
                space_id=str(command.space_id),
                profile_id=str(command.profile_id),
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
                            "profile_id": str(command.profile_id),
                            "thread_id": str(command.thread_id),
                            "chunk_ids": list(result.deleted_chunk_ids),
                        },
                    )
                )
            for fact_id in result.deleted_fact_ids:
                await uow.outbox.enqueue(
                    OutboxEvent(
                        event_type="graph.delete_fact",
                        aggregate_type="thread",
                        aggregate_id=str(command.thread_id),
                        payload={
                            "space_id": str(command.space_id),
                            "profile_id": str(command.profile_id),
                            "thread_id": str(command.thread_id),
                            "fact_id": fact_id,
                        },
                    )
                )
            await uow.commit()
        return DeleteThreadMemoryResult(
            deleted_chunks=result.deleted_chunks,
            deleted_facts=result.deleted_facts,
            deleted_jobs=result.deleted_jobs,
        )
