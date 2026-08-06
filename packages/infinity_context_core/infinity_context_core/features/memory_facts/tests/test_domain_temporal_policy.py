"""Boundary checks for deterministic fact currentness."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from infinity_context_core.features.memory_facts.domain import (
    FactCurrentness,
    FactCurrentnessPolicy,
    FactFreshness,
    FactTemporalAssurance,
    FactTemporalExtent,
    FactTemporalKind,
)

START = datetime(2026, 1, 10, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)


def test_state_interval_is_half_open_and_reports_next_boundary() -> None:
    policy = FactCurrentnessPolicy()
    extent = FactTemporalExtent(
        kind=FactTemporalKind.STATE,
        observed_at=START,
        valid_from=START,
        valid_to=END,
        basis="explicit_source",
    )

    before = policy.assess(extent, reference_time=datetime(2026, 1, 1, tzinfo=UTC))
    at_start = policy.assess(extent, reference_time=START)
    at_end = policy.assess(extent, reference_time=END)

    assert before.state is FactCurrentness.FUTURE
    assert before.next_boundary_at == START
    assert at_start.state is FactCurrentness.CURRENT
    assert at_start.next_boundary_at == END
    assert at_end.state is FactCurrentness.HISTORICAL
    assert at_start.assurance is FactTemporalAssurance.ASSERTED


def test_state_without_valid_from_is_unknown_not_invented_current() -> None:
    assessment = FactCurrentnessPolicy().assess(
        FactTemporalExtent(
            kind=FactTemporalKind.STATE,
            observed_at=START,
            basis="migrated_legacy",
        ),
        reference_time=END,
    )

    assert assessment.state is FactCurrentness.UNKNOWN
    assert assessment.assurance is FactTemporalAssurance.UNKNOWN
    assert assessment.reason_codes == ("valid_from_unknown",)


def test_old_timeless_fact_stays_current_regardless_of_age() -> None:
    assessment = FactCurrentnessPolicy().assess(
        FactTemporalExtent(
            kind=FactTemporalKind.TIMELESS,
            observed_at=datetime(2000, 1, 1, tzinfo=UTC),
            basis="primary_evidence",
        ),
        reference_time=END,
    )

    assert assessment.state is FactCurrentness.CURRENT
    assert assessment.assurance is FactTemporalAssurance.ASSERTED
    assert assessment.reason_codes == ("timeless_claim",)


def test_confirmed_assurance_requires_explicit_confirmation_not_basis_string() -> None:
    extent = FactTemporalExtent.ongoing_state(
        observed_at=START,
        basis="confirmed",
    )
    policy = FactCurrentnessPolicy()

    unaudited = policy.assess(extent, reference_time=END)
    confirmed = policy.assess(
        extent,
        reference_time=END,
        freshness=FactFreshness(
            last_confirmed_at=START,
            confirmation_basis="manual_review",
        ),
    )
    before_confirmation = policy.assess(
        extent,
        reference_time=datetime(2026, 1, 5, tzinfo=UTC),
        freshness=FactFreshness(
            last_confirmed_at=START,
            confirmation_basis="manual_review",
        ),
    )

    assert unaudited.assurance is FactTemporalAssurance.UNKNOWN
    assert confirmed.assurance is FactTemporalAssurance.CONFIRMED
    assert before_confirmation.assurance is FactTemporalAssurance.UNKNOWN


def test_finished_event_is_historical_but_keeps_event_reason() -> None:
    assessment = FactCurrentnessPolicy().assess(
        FactTemporalExtent(
            kind=FactTemporalKind.EVENT,
            observed_at=START,
            occurred_from=START,
            occurred_to=END,
            basis="system_event",
        ),
        reference_time=datetime(2026, 3, 1, tzinfo=UTC),
    )

    assert assessment.state is FactCurrentness.HISTORICAL
    assert assessment.temporal_kind is FactTemporalKind.EVENT
    assert assessment.reason_codes == ("event_occurred",)


def test_policy_rejects_naive_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FactCurrentnessPolicy().assess(
            FactTemporalExtent.ongoing_state(observed_at=START),
            reference_time=datetime(2026, 1, 11),
        )
