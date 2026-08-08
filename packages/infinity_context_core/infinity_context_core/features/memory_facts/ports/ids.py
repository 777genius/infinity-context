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

    def new_temporal_decision_id(self) -> str:
        """Return a new append-only temporal decision id."""

    def new_fact_relation_id(self) -> str:
        """Return a new high-impact fact relation id."""


__all__ = ("MemoryFactIdPort",)
