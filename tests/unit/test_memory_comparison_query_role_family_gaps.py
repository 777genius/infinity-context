from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
    quality_diagnostics,
)


def test_query_role_gap_breakdown_reports_typed_family_role_loss() -> None:
    item = {
        "case_id": "typed-family-loss",
        "retrieval": {
            "results": [
                _memory(
                    "duration",
                    query_roles=("duration_temporal_support",),
                    lifted=True,
                ),
                _memory("contrast", query_roles=("contrast_support",)),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert breakdown["role_family_gap_count"] == 2
    assert breakdown["role_families_without_selected_items"] == [
        "contrast_support",
        "temporal_support",
    ]
    assert breakdown["role_family_gaps"]["temporal_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "gap_reasons": ["not_selected"],
    }
    assert breakdown["role_family_gaps"]["contrast_support"]["gap_reasons"] == [
        "not_selected",
        "not_lifted",
    ]


def test_query_role_gap_breakdown_reports_multi_hop_bridge_family_loss() -> None:
    item = {
        "case_id": "bridge-family-loss",
        "retrieval": {
            "results": [
                _memory(
                    "bridge",
                    query_roles=("multi_hop_bridge",),
                    bridge_query_hit=True,
                    lifted=True,
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]
    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert table["bridge_query_hit_candidate_family_counts"] == {"multi_hop": 1}
    assert table["bridge_query_hit_selected_family_counts"] == {}
    assert breakdown["bridge_hit_role_families_without_selected_items"] == [
        "multi_hop"
    ]
    assert breakdown["role_family_gaps"]["multi_hop"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 1,
        "bridge_query_hit_selected_count": 0,
        "gap_reasons": ["not_selected", "bridge_hit_not_selected"],
    }


def test_query_role_gap_breakdown_uses_fusion_selected_evidence_role_families() -> None:
    item = {
        "case_id": "fusion-selected-role-family",
        "retrieval": {
            "metadata": {
                "multi_query_merge": {
                    "query_role_counts": {"location_support": 1},
                    "selected_evidence_query_role_counts": {
                        "location_support": 1
                    },
                }
            },
            "results": [
                _memory(
                    "location",
                    query_roles=("location_support",),
                    lifted=True,
                ),
            ],
        },
        "evidence_bundle": {
            "items": [
                {
                    "id": "location",
                    "role": "location_support",
                }
            ]
        },
    }

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert breakdown["selected_evidence_query_role_family_counts"] == {
        "location_support": 1,
        "relation_compact": 1,
    }
    assert breakdown["role_families_without_selected_items"] == [
        "location_support",
        "relation_compact",
    ]
    assert breakdown["role_families_without_selected_evidence"] == []
    assert breakdown["role_families_with_selected_evidence_only_in_fusion"] == [
        "location_support",
        "relation_compact",
    ]
    assert breakdown["role_family_gap_count"] == 2
    assert breakdown["role_family_gaps"]["location_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "gap_reasons": ["selected_evidence_not_bundle_tagged"],
        "selected_evidence_query_role_family_count": 1,
    }
    assert breakdown["role_family_gaps"]["relation_compact"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "gap_reasons": ["selected_evidence_not_bundle_tagged"],
        "selected_evidence_query_role_family_count": 1,
    }


def _memory(
    item_id: str,
    *,
    query_roles: tuple[str, ...],
    answerability_score: float = 0.7,
    source_locality_score: float = 0.7,
    bridge_query_hit: bool = False,
    lifted: bool = False,
) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "benchmark_candidate_features": {
            "query_roles": query_roles,
            "answerability_score": answerability_score,
            "source_locality_score": source_locality_score,
            "bridge_query_hit": bridge_query_hit,
        }
    }
    if lifted:
        diagnostics["benchmark_rerank_boosted"] = True
    return {
        "id": item_id,
        "metadata": {
            "diagnostics": diagnostics,
        },
    }
