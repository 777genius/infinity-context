"""Eligibility checks shared by canonical SQL selection and hydration revalidation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from infinity_context_core.features.memory_facts.domain import (
    FactCurrentness,
    FactEligibilityPolicy,
    FactTemporalExtent,
    FactTemporalQueryMode,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def test_current_selection_uses_half_open_state_interval() -> None:
    policy = FactEligibilityPolicy()
    valid_from = NOW - timedelta(days=1)
    valid_to = NOW + timedelta(days=1)
    fact = _fact(
        temporal=FactTemporalExtent(
            kind="state",
            observed_at=valid_from,
            valid_from=valid_from,
            valid_to=valid_to,
        )
    )

    at_start = policy.assess(
        fact,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=valid_from,
    )
    at_end = policy.assess(
        fact,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=valid_to,
    )

    assert at_start.eligible
    assert at_start.currentness.state is FactCurrentness.CURRENT
    assert not at_end.eligible
    assert at_end.currentness.state is FactCurrentness.HISTORICAL


def test_event_remains_eligible_evidence_after_it_occurred() -> None:
    fact = _fact(
        temporal=FactTemporalExtent(
            kind="event",
            observed_at=NOW,
            occurred_from=NOW - timedelta(days=2),
            occurred_to=NOW - timedelta(days=1),
        )
    )

    assessment = FactEligibilityPolicy().assess(
        fact,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=NOW,
    )

    assert assessment.eligible
    assert assessment.currentness.state is FactCurrentness.HISTORICAL
    assert assessment.reason_codes == ("event_available",)


def test_unknown_state_expired_fact_and_non_active_fact_are_not_current() -> None:
    policy = FactEligibilityPolicy()
    unknown = _fact(
        temporal=FactTemporalExtent(
            kind="state",
            observed_at=NOW - timedelta(days=30),
            basis="migrated_legacy",
            precision="unknown",
        )
    )
    expired = replace(
        _fact(),
        visibility=replace(
            _fact().visibility,
            ttl_policy="short",
            expires_at=NOW,
        ),
    )
    disputed = replace(
        _fact(),
        visibility=replace(_fact().visibility, status="disputed"),
    )

    assert not policy.assess(
        unknown,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=NOW,
    ).eligible
    assert not policy.assess(
        expired,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=NOW,
    ).eligible
    assert not policy.assess(
        disputed,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=NOW,
    ).eligible


def test_history_mode_is_auditable_and_does_not_hide_lifecycle_or_retention() -> None:
    fact = replace(
        _fact(),
        visibility=MemoryFactVisibility(
            status="deleted",
            version=2,
            expires_at=NOW - timedelta(days=1),
        ),
    )

    assessment = FactEligibilityPolicy().assess(
        fact,
        mode=FactTemporalQueryMode.HISTORY,
        reference_time=NOW,
    )

    assert assessment.eligible
    assert assessment.reason_codes == ("history_mode",)


def test_classification_is_fail_closed_in_every_temporal_mode() -> None:
    policy = FactEligibilityPolicy()

    for classification in ("restricted", "Restricted", "vendor-private"):
        fact = replace(
            _fact(),
            visibility=replace(_fact().visibility, classification=classification),
        )
        for mode in FactTemporalQueryMode:
            assessment = policy.assess(fact, mode=mode, reference_time=NOW)
            assert not assessment.eligible
            assert assessment.reason_codes[0].startswith("classification_")


def test_as_of_can_see_superseded_fact_inside_its_old_validity_interval() -> None:
    valid_from = NOW - timedelta(days=30)
    valid_to = NOW - timedelta(days=10)
    fact = replace(
        _fact(
            temporal=FactTemporalExtent(
                kind="state",
                observed_at=valid_from,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        ),
        visibility=MemoryFactVisibility(status="superseded", version=2),
    )

    historical_view = FactEligibilityPolicy().assess(
        fact,
        mode=FactTemporalQueryMode.AS_OF,
        reference_time=valid_from + timedelta(days=1),
    )
    current_view = FactEligibilityPolicy().assess(
        fact,
        mode=FactTemporalQueryMode.CURRENT,
        reference_time=valid_from + timedelta(days=1),
    )

    assert historical_view.eligible
    assert not current_view.eligible


def _fact(*, temporal: FactTemporalExtent | None = None) -> MemoryFactSnapshot:
    observed_at = NOW - timedelta(days=365)
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(
            fact_id="fact-1",
            scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
        ),
        text="Postgres is canonical.",
        source_refs=(MemoryFactSourceRef(source_type="document", source_id="adr-2"),),
        created_at=observed_at,
        updated_at=NOW,
        temporal_extent=temporal
        or FactTemporalExtent(
            kind="timeless",
            observed_at=observed_at,
            basis="primary_evidence",
        ),
    )
