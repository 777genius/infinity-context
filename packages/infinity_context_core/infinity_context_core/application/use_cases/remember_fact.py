"""Remember fact use case."""

from __future__ import annotations

from hashlib import sha256

from infinity_context_core.application.dto import FactResult, RememberFactCommand
from infinity_context_core.application.normalize import scoped_idempotency_key
from infinity_context_core.domain.entities import Confidence, MemoryFact, MemoryFactId
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.domain.taxonomy import DefaultTaxonomyPolicy
from infinity_context_core.ports.auto_memory import MemoryCandidate
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import (
    UnitOfWorkFactoryPort,
    coordinate_fact_source_refs,
)


def remember_fact_fingerprint(command: RememberFactCommand) -> str:
    source_keys = "|".join(
        f"{ref.source_type}:{ref.source_id}:{ref.chunk_id or ''}" for ref in command.source_refs
    )
    raw = (
        f"{command.space_id}:{command.memory_scope_id}:{command.thread_id or ''}:"
        f"{command.kind}:{command.text}:{command.classification}:"
        f"{command.category or ''}:{','.join(command.tags)}:{command.ttl_policy or ''}:"
        f"{command.expires_at.isoformat() if command.expires_at else ''}:{source_keys}"
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
                command.memory_scope_id,
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

            await coordinate_fact_source_refs(
                uow,
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                source_refs=command.source_refs,
            )
            now = self._clock.now()
            taxonomy = DefaultTaxonomyPolicy().normalize(
                MemoryCandidate(
                    text=command.text,
                    kind=command.kind,
                    confidence=Confidence.MEDIUM,
                    source_refs=command.source_refs,
                    safe_reason="direct_remember",
                    category=command.category,
                    tags=command.tags,
                    ttl_policy=command.ttl_policy,
                    expires_at=command.expires_at,
                )
            )
            fact = MemoryFact.create(
                fact_id=MemoryFactId(self._ids.new_id("fact")),
                space_id=command.space_id,
                memory_scope_id=command.memory_scope_id,
                thread_id=command.thread_id,
                text=command.text,
                kind=command.kind,
                source_refs=command.source_refs,
                classification=command.classification,
                category=taxonomy.category,
                tags=taxonomy.tags,
                ttl_policy=taxonomy.ttl_policy.name,
                expires_at=command.expires_at
                or (
                    now + taxonomy.ttl_policy.duration
                    if taxonomy.ttl_policy.duration is not None
                    else None
                ),
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
