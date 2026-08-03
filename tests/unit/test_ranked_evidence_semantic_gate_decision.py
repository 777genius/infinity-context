from __future__ import annotations

import copy

import pytest
from infinity_context_server.ranked_evidence_semantic_gate_decision import (
    ranked_evidence_semantic_gate_decision,
)

_CUTOFFS = (1, 2)
_REFERENCE_CUTOFF = 2
_CHECKS = {
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


def _semantic_metrics(
    *,
    retrieval_miss: bool = False,
    crowded_cutoffs: tuple[int, ...] = (),
) -> dict[str, object]:
    expected_refs = ("ref-a", "ref-b")
    reference_covered = ("ref-a",) if retrieval_miss else expected_refs
    cutoffs: list[dict[str, object]] = []
    for cutoff in _CUTOFFS:
        covered = ("ref-a",) if cutoff == 1 else reference_covered
        missing = tuple(ref for ref in expected_refs if ref not in covered)
        crowd_out = (
            tuple(ref for ref in reference_covered if ref not in covered)
            if cutoff in crowded_cutoffs
            else ()
        )
        cutoffs.append(
            {
                "cutoff": cutoff,
                "item_count": cutoff,
                "recall": len(covered) / len(expected_refs),
                "covered_refs": list(covered),
                "covered_ref_count": len(covered),
                "missing_refs": list(missing),
                "missing_ref_count": len(missing),
                "crowd_out_refs": list(crowd_out),
                "crowd_out_ref_count": len(crowd_out),
                "source_diversity_count": cutoff,
                "matches": True,
            }
        )
    retrieval_miss_refs = ["ref-b"] if retrieval_miss else []
    return {
        "schema_version": "ranked-evidence-semantic-metrics.v1",
        "reference_cutoff": _REFERENCE_CUTOFF,
        "expected_ref_count": len(expected_refs),
        "retrieval_miss_refs": retrieval_miss_refs,
        "retrieval_miss_ref_count": len(retrieval_miss_refs),
        "cutoffs": cutoffs,
        "checks": dict(_CHECKS),
        "matches": True,
    }


def _answer_support(
    *,
    complete_cutoffs: tuple[int, ...] = _CUTOFFS,
    applicable: bool = True,
) -> dict[str, object]:
    if not applicable:
        return {
            "schema_version": "ranked-evidence-answer-support-metrics.v1",
            "applicable": False,
            "fallback_reason": "unsupported_query",
            "expected_unit_count": 0,
            "cutoffs": [],
            "matches": False,
        }
    cutoff_metrics = [
        {
            "cutoff": cutoff,
            "supported_unit_count": 2 if cutoff in complete_cutoffs else 1,
            "recall": 1.0 if cutoff in complete_cutoffs else 0.5,
            "complete": cutoff in complete_cutoffs,
        }
        for cutoff in _CUTOFFS
    ]
    return {
        "schema_version": "ranked-evidence-answer-support-metrics.v1",
        "applicable": True,
        "fallback_reason": None,
        "expected_unit_count": 2,
        "cutoffs": cutoff_metrics,
        "matches": all(metric["complete"] is True for metric in cutoff_metrics),
    }


def _decision(
    semantic_metrics: object,
    answer_support: object,
):
    return ranked_evidence_semantic_gate_decision(
        semantic_metrics,
        answer_support,
        expected_cutoffs=_CUTOFFS,
        reference_cutoff=_REFERENCE_CUTOFF,
    )


def test_reference_miss_is_qualified_only_by_complete_reference_cutoff_support() -> None:
    raw_metrics = _semantic_metrics(retrieval_miss=True)
    raw_before = copy.deepcopy(raw_metrics)

    accepted = _decision(raw_metrics, _answer_support(complete_cutoffs=(2,)))
    incomplete = _decision(raw_metrics, _answer_support(complete_cutoffs=()))
    not_applicable = _decision(raw_metrics, _answer_support(applicable=False))

    assert accepted.ok is True
    assert accepted.failure_reason is None
    assert incomplete.failure_reason == "semantic_reference_miss"
    assert not_applicable.failure_reason == "semantic_reference_miss"
    assert raw_metrics == raw_before
    assert raw_metrics["retrieval_miss_refs"] == ["ref-b"]
    assert raw_metrics["cutoffs"][1]["recall"] == 0.5


def test_every_crowded_cutoff_requires_complete_support_at_that_cutoff() -> None:
    metrics = _semantic_metrics(crowded_cutoffs=(1,))

    incomplete = _decision(metrics, _answer_support(complete_cutoffs=(2,)))
    complete = _decision(metrics, _answer_support())
    not_applicable = _decision(metrics, _answer_support(applicable=False))

    assert incomplete.failure_reason == "semantic_answer_support_miss"
    assert complete.ok is True
    assert not_applicable.failure_reason == "semantic_cutoff_crowd_out"


def test_raw_semantic_mismatch_fails_before_any_support_qualification() -> None:
    metrics = _semantic_metrics(retrieval_miss=True)
    metrics["checks"]["coverage_monotonic"] = False
    metrics["matches"] = False

    decision = _decision(metrics, _answer_support())

    assert decision.ok is False
    assert decision.failure_reason == "semantic_metrics_mismatch"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda metrics, support: metrics.update({"unexpected": True}),
            "malformed_semantic_metrics",
        ),
        (
            lambda metrics, support: support["cutoffs"][1].update({"complete": 1}),
            "malformed_answer_support_metrics",
        ),
        (
            lambda metrics, support: support["cutoffs"].reverse(),
            "malformed_answer_support_metrics",
        ),
    ],
)
def test_exact_input_contracts_fail_closed(mutate, reason: str) -> None:
    metrics = _semantic_metrics()
    support = _answer_support()
    mutate(metrics, support)

    decision = _decision(metrics, support)

    assert decision.ok is False
    assert decision.failure_reason == reason
