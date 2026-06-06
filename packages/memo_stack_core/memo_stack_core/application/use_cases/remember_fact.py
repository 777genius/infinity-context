"""Remember fact use case."""

from __future__ import annotations

from hashlib import sha256

from memo_stack_core.application.dto import FactResult, RememberFactCommand
from memo_stack_core.application.normalize import scoped_idempotency_key
from memo_stack_core.domain.entities import MemoryFact, MemoryFactId
from memo_stack_core.domain.errors import MemoryConflictError, MemoryInvariantError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


def remember_fact_fingerprint(command: RememberFactCommand) -> str:
    source_keys = "|".join(
        f"{ref.source_type}:{ref.source_id}:{ref.chunk_id or ''}" for ref in command.source_refs
    )
    raw = (
        f"{command.space_id}:{command.profile_id}:{command.thread_id or ''}:"
        f"{command.kind}:{command.text}:{command.classification}:{source_keys}"
    )
    return sha256(raw.encode("utf-8")).hexdigest()


class RememberFactUseCase:
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

    async def execute(self, command: RememberFactCommand) -> FactResult:
        fingerprint = remember_fact_fingerprint(command)
        idempotency_key = (
            scoped_idempotency_key(
                "remember_fact",
                command.profile_id,
                command.thread_id,
                command.idempotency_key,
            )
            if command.idempotency_key
            else None
        )

        async with self._uow_factory() as uow:
            if idempotency_key:
                existing = await uow.idempotency.find(
                    space_id=str(command.space_id),
                    key=idempotency_key,
                )
                if existing:
                    if existing.fingerprint != fingerprint:
                        raise MemoryConflictError("Idempotency key was used with different body")
                    fact = await uow.facts.get_by_id(existing.result_id)
                    if fact is None:
                        raise MemoryInvariantError("Idempotency result points to missing fact")
                    return FactResult(fact=fact, indexing_status="already_indexed_or_pending")

            now = self._clock.now()
            fact = MemoryFact.create(
                fact_id=MemoryFactId(self._ids.new_id("fact")),
                space_id=command.space_id,
                profile_id=command.profile_id,
                thread_id=command.thread_id,
                text=command.text,
                kind=command.kind,
                source_refs=command.source_refs,
                classification=command.classification,
                now=now,
            )
            saved = await uow.facts.create(fact)
            await uow.outbox.enqueue(
                OutboxEvent(
                    event_type="graph.upsert_fact",
                    aggregate_type="fact",
                    aggregate_id=str(saved.id),
                    aggregate_version=saved.version,
                    payload={"fact_id": str(saved.id), "version": saved.version},
                )
            )
            if idempotency_key:
                await uow.idempotency.save(
                    IdempotencyRecord(
                        space_id=str(command.space_id),
                        key=idempotency_key,
                        fingerprint=fingerprint,
                        result_type="fact",
                        result_id=str(saved.id),
                    )
                )
            try:
                await uow.commit()
            except MemoryConflictError as exc:
                if not idempotency_key:
                    raise
                existing = await uow.idempotency.find(
                    space_id=str(command.space_id),
                    key=idempotency_key,
                )
                if existing is None:
                    raise
                if existing.fingerprint != fingerprint:
                    raise MemoryConflictError(
                        "Idempotency key was used with different body"
                    ) from exc
                fact = await uow.facts.get_by_id(existing.result_id)
                if fact is None:
                    raise MemoryInvariantError("Idempotency result points to missing fact") from exc
                return FactResult(fact=fact, indexing_status="already_indexed_or_pending")
            return FactResult(fact=saved, indexing_status="pending")
