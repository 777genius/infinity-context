"""Domain checks for safe semantic replacement."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactEpistemicMode,
    FactSupersessionPolicy,
    FactTemporalExtent,
    MemoryFact,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
)

NOW = datetime(2026, 5, 1, tzinfo=UTC)
EARLIER = NOW - timedelta(days=30)


def test_supersession_requires_same_scope_comparable_state_claims() -> None:
    policy = FactSupersessionPolicy()
    predecessor = _fact("old", valid_from=EARLIER)
    successor = _fact("new", valid_from=NOW)

    policy.validate(
        successor=successor,
        predecessor=predecessor,
        effective_at=NOW,
    )

    cross_scope = replace(
        successor,
        identity=MemoryFactIdentity(
            fact_id="new",
            scope=MemoryFactScope(space_id="space-2", memory_scope_id="scope-1"),
        ),
    )
    with pytest.raises(ValueError, match="cannot cross fact scope"):
        policy.validate(
            successor=cross_scope,
            predecessor=predecessor,
            effective_at=NOW,
        )


def test_hypothesis_cannot_automatically_supersede_world_claim() -> None:
    hypothesis = replace(
        _fact("new", valid_from=NOW),
        epistemic_context=FactEpistemicContext(mode=FactEpistemicMode.HYPOTHESIS),
    )

    with pytest.raises(ValueError, match="comparable epistemic contexts"):
        FactSupersessionPolicy().validate(
            successor=hypothesis,
            predecessor=_fact("old", valid_from=EARLIER),
            effective_at=NOW,
        )


def test_supersession_rejects_cross_repository_or_branch_replacement() -> None:
    predecessor = replace(
        _fact("old", valid_from=EARLIER),
        code_scope=FactCodeScopeReference("repo-1", "branch-main"),
    )
    successor = replace(
        _fact("new", valid_from=NOW),
        code_scope=FactCodeScopeReference("repo-2", "branch-main"),
    )

    with pytest.raises(ValueError, match="cross code scope"):
        FactSupersessionPolicy().validate(
            successor=successor,
            predecessor=predecessor,
            effective_at=NOW,
        )


def test_supersession_mutations_share_revision_clock_and_do_not_confirm_facts() -> None:
    predecessor = _fact("old", valid_from=EARLIER)
    successor = _fact("new", valid_from=NOW)

    changed_successor = successor.record_as_supersession_successor(
        expected_version=1,
        effective_at=NOW,
        now=NOW,
    )
    changed_predecessor = predecessor.supersede(
        expected_version=1,
        effective_at=NOW,
        now=NOW,
    )

    assert changed_successor.revision.value == 2
    assert changed_predecessor.revision.value == 2
    assert changed_predecessor.lifecycle.status.value == "superseded"
    assert changed_predecessor.temporal_extent.valid_to == NOW
    assert changed_successor.freshness.last_confirmed_at is None
    assert changed_predecessor.freshness.last_confirmed_at is None


def _fact(fact_id: str, *, valid_from: datetime) -> MemoryFact:
    return MemoryFact.remember(
        identity=MemoryFactIdentity(
            fact_id=fact_id,
            scope=MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
        ),
        text=f"Fact {fact_id}",
        source_refs=(MemoryFactSourceRef(source_type="document", source_id=fact_id),),
        now=valid_from,
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=valid_from,
            valid_from=valid_from,
            basis="primary_evidence",
        ),
    )
