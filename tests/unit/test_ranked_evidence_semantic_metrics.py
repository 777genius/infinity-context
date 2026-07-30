from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from infinity_context_server.ranked_evidence_semantic_metrics import (
    RankedEvidenceCutoffSnapshot,
    ranked_evidence_semantic_metrics,
)


def _telemetry(
    *,
    cutoff: int,
    eligible: int = 6,
    source_diversity: int | None = None,
) -> dict[str, object]:
    returned = min(cutoff, eligible)
    return {
        "ranked_evidence_candidate_count": 6,
        "ranked_evidence_selectable_candidate_count": 6,
        "ranked_evidence_eligible_candidate_count": eligible,
        "ranked_evidence_returned_count": returned,
        "ranked_evidence_source_diversity_count": (
            returned if source_diversity is None else source_diversity
        ),
    }


def _snapshot(
    cutoff: int,
    item_ids: tuple[str, ...],
    covered_refs: tuple[str, ...],
    *,
    telemetry: dict[str, object] | None = None,
) -> RankedEvidenceCutoffSnapshot:
    return RankedEvidenceCutoffSnapshot(
        cutoff=cutoff,
        item_ids=item_ids,
        covered_refs=covered_refs,
        ranked_telemetry=telemetry or _telemetry(cutoff=cutoff),
    )


def _valid_snapshots() -> tuple[RankedEvidenceCutoffSnapshot, ...]:
    return (
        _snapshot(2, ("i1", "i2"), ("r1",)),
        _snapshot(4, ("i1", "i2", "i3", "i4"), ("r1", "r2")),
        _snapshot(
            6,
            ("i1", "i2", "i3", "i4", "i5", "i6"),
            ("r1", "r2", "r3"),
        ),
    )


def _metrics(
    snapshots: object = None,
    *,
    expected_refs: object = None,
    reference_cutoff: object = 6,
) -> dict[str, object]:
    return ranked_evidence_semantic_metrics(
        _valid_snapshots() if snapshots is None else snapshots,
        expected_refs=(("r1", "r2", "r3", "r4") if expected_refs is None else expected_refs),
        reference_cutoff=reference_cutoff,
    )


def test_reports_post_hoc_recall_crowd_out_and_retrieval_misses() -> None:
    metrics = _metrics()

    assert metrics["matches"] is True
    assert metrics["reference_cutoff"] == 6
    assert metrics["expected_ref_count"] == 4
    assert metrics["retrieval_miss_refs"] == ["r4"]
    assert metrics["retrieval_miss_ref_count"] == 1
    assert metrics["checks"] == {
        "input_valid": True,
        "cutoffs_strictly_increasing": True,
        "reference_cutoff_is_max": True,
        "item_ids_stable_prefix": True,
        "coverage_monotonic": True,
        "telemetry_coherent": True,
        "telemetry_population_invariant": True,
        "telemetry_eligible_monotonic": True,
        "source_diversity_monotonic": True,
    }

    cutoff_two, cutoff_four, reference = metrics["cutoffs"]
    assert cutoff_two["recall"] == 0.25
    assert cutoff_two["covered_refs"] == ["r1"]
    assert cutoff_two["missing_refs"] == ["r2", "r3", "r4"]
    assert cutoff_two["crowd_out_refs"] == ["r2", "r3"]
    assert cutoff_two["source_diversity_count"] == 2
    assert cutoff_four["recall"] == 0.5
    assert cutoff_four["crowd_out_refs"] == ["r3"]
    assert reference["recall"] == 0.75
    assert reference["crowd_out_refs"] == []
    assert all(cutoff["matches"] for cutoff in metrics["cutoffs"])


def test_snapshot_freezes_sequences_and_copies_telemetry() -> None:
    telemetry = _telemetry(cutoff=2)
    item_ids = ["i1", "i2"]
    snapshot = RankedEvidenceCutoffSnapshot(
        cutoff=2,
        item_ids=item_ids,
        covered_refs=["r1"],
        ranked_telemetry=telemetry,
    )
    item_ids.append("i3")
    telemetry["ranked_evidence_returned_count"] = 999

    assert snapshot.item_ids == ("i1", "i2")
    assert snapshot.ranked_telemetry["ranked_evidence_returned_count"] == 2
    with pytest.raises(FrozenInstanceError):
        snapshot.cutoff = 3
    with pytest.raises(TypeError):
        snapshot.ranked_telemetry["extra"] = 1


@pytest.mark.parametrize("field", ["item_ids", "covered_refs"])
def test_snapshot_rejects_scalar_identifier_containers(field: str) -> None:
    values = {
        "cutoff": 2,
        "item_ids": ("i1", "i2"),
        "covered_refs": ("r1",),
        "ranked_telemetry": _telemetry(cutoff=2),
    }
    values[field] = "not-a-sequence"

    with pytest.raises(TypeError):
        RankedEvidenceCutoffSnapshot(**values)


def test_non_increasing_or_duplicate_cutoffs_fail_closed() -> None:
    duplicate = (
        _snapshot(2, ("i1", "i2"), ("r1",)),
        _snapshot(2, ("i1", "i2"), ("r1",)),
    )

    metrics = _metrics(duplicate, reference_cutoff=2)

    assert metrics["matches"] is False
    assert metrics["checks"]["cutoffs_strictly_increasing"] is False
    assert metrics["cutoffs"] == []


@pytest.mark.parametrize("reference_cutoff", [4, 8, True])
def test_reference_cutoff_must_be_exact_final_maximum(reference_cutoff: object) -> None:
    metrics = _metrics(reference_cutoff=reference_cutoff)

    assert metrics["matches"] is False
    if reference_cutoff is True:
        assert metrics["checks"]["input_valid"] is False
        assert metrics["reference_cutoff"] is None
    else:
        assert metrics["checks"]["reference_cutoff_is_max"] is False


def test_ranked_item_ids_must_remain_a_stable_prefix() -> None:
    snapshots = (
        _snapshot(2, ("i1", "i2"), ("r1",)),
        _snapshot(4, ("i1", "replacement", "i3", "i4"), ("r1", "r2")),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is False
    assert metrics["checks"]["item_ids_stable_prefix"] is False


def test_covered_expected_refs_must_be_monotonic() -> None:
    snapshots = (
        _snapshot(2, ("i1", "i2"), ("r1",)),
        _snapshot(4, ("i1", "i2", "i3", "i4"), ("r2",)),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is False
    assert metrics["checks"]["coverage_monotonic"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ranked_evidence_candidate_count", True),
        ("ranked_evidence_selectable_candidate_count", -1),
        ("ranked_evidence_eligible_candidate_count", 2.0),
        ("ranked_evidence_returned_count", "2"),
        ("ranked_evidence_source_diversity_count", None),
    ],
)
def test_ranked_telemetry_requires_exact_non_boolean_counts(
    key: str,
    value: object,
) -> None:
    telemetry = _telemetry(cutoff=2)
    telemetry[key] = value

    metrics = _metrics(
        (_snapshot(2, ("i1", "i2"), ("r1",), telemetry=telemetry),),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
    assert metrics["checks"]["telemetry_coherent"] is False


@pytest.mark.parametrize(
    "telemetry",
    [
        {
            **_telemetry(cutoff=2),
            "ranked_evidence_selectable_candidate_count": 5,
        },
        {
            **_telemetry(cutoff=2),
            "ranked_evidence_eligible_candidate_count": 7,
        },
        {
            **_telemetry(cutoff=2),
            "ranked_evidence_returned_count": 1,
        },
    ],
)
def test_incoherent_ranked_telemetry_fails_closed(
    telemetry: dict[str, object],
) -> None:
    metrics = _metrics(
        (_snapshot(2, ("i1", "i2"), ("r1",), telemetry=telemetry),),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["telemetry_coherent"] is False


@pytest.mark.parametrize(
    "key", ["ranked_evidence_candidate_count", "ranked_evidence_selectable_candidate_count"]
)
def test_candidate_population_must_be_invariant_across_cutoffs(key: str) -> None:
    later = _telemetry(cutoff=4)
    later[key] += 1
    snapshots = (
        _snapshot(2, ("i1", "i2"), ("r1",)),
        _snapshot(
            4,
            ("i1", "i2", "i3", "i4"),
            ("r1", "r2"),
            telemetry=later,
        ),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is False
    assert metrics["checks"]["telemetry_population_invariant"] is False


def test_eligible_population_may_decrease_as_larger_cutoff_selects_more_sources() -> None:
    earlier = _telemetry(cutoff=2)
    later = _telemetry(cutoff=4)
    earlier["ranked_evidence_eligible_candidate_count"] = 6
    later["ranked_evidence_eligible_candidate_count"] = 4
    snapshots = (
        _snapshot(2, ("i1", "i2"), ("r1",), telemetry=earlier),
        _snapshot(
            4,
            ("i1", "i2", "i3", "i4"),
            ("r1", "r2"),
            telemetry=later,
        ),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is True
    assert metrics["checks"]["telemetry_eligible_monotonic"] is True


def test_eligible_population_cannot_increase_at_larger_cutoff() -> None:
    earlier = _telemetry(cutoff=2, eligible=4)
    later = _telemetry(cutoff=4)
    later["ranked_evidence_eligible_candidate_count"] = 5
    snapshots = (
        _snapshot(2, ("i1", "i2"), ("r1",), telemetry=earlier),
        _snapshot(
            4,
            ("i1", "i2", "i3", "i4"),
            ("r1", "r2"),
            telemetry=later,
        ),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is False
    assert metrics["checks"]["telemetry_eligible_monotonic"] is False


def test_source_diversity_must_be_monotonic_across_cutoffs() -> None:
    snapshots = (
        _snapshot(
            2,
            ("i1", "i2"),
            ("r1",),
            telemetry=_telemetry(cutoff=2, source_diversity=2),
        ),
        _snapshot(
            4,
            ("i1", "i2", "i3", "i4"),
            ("r1", "r2"),
            telemetry=_telemetry(cutoff=4, source_diversity=1),
        ),
    )

    metrics = _metrics(snapshots, reference_cutoff=4)

    assert metrics["matches"] is False
    assert metrics["checks"]["source_diversity_monotonic"] is False


def test_empty_result_cannot_report_source_diversity() -> None:
    telemetry = _telemetry(cutoff=2, source_diversity=1)
    telemetry["ranked_evidence_returned_count"] = 0

    metrics = _metrics(
        (_snapshot(2, (), (), telemetry=telemetry),),
        expected_refs=("r1",),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["telemetry_coherent"] is False


@pytest.mark.parametrize(
    "expected_refs",
    [
        ("r1", "r1"),
        ("r1", ""),
        ("r1", 7),
        (),
        "r1",
    ],
)
def test_malformed_or_duplicate_expected_refs_fail_closed(
    expected_refs: object,
) -> None:
    metrics = _metrics(expected_refs=expected_refs)

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
    assert metrics["cutoffs"] == []


@pytest.mark.parametrize(
    "covered_refs",
    [
        ("r1", "r1"),
        ("r1", ""),
        ("r1", "not-expected"),
    ],
)
def test_malformed_duplicate_or_unknown_covered_refs_fail_closed(
    covered_refs: tuple[str, ...],
) -> None:
    metrics = _metrics(
        (_snapshot(2, ("i1", "i2"), covered_refs),),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False


@pytest.mark.parametrize("cutoff", [True, 0, -1, 2.0])
def test_cutoff_requires_an_exact_positive_integer(cutoff: object) -> None:
    snapshot = _snapshot(cutoff, ("i1", "i2"), ("r1",))

    metrics = _metrics((snapshot,), reference_cutoff=2)

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
    assert metrics["checks"]["cutoffs_strictly_increasing"] is False


@pytest.mark.parametrize(
    "item_ids",
    [
        ("i1", "i1"),
        ("i1", ""),
        ("i1", 7),
    ],
)
def test_malformed_or_duplicate_item_ids_fail_closed(
    item_ids: tuple[str, ...],
) -> None:
    metrics = _metrics(
        (_snapshot(2, item_ids, ("r1",)),),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False


def test_missing_telemetry_key_fails_closed_without_partial_metrics() -> None:
    telemetry = _telemetry(cutoff=2)
    telemetry.pop("ranked_evidence_eligible_candidate_count")

    metrics = _metrics(
        (_snapshot(2, ("i1", "i2"), ("r1",), telemetry=telemetry),),
        reference_cutoff=2,
    )

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
    assert metrics["cutoffs"] == []


def test_budget_limited_returned_count_is_coherent() -> None:
    telemetry = _telemetry(cutoff=4, eligible=6)
    telemetry["ranked_evidence_returned_count"] = 2
    snapshot = _snapshot(
        4,
        ("i1", "i2"),
        ("r1",),
        telemetry=telemetry,
    )

    metrics = _metrics(
        (snapshot,),
        expected_refs=("r1",),
        reference_cutoff=4,
    )

    assert metrics["matches"] is True
    assert metrics["checks"]["telemetry_coherent"] is True


def test_multi_source_item_diversity_may_exceed_returned_items() -> None:
    telemetry = _telemetry(
        cutoff=2,
        eligible=6,
        source_diversity=3,
    )
    telemetry["ranked_evidence_returned_count"] = 1
    snapshot = _snapshot(
        2,
        ("multi-source-item",),
        ("r1",),
        telemetry=telemetry,
    )

    metrics = _metrics(
        (snapshot,),
        expected_refs=("r1",),
        reference_cutoff=2,
    )

    assert metrics["matches"] is True
    assert metrics["checks"]["telemetry_coherent"] is True


def test_non_snapshot_input_fails_closed() -> None:
    metrics = _metrics(({"cutoff": 2},), reference_cutoff=2)

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
    assert metrics["checks"]["reference_cutoff_is_max"] is False


def test_empty_input_fails_closed() -> None:
    metrics = _metrics((), expected_refs=("r1",), reference_cutoff=2)

    assert metrics["matches"] is False
    assert metrics["checks"]["input_valid"] is False
