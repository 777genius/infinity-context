"""Update fact use case."""

from memo_stack_core.application.dto import FactResult, UpdateFactCommand
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class UpdateFactUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: UpdateFactCommand) -> FactResult:
        async with self._uow_factory() as uow:
            current = await uow.facts.get_for_update(command.fact_id)
            if current is None:
                raise MemoryNotFoundError("Fact not found")
            updated = current.update(
                expected_version=command.expected_version,
                text=command.text,
                source_refs=command.source_refs,
                reason=command.reason,
                now=self._clock.now(),
            )
            saved = await uow.facts.save(updated)
            await uow.outbox.enqueue(
                OutboxEvent(
                    event_type="graph.upsert_fact",
                    aggregate_type="fact",
                    aggregate_id=str(saved.id),
                    aggregate_version=saved.version,
                    payload={"fact_id": str(saved.id), "version": saved.version},
                )
            )
            await uow.commit()
            return FactResult(fact=saved, indexing_status="pending")
