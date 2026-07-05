"""Outbox port owned by the memory_facts feature."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MemoryFactOutboxMessage:
    """Derived-index event intent emitted after a canonical fact change."""

    message_id: str
    event_type: str
    aggregate_id: str
    aggregate_version: int
    occurred_at: datetime | None = None


class MemoryFactOutboxPort(Protocol):
    async def enqueue(self, message: MemoryFactOutboxMessage) -> None:
        """Persist a fact lifecycle outbox message in the current transaction."""


__all__ = ("MemoryFactOutboxMessage", "MemoryFactOutboxPort")
