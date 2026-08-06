"""Provider-neutral fact event construction shared by lifecycle handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from infinity_context_core.features.memory_facts.domain import MemoryFactSnapshot
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactIdPort,
    MemoryFactOutboxMessage,
)

FACT_CREATED_EVENT: Final = "fact.created"
FACT_UPDATED_EVENT: Final = "fact.updated"
FACT_DELETED_EVENT: Final = "fact.deleted"
FACT_DISPUTED_EVENT: Final = "fact.disputed"
FACT_SUPERSEDED_EVENT: Final = "fact.superseded"
FACT_CONFIRMED_EVENT: Final = "fact.confirmed"
FACT_TEMPORAL_ENDED_EVENT: Final = "fact.temporal_ended"


def new_fact_outbox_message(
    *,
    ids: MemoryFactIdPort,
    fact: MemoryFactSnapshot,
    event_type: str,
    occurred_at: datetime,
) -> MemoryFactOutboxMessage:
    return MemoryFactOutboxMessage(
        message_id=ids.new_outbox_message_id(),
        event_type=event_type,
        aggregate_id=fact.identity.fact_id,
        aggregate_version=fact.visibility.version,
        scope=fact.identity.scope,
        occurred_at=occurred_at,
    )


__all__ = (
    "FACT_CREATED_EVENT",
    "FACT_CONFIRMED_EVENT",
    "FACT_DELETED_EVENT",
    "FACT_DISPUTED_EVENT",
    "FACT_SUPERSEDED_EVENT",
    "FACT_TEMPORAL_ENDED_EVENT",
    "FACT_UPDATED_EVENT",
    "new_fact_outbox_message",
)
