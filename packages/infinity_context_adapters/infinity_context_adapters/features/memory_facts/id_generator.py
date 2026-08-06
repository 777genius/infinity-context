"""Feature-owned identifier adapter over an injected opaque-id factory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infinity_context_core.features.memory_facts.public import MemoryFactIdPort


@dataclass(frozen=True, slots=True)
class MemoryFactIdAdapter:
    factory: Callable[[str], str]

    def new_fact_id(self) -> str:
        return self.factory("fact")

    def new_outbox_message_id(self) -> str:
        return self.factory("outbox")

    def new_tombstone_id(self) -> str:
        return self.factory("tombstone")

    def new_temporal_decision_id(self) -> str:
        return self.factory("temporal-decision")

    def new_fact_relation_id(self) -> str:
        return self.factory("fact-relation")


def create_memory_fact_id_adapter(factory: Callable[[str], str]) -> MemoryFactIdPort:
    return MemoryFactIdAdapter(factory=factory)


__all__ = ("MemoryFactIdAdapter", "create_memory_fact_id_adapter")
