"""Identifier port owned by the memory_facts feature."""

from __future__ import annotations

from typing import Protocol


class MemoryFactIdPort(Protocol):
    def new_fact_id(self) -> str:
        """Return a new canonical fact id."""

    def new_outbox_message_id(self) -> str:
        """Return a new outbox message id for a fact lifecycle event."""

    def new_tombstone_id(self) -> str:
        """Return a new tombstone id for a forget operation."""


__all__ = ("MemoryFactIdPort",)
