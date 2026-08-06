"""Server composition for canonical-fact cognitive invalidation events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from infinity_context_adapters.features.cognitive_memory import (
    PostgresCognitiveProjectionStore,
)
from infinity_context_adapters.features.memory_facts import PostgresMemoryFactStore
from infinity_context_adapters.postgres import build_session_factory
from infinity_context_core.features.memory_facts.public import (
    MemoryFactOutboxMessage,
    MemoryFactScope,
)
from infinity_context_core.processes.fact_cognitive_invalidation import (
    FactCognitiveInvalidationProcess,
)

from infinity_context_server.processes.outbox import ClaimedOutboxJob, OutboxHandlerRegistry

if TYPE_CHECKING:
    from infinity_context_server.composition import Container

_FACT_CHANGE_EVENTS = (
    "fact.created",
    "fact.updated",
    "fact.deleted",
    "fact.disputed",
    "fact.superseded",
    "fact.confirmed",
    "fact.temporal_ended",
)


class FactCognitiveInvalidationOutboxProcess:
    """Invalidate version-bound cognition without teaching core about SQLAlchemy."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def handlers(self) -> OutboxHandlerRegistry:
        return {event_type: self.handle_fact_changed for event_type in _FACT_CHANGE_EVENTS}

    async def handle_fact_changed(self, job: ClaimedOutboxJob) -> None:
        payload = await self._scope_enriched_payload(job)
        version = job.aggregate_version or _required_int(payload, "version")
        session_factory = build_session_factory(self._container.engine)
        async with session_factory() as session:
            process = FactCognitiveInvalidationProcess(
                facts=PostgresMemoryFactStore(session),
                projections=PostgresCognitiveProjectionStore(session),
            )
            await process.handle(
                MemoryFactOutboxMessage(
                    message_id=str(payload.get("message_id") or f"outbox:{job.id}"),
                    event_type=job.event_type,
                    aggregate_id=job.aggregate_id,
                    aggregate_version=version,
                    scope=MemoryFactScope(
                        space_id=_required_string(payload, "space_id"),
                        memory_scope_id=_required_string(payload, "memory_scope_id"),
                        thread_id=_optional_string(payload.get("thread_id")),
                    ),
                    occurred_at=_optional_datetime(payload.get("occurred_at")),
                )
            )
            await session.commit()

    async def _scope_enriched_payload(
        self,
        job: ClaimedOutboxJob,
    ) -> dict[str, object]:
        payload = dict(job.payload_json)
        if payload.get("space_id") and payload.get("memory_scope_id"):
            return payload
        async with self._container.uow_factory() as uow:
            fact = await uow.facts.get_by_id(job.aggregate_id)
        if fact is None:
            raise ValueError("Fact outbox payload cannot resolve canonical scope")
        payload.update(
            {
                "space_id": str(fact.space_id),
                "memory_scope_id": str(fact.memory_scope_id),
                "thread_id": str(fact.thread_id) if fact.thread_id else None,
                "version": job.aggregate_version or fact.version,
            }
        )
        return payload


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Fact outbox payload requires {key}")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"Fact outbox payload requires positive {key}")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Fact outbox thread_id must be a non-blank string")
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Fact outbox occurred_at must be an ISO datetime")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Fact outbox occurred_at must be timezone-aware")
    return parsed


__all__ = ("FactCognitiveInvalidationOutboxProcess",)
