"""Temporal query and prompt-eligibility policy for canonical facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from infinity_context_core.features.memory_facts.domain.fact import MemoryFactSnapshot
from infinity_context_core.features.memory_facts.domain.temporal import (
    FactCurrentness,
    FactCurrentnessAssessment,
    FactCurrentnessPolicy,
)
from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactClassification,
    FactLifecycleStatus,
    FactRetention,
    FactTemporalKind,
)


class FactTemporalQueryMode(StrEnum):
    CURRENT = "current"
    AS_OF = "as_of"
    HISTORY = "history"


@dataclass(frozen=True, slots=True)
class MemoryFactSelectionQuery:
    """Canonical temporal selection before relevance ranking."""

    space_id: str
    memory_scope_ids: tuple[str, ...]
    temporal_mode: FactTemporalQueryMode
    reference_time: datetime
    limit: int
    thread_id: str | None = None
    repository_id: str | None = None
    code_scope_id: str | None = None
    fact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "temporal_mode", FactTemporalQueryMode(self.temporal_mode))
        if not self.space_id.strip():
            raise ValueError("Fact selection requires space_id")
        if not self.memory_scope_ids or any(
            not memory_scope_id.strip() for memory_scope_id in self.memory_scope_ids
        ):
            raise ValueError("Fact selection requires non-blank memory_scope_ids")
        if len(set(self.memory_scope_ids)) != len(self.memory_scope_ids):
            raise ValueError("Fact selection memory_scope_ids must be unique")
        if self.thread_id is not None and not self.thread_id.strip():
            raise ValueError("Fact selection thread_id cannot be blank")
        if self.repository_id is not None and not self.repository_id.strip():
            raise ValueError("Fact selection repository_id cannot be blank")
        if self.code_scope_id is not None:
            if not self.code_scope_id.strip():
                raise ValueError("Fact selection code_scope_id cannot be blank")
            if self.repository_id is None:
                raise ValueError("Fact selection code_scope_id requires repository_id")
        if any(not fact_id.strip() for fact_id in self.fact_ids):
            raise ValueError("Fact selection fact_ids cannot contain blanks")
        if len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("Fact selection fact_ids must be unique")
        if self.limit < 1:
            raise ValueError("Fact selection limit must be positive")
        _require_aware(self.reference_time)


@dataclass(frozen=True, slots=True)
class FactEligibilityAssessment:
    eligible: bool
    currentness: FactCurrentnessAssessment
    reason_codes: tuple[str, ...]


class FactEligibilityPolicy:
    """Combine lifecycle, temporal and retention without ranking or storage concerns."""

    def __init__(self, currentness: FactCurrentnessPolicy | None = None) -> None:
        self._currentness = currentness or FactCurrentnessPolicy()

    def assess(
        self,
        fact: MemoryFactSnapshot,
        *,
        mode: FactTemporalQueryMode,
        reference_time: datetime,
    ) -> FactEligibilityAssessment:
        if fact.temporal_extent is None:
            raise ValueError("Canonical fact selection requires temporal_extent")
        mode = FactTemporalQueryMode(mode)
        currentness = self._currentness.assess(
            fact.temporal_extent,
            reference_time=reference_time,
            freshness=fact.freshness,
        )
        lifecycle = FactLifecycleStatus(fact.visibility.status)

        # Selection is the canonical trust boundary for every retrieval adapter.
        # Provider filters are only an optimization and must never grant disclosure.
        try:
            classification = FactClassification(fact.visibility.classification)
        except ValueError:
            classification = FactClassification.UNKNOWN
        if not classification.prompt_visible:
            return FactEligibilityAssessment(
                eligible=False,
                currentness=currentness,
                reason_codes=(f"classification_{classification.value}",),
            )

        if mode is FactTemporalQueryMode.HISTORY:
            return FactEligibilityAssessment(
                eligible=True,
                currentness=currentness,
                reason_codes=("history_mode",),
            )
        allowed_lifecycle = (
            {FactLifecycleStatus.ACTIVE, FactLifecycleStatus.SUPERSEDED}
            if mode is FactTemporalQueryMode.AS_OF
            else {FactLifecycleStatus.ACTIVE}
        )
        if lifecycle not in allowed_lifecycle:
            return FactEligibilityAssessment(
                eligible=False,
                currentness=currentness,
                reason_codes=(f"lifecycle_{lifecycle.value}",),
            )
        retention = FactRetention(
            ttl_policy=fact.visibility.ttl_policy,
            context_expires_at=fact.visibility.expires_at,
            purge_after=fact.purge_after,
        )
        if not retention.is_context_visible_at(reference_time):
            return FactEligibilityAssessment(
                eligible=False,
                currentness=currentness,
                reason_codes=("context_expired",),
            )

        temporal_kind = fact.temporal_extent.kind
        if temporal_kind is FactTemporalKind.EVENT:
            eligible = currentness.state is not FactCurrentness.FUTURE
            reason = "event_available" if eligible else "event_not_occurred"
        else:
            eligible = currentness.state is FactCurrentness.CURRENT
            reason = "temporally_current" if eligible else f"temporal_{currentness.state.value}"
        return FactEligibilityAssessment(
            eligible=eligible,
            currentness=currentness,
            reason_codes=(reason,),
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Fact selection reference_time must be timezone-aware")


__all__ = (
    "FactEligibilityAssessment",
    "FactEligibilityPolicy",
    "FactTemporalQueryMode",
    "MemoryFactSelectionQuery",
)
