"""Question-only requirements for bounded paired evidence reservation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from infinity_context_core.application.context_query_state_transition import (
    state_transition_requires_pair,
)
from infinity_context_core.application.context_temporal_intent_policy import (
    temporal_ordering_intent,
)
from infinity_context_core.application.context_temporal_interval_requirements import (
    temporal_interval_requirements,
)

_MAX_ROLES = 2


class PairedEvidenceKind(StrEnum):
    """A bounded question shape with exactly two independently useful roles."""

    TEMPORAL_INTERVAL = "temporal_interval"
    TEMPORAL_ORDERING = "temporal_ordering"
    STATE_TRANSITION = "state_transition"


@dataclass(frozen=True, slots=True)
class PairedEvidenceRequirement:
    """Two roles derived only from explicit question semantics."""

    kind: PairedEvidenceKind
    role_ids: tuple[str, str]
    retrieval_reasons: tuple[str | None, str | None]
    role_queries: tuple[str, str]

    @property
    def uses_typed_retrieval_reasons(self) -> bool:
        return all(reason is not None for reason in self.retrieval_reasons)


def paired_evidence_requirement(query: str) -> PairedEvidenceRequirement | None:
    """Return a requirement only for explicit, safely bounded pair requests."""

    interval = temporal_interval_requirements(query)
    if len(interval.endpoints) == _MAX_ROLES:
        return PairedEvidenceRequirement(
            kind=PairedEvidenceKind.TEMPORAL_INTERVAL,
            role_ids=("interval_start", "interval_end"),
            retrieval_reasons=tuple(endpoint.slot_id for endpoint in interval.endpoints),
            role_queries=tuple(endpoint.query for endpoint in interval.endpoints),
        )

    ordering = temporal_ordering_intent(query)
    if len(ordering.endpoints) == _MAX_ROLES:
        return PairedEvidenceRequirement(
            kind=PairedEvidenceKind.TEMPORAL_ORDERING,
            role_ids=("ordering_first", "ordering_second"),
            retrieval_reasons=tuple(endpoint.slot_id for endpoint in ordering.endpoints),
            role_queries=tuple(endpoint.query for endpoint in ordering.endpoints),
        )

    if state_transition_requires_pair(query):
        return PairedEvidenceRequirement(
            kind=PairedEvidenceKind.STATE_TRANSITION,
            role_ids=("previous_state", "current_state"),
            retrieval_reasons=(None, None),
            role_queries=(query, query),
        )
    return None


__all__ = (
    "PairedEvidenceKind",
    "PairedEvidenceRequirement",
    "paired_evidence_requirement",
)
