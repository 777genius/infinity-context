"""Append-only decisions that explain semantic changes to canonical facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from infinity_context_core.features.memory_facts.domain.fact import (
    MemoryFactEvidenceRef,
    MemoryFactScope,
)


class FactTemporalDecisionType(StrEnum):
    SUPERSEDE = "supersede"
    TEMPORAL_END = "temporal_end"
    CONFIRM = "confirm"
    DISPUTE = "dispute"
    REINSTATE = "reinstate"
    KEEP_BOTH = "keep_both"


@dataclass(frozen=True, slots=True)
class FactTemporalDecision:
    """Immutable audit record; facts remain the only mutable canonical aggregate."""

    decision_id: str
    decision_type: FactTemporalDecisionType
    scope: MemoryFactScope
    source_fact_id: str
    source_fact_version: int
    target_fact_id: str | None
    target_fact_version: int | None
    effective_at: datetime
    evidence_refs: tuple[MemoryFactEvidenceRef, ...]
    actor_id: str
    policy_version: str
    reason_code: str
    applied_at: datetime
    idempotency_key: str
    compensates_decision_id: str | None = None
    outbox_message_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_type",
            FactTemporalDecisionType(self.decision_type),
        )
        for field_name in (
            "decision_id",
            "source_fact_id",
            "actor_id",
            "policy_version",
            "reason_code",
            "idempotency_key",
        ):
            _require_non_blank(field_name, getattr(self, field_name))
        if len(self.idempotency_key) > 160:
            raise ValueError("idempotency_key exceeds 160 characters")
        if self.target_fact_id is not None:
            _require_non_blank("target_fact_id", self.target_fact_id)
        if (self.target_fact_id is None) != (self.target_fact_version is None):
            raise ValueError("Temporal decision target id and version must be provided together")
        two_fact_decisions = {
            FactTemporalDecisionType.SUPERSEDE,
            FactTemporalDecisionType.DISPUTE,
            FactTemporalDecisionType.REINSTATE,
            FactTemporalDecisionType.KEEP_BOTH,
        }
        if (self.decision_type in two_fact_decisions) != (self.target_fact_id is not None):
            raise ValueError("Temporal decision target does not match decision type")
        if self.source_fact_id == self.target_fact_id:
            raise ValueError("Temporal decision source and target must differ")
        if self.source_fact_version < 1 or (
            self.target_fact_version is not None and self.target_fact_version < 1
        ):
            raise ValueError("Temporal decision fact versions must be positive")
        if not self.evidence_refs:
            raise ValueError("Temporal decision requires evidence_refs")
        _require_aware("effective_at", self.effective_at)
        _require_aware("applied_at", self.applied_at)
        if self.applied_at < self.effective_at and self.decision_type not in {
            FactTemporalDecisionType.SUPERSEDE,
            FactTemporalDecisionType.TEMPORAL_END,
        }:
            raise ValueError("Only temporal boundary decisions may be scheduled")
        if self.compensates_decision_id is not None:
            _require_non_blank("compensates_decision_id", self.compensates_decision_id)
        if any(not message_id.strip() for message_id in self.outbox_message_ids):
            raise ValueError("Temporal decision outbox ids cannot contain blanks")


@dataclass(frozen=True, slots=True)
class FactSupersessionRelation:
    """Immutable high-impact relation created with its audit decision."""

    relation_id: str
    scope: MemoryFactScope
    successor_fact_id: str
    successor_fact_version: int
    predecessor_fact_id: str
    predecessor_fact_version: int
    effective_at: datetime
    decision_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "relation_id",
            "successor_fact_id",
            "predecessor_fact_id",
            "decision_id",
        ):
            _require_non_blank(field_name, getattr(self, field_name))
        if self.successor_fact_id == self.predecessor_fact_id:
            raise ValueError("Fact cannot supersede itself")
        if self.successor_fact_version < 1 or self.predecessor_fact_version < 1:
            raise ValueError("Supersession fact versions must be positive")
        _require_aware("effective_at", self.effective_at)
        _require_aware("created_at", self.created_at)


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_non_blank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


__all__ = (
    "FactSupersessionRelation",
    "FactTemporalDecision",
    "FactTemporalDecisionType",
)
