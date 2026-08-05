"""Forget fact use case."""

from infinity_context_core.application.dto import FactResult, ForgetFactCommand
from infinity_context_core.domain.entities import FactStatus
from infinity_context_core.domain.errors import MemoryNotFoundError
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ForgetFactUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ForgetFactCommand) -> FactResult:
        async with self._uow_factory() as uow:
            current = await uow.facts.get_for_update(command.fact_id)
            if current is None:
                raise MemoryNotFoundError("Fact not found")
            if current.status == FactStatus.DELETED:
                await uow.commit()
                return FactResult(fact=current, indexing_status="already_deleted")

            forgotten = current.forget(now=self._clock.now())
            saved = await uow.facts.save(forgotten)
            await uow.outbox.enqueue(
                OutboxEvent(
                    event_type="graph.delete_fact",
                    aggregate_type="fact",
                    aggregate_id=str(saved.id),
                    aggregate_version=saved.version,
                    payload={"fact_id": str(saved.id), "version": saved.version},
                )
            )
            await uow.commit()
            return FactResult(fact=saved, indexing_status="pending")
