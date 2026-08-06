"""Deterministic currentness assessment for memory facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactFreshness,
    FactTemporalExtent,
    FactTemporalKind,
)


class FactCurrentness(StrEnum):
    CURRENT = "current"
    FUTURE = "future"
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


class FactTemporalAssurance(StrEnum):
    CONFIRMED = "confirmed"
    ASSERTED = "asserted"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FactCurrentnessAssessment:
    state: FactCurrentness
    temporal_kind: FactTemporalKind
    reference_time: datetime
    assurance: FactTemporalAssurance
    reason_codes: tuple[str, ...]
    next_boundary_at: datetime | None = None


class FactCurrentnessPolicy:
    """Pure valid-time policy; persistence and ranking are deliberately absent."""

    def assess(
        self,
        extent: FactTemporalExtent,
        *,
        reference_time: datetime,
        freshness: FactFreshness | None = None,
    ) -> FactCurrentnessAssessment:
        _require_aware(reference_time)
        assurance = _assurance(
            extent.basis,
            freshness=freshness,
            reference_time=reference_time,
        )

        if extent.kind is FactTemporalKind.TIMELESS:
            return FactCurrentnessAssessment(
                state=FactCurrentness.CURRENT,
                temporal_kind=extent.kind,
                reference_time=reference_time,
                assurance=assurance,
                reason_codes=("timeless_claim",),
            )

        if extent.kind is FactTemporalKind.EVENT:
            return _assess_event(extent, reference_time, assurance)

        return _assess_state(extent, reference_time, assurance)


def _assess_state(
    extent: FactTemporalExtent,
    reference_time: datetime,
    assurance: FactTemporalAssurance,
) -> FactCurrentnessAssessment:
    if extent.valid_from is None:
        return FactCurrentnessAssessment(
            state=FactCurrentness.UNKNOWN,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=FactTemporalAssurance.UNKNOWN,
            reason_codes=("valid_from_unknown",),
            next_boundary_at=extent.valid_to,
        )
    if reference_time < extent.valid_from:
        return FactCurrentnessAssessment(
            state=FactCurrentness.FUTURE,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=assurance,
            reason_codes=("before_valid_from",),
            next_boundary_at=extent.valid_from,
        )
    if extent.valid_to is not None and reference_time >= extent.valid_to:
        return FactCurrentnessAssessment(
            state=FactCurrentness.HISTORICAL,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=assurance,
            reason_codes=("at_or_after_valid_to",),
        )
    return FactCurrentnessAssessment(
        state=FactCurrentness.CURRENT,
        temporal_kind=extent.kind,
        reference_time=reference_time,
        assurance=assurance,
        reason_codes=("inside_validity_interval",),
        next_boundary_at=extent.valid_to,
    )


def _assess_event(
    extent: FactTemporalExtent,
    reference_time: datetime,
    assurance: FactTemporalAssurance,
) -> FactCurrentnessAssessment:
    if extent.occurred_from is None:
        return FactCurrentnessAssessment(
            state=FactCurrentness.UNKNOWN,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=FactTemporalAssurance.UNKNOWN,
            reason_codes=("occurred_from_unknown",),
        )
    if reference_time < extent.occurred_from:
        return FactCurrentnessAssessment(
            state=FactCurrentness.FUTURE,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=assurance,
            reason_codes=("before_event",),
            next_boundary_at=extent.occurred_from,
        )
    if extent.occurred_to is not None and reference_time < extent.occurred_to:
        return FactCurrentnessAssessment(
            state=FactCurrentness.CURRENT,
            temporal_kind=extent.kind,
            reference_time=reference_time,
            assurance=assurance,
            reason_codes=("during_event",),
            next_boundary_at=extent.occurred_to,
        )
    return FactCurrentnessAssessment(
        state=FactCurrentness.HISTORICAL,
        temporal_kind=extent.kind,
        reference_time=reference_time,
        assurance=assurance,
        reason_codes=("event_occurred",),
    )


def _assurance(
    basis: str,
    *,
    freshness: FactFreshness | None,
    reference_time: datetime,
) -> FactTemporalAssurance:
    if (
        freshness is not None
        and freshness.last_confirmed_at is not None
        and freshness.last_confirmed_at <= reference_time
    ):
        return FactTemporalAssurance.CONFIRMED
    normalized = basis.strip().casefold()
    if normalized in {"asserted", "explicit_source", "primary_evidence", "system_event"}:
        return FactTemporalAssurance.ASSERTED
    if normalized in {"inferred", "extracted"}:
        return FactTemporalAssurance.INFERRED
    return FactTemporalAssurance.UNKNOWN


def _require_aware(reference_time: datetime) -> None:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("reference_time must be timezone-aware")


__all__ = (
    "FactCurrentness",
    "FactCurrentnessAssessment",
    "FactCurrentnessPolicy",
    "FactTemporalAssurance",
)
