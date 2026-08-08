"""Behavior checks for the feature-owned MemoryFact aggregate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactEpistemicMode,
    FactFreshness,
    FactLifecycleStatus,
    FactQuality,
    FactRetention,
    FactTemporalExtent,
    FactTemporalKind,
    MemoryFact,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
)

OBSERVED = datetime(2026, 1, 1, tzinfo=UTC)
UPDATED = datetime(2026, 1, 2, tzinfo=UTC)


def test_quality_normalizes_known_values_and_rejects_unknown_values() -> None:
    quality = FactQuality(
        confidence=" HIGH ",
        trust_level="Low",
        classification="Restricted",
    )

    assert quality.confidence == "high"
    assert quality.trust_level == "low"
    assert quality.classification == "restricted"
    with pytest.raises(ValueError, match="Unknown FactClassification"):
        FactQuality(classification="vendor-private")


def test_remember_builds_valid_aggregate_and_round_trips_snapshot() -> None:
    aggregate = replace(
        _remember(),
        code_scope=FactCodeScopeReference(
            repository_id="repo-1",
            code_scope_id="code-scope-1",
        ),
    )

    snapshot = aggregate.to_snapshot()
    restored = MemoryFact.restore(snapshot)

    assert restored == aggregate
    assert aggregate.lifecycle.status is FactLifecycleStatus.ACTIVE
    assert aggregate.revision.value == 1
    assert aggregate.temporal_extent == FactTemporalExtent.ongoing_state(observed_at=OBSERVED)
    assert aggregate.freshness == FactFreshness()
    assert restored.code_scope == aggregate.code_scope


def test_update_increments_revision_and_clears_revision_bound_confirmation() -> None:
    aggregate = _remember().confirm(
        expected_version=1,
        confirmed_at=OBSERVED,
        confirmation_basis="primary_evidence",
        now=OBSERVED,
    )

    updated = aggregate.update(
        expected_version=2,
        text="Postgres remains canonical truth.",
        source_refs=(_source_ref("adr-2"),),
        now=UPDATED,
        kind=aggregate.kind,
        evidence_refs=aggregate.evidence_refs,
        category=aggregate.category,
        tags=("canonical", "postgres"),
    )

    assert updated.revision.value == 3
    assert updated.updated_at == UPDATED
    assert updated.freshness == FactFreshness()


def test_remember_rejects_an_observation_after_transaction_time() -> None:
    with pytest.raises(ValueError, match="observed_at cannot be after transaction time"):
        MemoryFact.remember(
            identity=_identity(),
            text="Postgres is canonical.",
            source_refs=(_source_ref("adr-future"),),
            now=OBSERVED,
            temporal_extent=FactTemporalExtent(
                kind=FactTemporalKind.TIMELESS,
                observed_at=UPDATED,
            ),
        )


def test_content_update_cannot_resurrect_a_disputed_fact() -> None:
    disputed = _remember().dispute(expected_version=1, now=UPDATED)

    with pytest.raises(ValueError, match="Only an active memory fact"):
        disputed.update(
            expected_version=2,
            text="Postgres remains canonical truth.",
            source_refs=(_source_ref("adr-3"),),
            now=UPDATED + timedelta(days=1),
            kind=disputed.kind,
            evidence_refs=disputed.evidence_refs,
            category=disputed.category,
            tags=disputed.tags,
        )


def test_confirmation_time_cannot_be_future_or_move_backwards() -> None:
    with pytest.raises(ValueError, match="after transaction time"):
        MemoryFact.remember(
            identity=_identity(),
            text="Postgres is canonical.",
            source_refs=(_source_ref("adr-2"),),
            now=OBSERVED,
            freshness=FactFreshness(
                last_confirmed_at=UPDATED,
                confirmation_basis="future_evidence",
            ),
        )

    confirmed = _remember().confirm(
        expected_version=1,
        confirmed_at=UPDATED,
        confirmation_basis="primary_evidence",
        now=UPDATED,
    )
    with pytest.raises(ValueError, match="cannot move backwards"):
        confirmed.confirm(
            expected_version=2,
            confirmed_at=OBSERVED,
            confirmation_basis="older_evidence",
            now=UPDATED + timedelta(days=1),
        )


def test_forget_changes_lifecycle_but_preserves_temporal_history() -> None:
    aggregate = _remember()

    forgotten = aggregate.forget(expected_version=1, now=UPDATED)

    assert forgotten.lifecycle.status is FactLifecycleStatus.DELETED
    assert forgotten.revision.value == 2
    assert forgotten.temporal_extent == aggregate.temporal_extent
    assert forgotten.source_refs == aggregate.source_refs


def test_attach_evidence_preserves_truth_temporal_and_confirmation_semantics() -> None:
    confirmed = _remember().confirm(
        expected_version=1,
        confirmed_at=OBSERVED,
        confirmation_basis="primary_evidence",
        now=OBSERVED,
    )
    source = _source_ref("adr-3")

    enriched = confirmed.attach_evidence(
        expected_version=2,
        source_refs=(source,),
        evidence_refs=(MemoryFactEvidenceRef(source_ref=source),),
        now=UPDATED,
    )

    assert enriched.text == confirmed.text
    assert enriched.lifecycle == confirmed.lifecycle
    assert enriched.temporal_extent == confirmed.temporal_extent
    assert enriched.freshness == confirmed.freshness
    assert enriched.quality == confirmed.quality
    assert enriched.revision.value == 3
    assert enriched.source_refs == (*confirmed.source_refs, source)


def test_event_timeless_and_state_intervals_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="Event fact cannot define state validity"):
        FactTemporalExtent(
            kind=FactTemporalKind.EVENT,
            observed_at=OBSERVED,
            valid_from=OBSERVED,
            occurred_from=OBSERVED,
        )

    with pytest.raises(ValueError, match="Timeless fact cannot define"):
        FactTemporalExtent(
            kind=FactTemporalKind.TIMELESS,
            observed_at=OBSERVED,
            valid_to=UPDATED,
        )

    with pytest.raises(ValueError, match="validity end must be after start"):
        FactTemporalExtent(
            kind=FactTemporalKind.STATE,
            observed_at=OBSERVED,
            valid_from=UPDATED,
            valid_to=OBSERVED,
        )


def test_perspectives_are_comparable_only_for_the_same_subject() -> None:
    ada = FactEpistemicContext(
        mode=FactEpistemicMode.PERSPECTIVE,
        perspective_subject="ada",
    )
    another_ada_claim = FactEpistemicContext(
        mode=FactEpistemicMode.PERSPECTIVE,
        perspective_subject="ada",
    )
    bob = FactEpistemicContext(
        mode=FactEpistemicMode.PERSPECTIVE,
        perspective_subject="bob",
    )
    hypothesis = FactEpistemicContext(mode=FactEpistemicMode.HYPOTHESIS)

    assert ada.is_automatically_comparable_with(another_ada_claim)
    assert not ada.is_automatically_comparable_with(bob)
    assert not ada.is_automatically_comparable_with(hypothesis)


def test_retention_is_independent_from_temporal_validity() -> None:
    retention = FactRetention(
        ttl_policy="short",
        context_expires_at=UPDATED,
        purge_after=UPDATED + timedelta(days=30),
    )

    assert retention.is_context_visible_at(OBSERVED)
    assert not retention.is_context_visible_at(UPDATED)
    assert _remember().temporal_extent.valid_to is None


def test_aggregate_rejects_missing_evidence_and_naive_transaction_time() -> None:
    with pytest.raises(ValueError, match="source_refs are required"):
        MemoryFact.remember(
            identity=_identity(),
            text="Postgres is canonical.",
            source_refs=(),
            now=OBSERVED,
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        MemoryFact.remember(
            identity=_identity(),
            text="Postgres is canonical.",
            source_refs=(_source_ref("adr-2"),),
            now=datetime(2026, 1, 1),
        )


def _remember() -> MemoryFact:
    return MemoryFact.remember(
        identity=_identity(),
        text="Postgres is the canonical lifecycle store.",
        source_refs=(_source_ref("adr-2"),),
        now=OBSERVED,
        kind="architecture_decision",
        category="architecture",
        tags=("canonical",),
    )


def _identity() -> MemoryFactIdentity:
    return MemoryFactIdentity(
        fact_id="fact-1",
        scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
    )


def _source_ref(source_id: str) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(source_type="document", source_id=source_id)
