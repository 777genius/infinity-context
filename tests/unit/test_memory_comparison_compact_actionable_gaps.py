from __future__ import annotations

import json

from infinity_context_server import memory_comparison_benchmark as benchmark


def _ranked_gap(index: int) -> dict[str, object]:
    return {
        "rank": index,
        "impact_count": 10 - index,
        "impact_rate": 0.123456789,
        "severity": "blocking",
        "category": "query_plan",
        "gap": f"gap-{index}",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "sample_case_ids": [
            f"case-{index}-1",
            f"case-{index}-2",
            f"case-{index}-3",
            f"case-{index}-4",
        ],
        "action": "Inspect this gap and adjust the matching policy.",
        "samples": [{"case_id": f"case-{index}-1", "text": "fixture detail"}],
        "evidence": {"sample": "diagnostic detail"},
    }


def test_compact_actionable_gaps_bounds_and_excludes_verbose_fields() -> None:
    compact = benchmark._compact_actionable_gaps(
        [_ranked_gap(index) for index in range(1, 8)]
    )

    assert len(compact) == 5
    assert compact[0] == {
        "rank": 1,
        "impact_count": 9,
        "impact_rate": 0.123457,
        "severity": "blocking",
        "category": "query_plan",
        "gap": "gap-1",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "action": "Inspect this gap and adjust the matching policy.",
        "sample_case_ids": ["case-1-1", "case-1-2", "case-1-3"],
    }
    assert compact[-1]["gap"] == "gap-5"
    assert all("samples" not in gap for gap in compact)
    assert all("evidence" not in gap for gap in compact)


def test_compact_actionable_gaps_keeps_bounded_action_text() -> None:
    long_action = "x" * 220
    compact = benchmark._compact_actionable_gaps(
        [
            {
                "rank": 1,
                "impact_count": 1,
                "category": "query_plan",
                "gap": "missing_bridge",
                "action": long_action,
            }
        ]
    )

    assert compact[0]["action"] == f"{long_action[:177]}..."
    assert len(compact[0]["action"]) == 180


def test_compact_fast_gate_summary_surfaces_bounded_actionable_gaps(
    monkeypatch,
) -> None:
    ranked_gaps = [_ranked_gap(index) for index in range(1, 7)]

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "evaluation_count": 1,
            "expected_case_count": 1,
            "actionable_gap_summary": {
                "top_gap": ranked_gaps[0],
                "ranked_gaps": ranked_gaps,
                "blocking_gap_count": 6,
                "diagnostic_gap_count": 0,
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))

    assert summary["top_gap"] == {
        "rank": 1,
        "impact_count": 9,
        "impact_rate": 0.123457,
        "severity": "blocking",
        "category": "query_plan",
        "gap": "gap-1",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "action": "Inspect this gap and adjust the matching policy.",
        "sample_case_ids": ["case-1-1", "case-1-2", "case-1-3"],
    }
    assert len(summary["top_actionable_gaps"]) == 5
    assert summary["top_actionable_gaps"][0] == {
        "rank": 1,
        "impact_count": 9,
        "impact_rate": 0.123457,
        "severity": "blocking",
        "category": "query_plan",
        "gap": "gap-1",
        "failed_gate": "query_plan_evidence_roles_clear",
        "source_metric": "query_plan_gap_breakdown.reason_counts",
        "action": "Inspect this gap and adjust the matching policy.",
        "sample_case_ids": ["case-1-1", "case-1-2", "case-1-3"],
    }
    assert "samples" not in summary["top_gap"]
    assert "evidence" not in summary["top_gap"]
    assert all("samples" not in gap for gap in summary["top_actionable_gaps"])
    assert all("evidence" not in gap for gap in summary["top_actionable_gaps"])


def test_compact_fast_gate_summary_keeps_low_confidence_context_gap() -> None:
    summary = benchmark._compact_fast_gate_summary(
        (
            {
                "case_id": "preserved-low-confidence-context",
                "group": "multi-hop",
                "scored": True,
                "judgment": {"score": 1.0},
                "retrieval_quality": {},
                "evidence_bundle": {},
                "retrieval": {"metadata": {}, "results": []},
                "cutoff_results": {
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_item_count": 1,
                            "bundle_confidence_score": 0.42,
                            "bundle_confidence_band": "low",
                            "bundle_source_ref_support_item_count": 1,
                        }
                    }
                },
            },
        )
    )

    assert summary["answer_context_support_gap_counts"]["gap_reason_counts"] == {
        "low_bundle_confidence": 1
    }
    assert summary["answer_context_support_gap_samples"][0]["gap_reasons"] == [
        "low_bundle_confidence"
    ]


def test_compact_fast_gate_summary_surfaces_missing_answer_contexts() -> None:
    summary = benchmark._compact_fast_gate_summary(
        (
            {
                "case_id": "missing-answer-context",
                "group": "single-hop",
                "scored": True,
                "judgment": {"score": 1.0},
                "retrieval_quality": {},
                "evidence_bundle": {},
                "retrieval": {"metadata": {}, "results": []},
                "cutoff_results": {
                    "3": {},
                    "5": {"answer_context": []},
                    "10": {
                        "answer_context": {
                            "source": "evidence_bundle",
                            "memory_count": 1,
                            "source_ref_item_count": 1,
                        }
                    },
                },
            },
        )
    )

    assert summary["answer_context_support_gap_counts"] == {
        "expected_context_count": 3,
        "context_count": 1,
        "support_gap_context_count": 0,
        "answer_context_availability_gap_count": 2,
        "missing_answer_context_count": 1,
        "unsupported_answer_context_count": 1,
        "gap_reason_counts": {},
        "missing_required_role_counts": {},
        "risk_reason_counts": {},
    }
    assert summary["answer_context_availability_gap_samples"] == [
        {
            "case_id": "missing-answer-context",
            "group": "single-hop",
            "cutoff": "3",
            "source": "missing",
            "gap_reasons": ["missing_answer_context"],
        },
        {
            "case_id": "missing-answer-context",
            "group": "single-hop",
            "cutoff": "5",
            "source": "unsupported",
            "gap_reasons": ["unsupported_answer_context"],
        },
    ]


def test_compact_fast_gate_summary_bounds_temporal_grounding_issue_fields(
    monkeypatch,
) -> None:
    long_value = "x" * 240

    def truncated(prefix: str) -> str:
        return f"{prefix}{long_value[: 177 - len(prefix)]}..."

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "schema_version": "fast_gate.v1",
            "ready_for_full_locomo": False,
            "failed_gates": [],
            "evaluation_count": 4,
            "expected_case_count": 4,
            "temporal_grounding_table": {
                "schema_version": "temporal_grounding.v1",
                "temporal_case_count": 4,
                "temporal_scored_case_count": 4,
                "selected_item_count": 4,
                "selected_temporal_grounding_issue_item_count": 4,
                "selected_temporal_grounding_issue_reason_counts": {
                    f"missing_{long_value}": 4,
                },
                "selected_temporal_grounding_issue_samples": [
                    {
                        "case_id": f"case-{index}-{long_value}",
                        "group": f"temporal-{long_value}",
                        "item_id": f"item-{index}-{long_value}",
                        "role": f"role-{long_value}",
                        "query_roles": [
                            f"role-{value}-{long_value}" for value in range(8)
                        ],
                        "source_refs": [
                            "D1:0",
                            f"D1:{'9' * 120}",
                            *[f"D1:{value}" for value in range(1, 8)],
                        ],
                        "issue_reasons": [
                            f"missing-{value}-{long_value}" for value in range(8)
                        ],
                        "source_identity_gap_codes": [
                            f"gap-{value}-{long_value}" for value in range(8)
                        ],
                        "grounding_signals": {
                            "source_window": False,
                            "session_boundary": False,
                            "date_or_range": False,
                            "relative_date": True,
                            "temporal_order": False,
                        },
                        "text": "raw temporal text must stay out",
                    }
                    for index in range(5)
                ],
            },
            "actionable_gap_summary": {
                "schema_version": "actionable_gap_summary.v1",
                "blocking_gap_count": 0,
                "diagnostic_gap_count": 1,
                "ranked_gaps": [
                    {
                        "rank": 1,
                        "impact_count": 4,
                        "impact_rate": 1.0,
                        "severity": "diagnostic",
                        "category": f"temporal-{long_value}",
                        "gap": f"missing-{long_value}",
                        "failed_gate": "",
                        "source_metric": f"temporal_grounding_table.{long_value}",
                        "action": f"Fix temporal grounding {long_value}",
                        "sample_case_ids": [
                            f"case-{index}-{long_value}" for index in range(5)
                        ],
                        "samples": [{"case_id": "verbose"}],
                        "evidence": {"raw": "verbose"},
                    }
                ],
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))

    top_gap = summary["top_gap"]
    assert top_gap["category"] == truncated("temporal-")
    assert top_gap["gap"] == truncated("missing-")
    assert top_gap["source_metric"] == truncated("temporal_grounding_table.")
    assert len(top_gap["sample_case_ids"]) == 3
    assert all(len(case_id) <= 180 for case_id in top_gap["sample_case_ids"])
    samples = summary["temporal_grounding_issue_samples"]
    assert len(samples) == 3
    assert len(samples[0]["query_roles"]) == 6
    assert len(samples[0]["source_refs"]) == 6
    assert len(samples[0]["issue_reasons"]) == 6
    assert len(samples[0]["source_identity_gap_codes"]) == 6
    assert all(
        len(value) <= 180
        for sample in samples
        for key in (
            "case_id",
            "group",
            "item_id",
            "role",
        )
        for value in (sample[key],)
    )
    assert all(
        len(value) <= 180
        for sample in samples
        for key in (
            "query_roles",
            "source_refs",
            "issue_reasons",
            "source_identity_gap_codes",
        )
        for value in sample[key]
    )
    assert "text" not in samples[0]
    serialized = json.dumps(summary, sort_keys=True)
    assert long_value not in serialized
    assert "9" * 120 not in serialized
    assert "raw temporal text must stay out" not in serialized


def test_compact_fast_gate_summary_bounds_remaining_gap_sample_fields(
    monkeypatch,
) -> None:
    long_value = "x" * 260
    raw_memory_text = "RAW MEMORY TEXT MUST STAY OUT"
    raw_provider_ref = "provider-ref-" + long_value

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "schema_version": "fast_gate.v1",
            "ready_for_full_locomo": False,
            "failed_gates": [],
            "evaluation_count": 2,
            "expected_case_count": 2,
            "query_role_gap_breakdown": {
                "bridge_hit_roles_without_selected_items": [
                    f"role-{index}-{long_value}" for index in range(10)
                ],
                "bridge_hit_role_families_without_selected_items": [
                    f"family-{index}-{long_value}" for index in range(10)
                ],
            },
            "answerability_gap_breakdown": {
                "samples": [
                    {
                        "case_id": f"answerability-{long_value}",
                        "group": f"group-{long_value}",
                        "memory_id": f"memory-{long_value}",
                        "reasons": [
                            f"reason-{index}-{long_value}" for index in range(8)
                        ],
                        "query_roles": [
                            f"role-{index}-{long_value}" for index in range(8)
                        ],
                        "raw_text": raw_memory_text,
                    }
                ],
            },
            "answer_context_support_gap_summary": {
                "samples": [
                    {
                        "case_id": f"context-{long_value}",
                        "group": f"group-{long_value}",
                        "cutoff": f"cutoff-{long_value}",
                        "source": f"source-{long_value}",
                        "item_ids": [
                            f"item-{index}-{long_value}" for index in range(10)
                        ],
                        "gap_reasons": [
                            f"gap-{index}-{long_value}" for index in range(10)
                        ],
                        "memory_text": raw_memory_text,
                    }
                ],
            },
            "selected_evidence_weakness": {
                "samples": [
                    {
                        "case_id": f"weak-{long_value}",
                        "group": f"group-{long_value}",
                        "item_id": f"item-{long_value}",
                        "role": f"role-{long_value}",
                        "source_refs": [raw_provider_ref],
                        "query_roles": [
                            f"query-role-{index}-{long_value}"
                            for index in range(8)
                        ],
                        "text": raw_memory_text,
                    }
                ],
            },
            "rerank_signal_gap_breakdown": {
                "positive_unselected_samples": [
                    {
                        "case_id": f"rerank-{long_value}",
                        "group": f"group-{long_value}",
                        "item_id": f"candidate-{long_value}",
                        "selected_item_ids": [
                            f"selected-{index}-{long_value}" for index in range(8)
                        ],
                        "top_signals": {
                            f"signal-{index}-{long_value}": f"value-{long_value}"
                            for index in range(8)
                        },
                        "memory_text": raw_memory_text,
                    }
                ],
                "selection_conflict_samples": [
                    {
                        "case_id": f"conflict-{long_value}",
                        "group": f"group-{long_value}",
                        "positive_unselected_signal_counts": {
                            f"signal-{index}-{long_value}": index
                            for index in range(8)
                        },
                    }
                ],
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))
    serialized = json.dumps(summary, sort_keys=True)

    assert raw_memory_text not in serialized
    assert long_value not in serialized
    assert len(
        summary["query_role_gap_counts"]["bridge_hit_roles_without_selected_items"]
    ) == 8
    assert len(summary["answerability_gap_samples"]["samples"][0]["reasons"]) == 6
    assert len(summary["answer_context_support_gap_samples"][0]["item_ids"]) == 8
    weakness_sample = summary["selected_evidence_weakness_samples"]["samples"][0]
    assert "source_refs" not in weakness_sample
    assert raw_provider_ref not in serialized
    assert (
        len(
            summary["rerank_signal_gap_samples"]["positive_unselected_samples"][0][
                "top_signals"
            ]
        )
        == 6
    )


def test_compact_fast_gate_summary_recounts_sanitized_selected_source_refs(
    monkeypatch,
) -> None:
    raw_provider_ref = "provider:private-token:selected-evidence"

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "schema_version": "fast_gate.v1",
            "evaluation_count": 1,
            "expected_case_count": 1,
            "selected_evidence_weakness": {
                "samples": [
                    {
                        "case_id": "selected-raw-source-ref",
                        "source_refs": [raw_provider_ref, raw_provider_ref, "D1:1"],
                    }
                ],
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))
    sample = summary["selected_evidence_weakness_samples"]["samples"][0]

    assert sample["source_refs"] == ["D1:1"]
    assert sample["source_ref_count"] == 2
    assert raw_provider_ref not in json.dumps(summary, sort_keys=True)


def test_compact_fast_gate_summary_filters_private_item_ids(monkeypatch) -> None:
    private_item_id = "provider:private-token-memory-123"

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "schema_version": "fast_gate.v1",
            "evaluation_count": 1,
            "expected_case_count": 1,
            "answerability_gap_breakdown": {
                "samples": [
                    {
                        "case_id": "private-item-id-answerability",
                        "memory_id": private_item_id,
                        "rank": 1,
                    }
                ],
            },
            "answer_context_support_gap_summary": {
                "samples": [
                    {
                        "case_id": "private-item-id-context",
                        "item_ids": [private_item_id, "safe-item"],
                    }
                ],
            },
            "selected_evidence_weakness": {
                "samples": [
                    {
                        "case_id": "private-item-id-selected",
                        "item_id": private_item_id,
                    }
                ],
            },
            "temporal_grounding_table": {
                "selected_temporal_grounding_issue_samples": [
                    {
                        "case_id": "private-item-id-temporal",
                        "item_id": private_item_id,
                    }
                ],
            },
            "rerank_signal_gap_breakdown": {
                "positive_unselected_samples": [
                    {
                        "case_id": "private-item-id-rerank",
                        "item_id": private_item_id,
                        "selected_item_ids": [private_item_id, "safe-selected"],
                    }
                ],
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))
    serialized = json.dumps(summary, sort_keys=True)

    assert private_item_id not in serialized
    assert "private-token" not in serialized
    assert "safe-item" in serialized
    assert "safe-selected" in serialized
    assert "memory_id" not in summary["answerability_gap_samples"]["samples"][0]
    assert "item_id" not in summary["selected_evidence_weakness_samples"]["samples"][0]
    assert "item_id" not in summary["temporal_grounding_issue_samples"][0]
    assert "item_id" not in summary["rerank_signal_gap_samples"][
        "positive_unselected_samples"
    ][0]


def test_compact_fast_gate_summary_keeps_selected_weakness_diagnostics_bounded(
    monkeypatch,
) -> None:
    long_value = "x" * 260
    raw_memory_text = "RAW SELECTED MEMORY TEXT MUST STAY OUT"

    def fast_gate_metrics(_: object) -> dict[str, object]:
        return {
            "schema_version": "fast_gate.v1",
            "evaluation_count": 6,
            "expected_case_count": 6,
            "selected_evidence_weakness": {
                "samples": [
                    {
                        "case_id": f"weakness-{index}-{long_value}",
                        "group": f"group-{long_value}",
                        "item_id": f"item-{index}-{long_value}",
                        "role": f"role-{long_value}",
                        "answerability_score": 0.12,
                        "source_locality_score": 0.34,
                        "broad_summary": True,
                        "conflict_or_stale": True,
                        "source_ref_count": 8,
                        "risk_reason_count": 8,
                        "planner_reason_count": 8,
                        "answerability_reason_count": 8,
                        "source_locality_reason_count": 8,
                        "retrieval_source_count": 8,
                        "source_type_count": 8,
                        "relation_category_count": 8,
                        "relation_category_hit_count": 8,
                        "source_type": f"source-type-{long_value}",
                        "stale_reason": f"stale-{long_value}",
                        "conflict_reason": f"conflict-{long_value}",
                        "query_roles": [
                            f"query-role-{value}-{long_value}"
                            for value in range(8)
                        ],
                        "source_refs": [f"D1:{value}" for value in range(8)],
                        "risk_reason_codes": [
                            f"risk-{value}-{long_value}" for value in range(8)
                        ],
                        "planner_reason_codes": [
                            f"planner-{value}-{long_value}" for value in range(8)
                        ],
                        "answerability_reason_codes": [
                            f"answerability-{value}-{long_value}"
                            for value in range(8)
                        ],
                        "source_locality_reason_codes": [
                            f"locality-{value}-{long_value}" for value in range(8)
                        ],
                        "retrieval_sources": [
                            f"source-{value}-{long_value}" for value in range(8)
                        ],
                        "source_types": [
                            f"type-{value}-{long_value}" for value in range(8)
                        ],
                        "relation_categories": [
                            f"category-{value}-{long_value}" for value in range(8)
                        ],
                        "relation_category_hits": [
                            f"hit-{value}-{long_value}" for value in range(8)
                        ],
                        "text": raw_memory_text,
                    }
                    for index in range(4)
                ],
            },
        }

    monkeypatch.setattr(benchmark, "_fast_gate_metrics", fast_gate_metrics)

    summary = benchmark._compact_fast_gate_summary(({"case_id": "case-1"},))
    samples = summary["selected_evidence_weakness_samples"]["samples"]
    sample = samples[0]

    assert len(samples) == 3
    assert sample["answerability_score"] == 0.12
    assert sample["source_locality_score"] == 0.34
    assert sample["broad_summary"] is True
    assert sample["conflict_or_stale"] is True
    assert sample["source_ref_count"] == 8
    assert sample["source_refs"] == [f"D1:{value}" for value in range(6)]
    for key in (
        "query_roles",
        "risk_reason_codes",
        "planner_reason_codes",
        "answerability_reason_codes",
        "source_locality_reason_codes",
        "retrieval_sources",
        "source_types",
        "relation_categories",
        "relation_category_hits",
    ):
        assert len(sample[key]) == 6
        assert all(len(value) <= 180 for value in sample[key])
    serialized = json.dumps(summary, sort_keys=True)
    assert long_value not in serialized
    assert raw_memory_text not in serialized


def test_compact_backend_metrics_uses_allowlist_without_raw_payloads() -> None:
    raw_payload = "RAW MEMORY TEXT provider:private-token"

    compact = benchmark._compact_backend_metrics(
        {
            "memo-stack": {
                "ok": True,
                "total": 1,
                "accuracy": 1.0,
                "expected_term_recall": 1.0,
                "raw_provider_payload": raw_payload,
                "quality_diagnostics": {
                    "samples": [{"memory_text": raw_payload}],
                },
                "fast_gate": {
                    "selected_evidence_weakness": {
                        "samples": [{"source_refs": [raw_payload]}],
                    },
                },
            }
        }
    )

    assert compact == {
        "memo-stack": {
            "accuracy": 1.0,
            "expected_term_recall": 1.0,
            "ok": True,
            "total": 1,
        }
    }
    assert raw_payload not in json.dumps(compact, sort_keys=True)
