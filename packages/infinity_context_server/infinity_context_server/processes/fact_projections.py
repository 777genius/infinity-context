"""Composite fan-out for canonical fact changes and legacy migration events."""

from __future__ import annotations

from infinity_context_server.processes.fact_cognitive_invalidation import (
    FactCognitiveInvalidationOutboxProcess,
)
from infinity_context_server.processes.outbox import (
    ClaimedOutboxJob,
    OutboxHandlerRegistry,
)
from infinity_context_server.processes.projections import ProjectionOutboxProcess

_CANONICAL_FACT_EVENTS = (
    "fact.created",
    "fact.updated",
    "fact.deleted",
    "fact.disputed",
    "fact.superseded",
    "fact.confirmed",
    "fact.temporal_ended",
)


class FactProjectionOutboxProcess:
    """Fan one durable fact change out to every derived-memory subscriber."""

    def __init__(self, container) -> None:
        self._cognitive = FactCognitiveInvalidationOutboxProcess(container)
        self._projections = ProjectionOutboxProcess(container)

    def handlers(self) -> OutboxHandlerRegistry:
        return {
            **self.legacy_handlers(),
            **self.canonical_handlers(),
        }

    def legacy_handlers(self) -> OutboxHandlerRegistry:
        return {
            "graph.upsert_fact": self.handle_legacy_upsert,
            "graph.delete_fact": self.handle_legacy_delete,
        }

    def canonical_handlers(self) -> OutboxHandlerRegistry:
        return {event_type: self.handle_canonical_change for event_type in _CANONICAL_FACT_EVENTS}

    async def handle_canonical_change(self, job: ClaimedOutboxJob) -> None:
        await self._cognitive.handle_fact_changed(job)
        await self._projections.handle_graph_upsert(job)

    async def handle_legacy_upsert(self, job: ClaimedOutboxJob) -> None:
        await self._cognitive.handle_fact_changed(job)
        await self._projections.handle_graph_upsert(job)

    async def handle_legacy_delete(self, job: ClaimedOutboxJob) -> None:
        await self._cognitive.handle_fact_changed(job)
        await self._projections.handle_graph_delete(job)


__all__ = ("FactProjectionOutboxProcess",)
