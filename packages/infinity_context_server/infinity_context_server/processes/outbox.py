"""Server process boundary for outbox event dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimedOutboxJob:
    id: int
    event_type: str
    aggregate_id: str
    aggregate_version: int | None
    attempt_count: int
    workload_class: str
    fairness_key: str | None
    payload_json: dict[str, object]


OutboxEventHandler = Callable[[ClaimedOutboxJob], Awaitable[None]]
OutboxHandlerRegistry = Mapping[str, OutboxEventHandler]


class OutboxEventDispatcher:
    def __init__(self, handlers: OutboxHandlerRegistry) -> None:
        self._handlers = dict(handlers)

    @property
    def event_types(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    async def handle(self, job: ClaimedOutboxJob) -> None:
        handler = self._handlers.get(job.event_type)
        if handler is None:
            raise ValueError(f"Unknown outbox event type: {job.event_type}")
        await handler(job)


def merge_outbox_handlers(*registries: OutboxHandlerRegistry) -> dict[str, OutboxEventHandler]:
    merged: dict[str, OutboxEventHandler] = {}
    for registry in registries:
        for event_type, handler in registry.items():
            if event_type in merged:
                raise ValueError(f"Duplicate outbox event handler: {event_type}")
            merged[event_type] = handler
    return merged
