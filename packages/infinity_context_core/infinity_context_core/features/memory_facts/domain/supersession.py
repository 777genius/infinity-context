"""Pure invariants for replacing one state fact with another."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.memory_facts.domain.fact import MemoryFact
from infinity_context_core.features.memory_facts.domain.temporal_decisions import (
    FactSupersessionRelation,
)
from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactLifecycleStatus,
    FactTemporalKind,
)


@dataclass(frozen=True, slots=True)
class FactSupersessionPolicy:
    """Validate semantic replacement without storage or provider concerns."""

    def validate(
        self,
        *,
        successor: MemoryFact,
        predecessor: MemoryFact,
        effective_at: datetime,
    ) -> None:
        _require_aware(effective_at)
        if successor.identity.fact_id == predecessor.identity.fact_id:
            raise ValueError("Fact cannot supersede itself")
        if successor.identity.scope != predecessor.identity.scope:
            raise ValueError("Supersession cannot cross fact scope")
        if successor.code_scope != predecessor.code_scope:
            raise ValueError("Supersession cannot cross code scope")
        if successor.lifecycle.status is not FactLifecycleStatus.ACTIVE:
            raise ValueError("Supersession successor must be active")
        if predecessor.lifecycle.status is not FactLifecycleStatus.ACTIVE:
            raise ValueError("Supersession predecessor must be active")
        if not successor.epistemic_context.is_automatically_comparable_with(
            predecessor.epistemic_context
        ):
            raise ValueError("Supersession requires comparable epistemic contexts")
        if successor.temporal_extent.kind is not FactTemporalKind.STATE:
            raise ValueError("Supersession successor must be a state fact")
        if predecessor.temporal_extent.kind is not FactTemporalKind.STATE:
            raise ValueError("Supersession predecessor must be a state fact")
        if successor.temporal_extent.valid_from != effective_at:
            raise ValueError("Supersession successor valid_from must equal effective_at")
        predecessor_start = predecessor.temporal_extent.valid_from
        if predecessor_start is None:
            raise ValueError("Supersession predecessor valid_from is unknown")
        if effective_at <= predecessor_start:
            raise ValueError("Supersession must end predecessor after its valid_from")
        predecessor_end = predecessor.temporal_extent.valid_to
        if predecessor_end is not None:
            raise ValueError("Supersession predecessor already has valid_to")

    def validate_graph(
        self,
        *,
        active_relations: tuple[FactSupersessionRelation, ...],
        successor_fact_id: str,
        predecessor_fact_id: str,
    ) -> None:
        if any(
            relation.predecessor_fact_id == predecessor_fact_id for relation in active_relations
        ):
            raise ValueError("Supersession predecessor already has a successor")
        if any(relation.successor_fact_id == successor_fact_id for relation in active_relations):
            raise ValueError("Supersession successor already replaces another fact")
        adjacency = {
            relation.predecessor_fact_id: relation.successor_fact_id
            for relation in active_relations
        }
        adjacency[predecessor_fact_id] = successor_fact_id
        cursor = successor_fact_id
        visited: set[str] = set()
        while cursor in adjacency:
            if cursor in visited:
                raise ValueError("Supersession would create a cycle")
            visited.add(cursor)
            cursor = adjacency[cursor]
        if cursor == predecessor_fact_id:
            raise ValueError("Supersession would create a cycle")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("effective_at must be timezone-aware")


__all__ = ("FactSupersessionPolicy",)
