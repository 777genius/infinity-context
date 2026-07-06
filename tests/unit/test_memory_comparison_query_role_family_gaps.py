from __future__ import annotations

import json

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


def test_query_role_gap_samples_use_deterministic_roles_and_families() -> None:
    item = {
        "case_id": "deterministic-role-samples",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "mixed",
                    query_roles=(
                        "temporal_support",
                        "visual_temporal_support",
                        "contrast_support",
                    ),
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    samples = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]["samples"]

    assert [sample["query_role"] for sample in samples] == [
        "contrast_support",
        "temporal_support",
        "visual_temporal_support",
    ]
    assert samples[0]["query_role_families"] == ["contrast_support"]
    assert samples[0]["query_role_gap_families"] == ["contrast_support"]
    assert samples[1]["query_role_families"] == ["temporal_support"]
    assert samples[1]["query_role_gap_families"] == ["temporal_support"]
    assert samples[2]["query_role_families"] == [
        "visual_support",
        "temporal_support",
    ]
    assert samples[2]["query_role_gap_families"] == [
        "visual_support",
        "temporal_support",
    ]
    assert samples[2]["gap_reasons"] == ["not_selected", "not_lifted"]


def test_query_role_gap_samples_include_candidate_role_context() -> None:
    item = {
        "case_id": "candidate-role-context",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "mixed-candidate",
                    query_roles=(
                        "visual_temporal_support",
                        "location_support",
                        "multi_hop_bridge",
                    ),
                    lifted=True,
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    sample = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]["samples"][0]

    assert sample["candidate_query_roles"] == [
        "location_support",
        "multi_hop_bridge",
        "visual_temporal_support",
    ]
    assert sample["candidate_query_role_count"] == 3
    assert sample["candidate_query_role_families"] == [
        "location_support",
        "multi_hop",
        "relation_compact",
        "temporal_support",
        "visual_support",
    ]
    assert sample["candidate_query_role_family_count"] == 5


def test_query_role_gap_samples_sort_selected_bundle_role_lists() -> None:
    item = {
        "case_id": "deterministic-selected-role-lists",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "temporal",
                    query_roles=("temporal_support",),
                ),
            ],
        },
        "evidence_bundle": {
            "items": [
                {
                    "id": "selected-z",
                    "role": "z_support",
                    "query_roles": ("z_query",),
                },
                {
                    "id": "selected-a",
                    "role": "a_support",
                    "query_roles": ("a_query",),
                },
            ]
        },
    }

    sample = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]["samples"][0]

    assert sample["selected_bundle_roles"] == ["a_support", "z_support"]
    assert sample["selected_bundle_role_families"] == ["a_support", "z_support"]
    assert sample["selected_bundle_role_family_count"] == 2
    assert sample["selected_bundle_query_roles"] == ["a_query", "z_query"]
    assert sample["selected_bundle_query_role_families"] == ["a_query", "z_query"]
    assert sample["selected_bundle_query_role_family_count"] == 2


def test_query_role_gap_samples_match_positive_signal_lifted_candidates() -> None:
    item = {
        "case_id": "positive-signal-lifted-sample",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "signal-lifted",
                    query_roles=("temporal_support",),
                    score_signals={"temporal_query_role_match": True},
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert breakdown["lifted_candidate_role_counts"] == {"temporal_support": 1}
    assert breakdown["samples"][0]["lifted"] is True


def test_query_role_gap_samples_include_bounded_reason_codes() -> None:
    item = {
        "case_id": "bounded-reason-sample",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "reason-coded",
                    query_roles=("temporal_support",),
                    score_signals={
                        "z_signal": True,
                        "a_signal": True,
                    },
                    policy_reason_codes=tuple(
                        f"policy-reason-{index}" for index in range(8)
                    ),
                    answerability_reason_codes=tuple(
                        f"answerability-reason-{index}" for index in range(8)
                    ),
                    source_locality_reason_codes=tuple(
                        f"source-locality-reason-{index}" for index in range(8)
                    ),
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    sample = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]["samples"][0]

    assert sample["positive_signal_names"] == ["a_signal", "z_signal"]
    assert sample["positive_signal_count"] == 2
    assert sample["policy_reason_codes"] == [
        "policy-reason-0",
        "policy-reason-1",
        "policy-reason-2",
        "policy-reason-3",
        "policy-reason-4",
        "policy-reason-5",
    ]
    assert sample["policy_reason_count"] == 8
    assert sample["answerability_reason_codes"] == [
        "answerability-reason-0",
        "answerability-reason-1",
        "answerability-reason-2",
        "answerability-reason-3",
        "answerability-reason-4",
        "answerability-reason-5",
    ]
    assert sample["answerability_reason_count"] == 8
    assert sample["source_locality_reason_codes"] == [
        "source-locality-reason-0",
        "source-locality-reason-1",
        "source-locality-reason-2",
        "source-locality-reason-3",
        "source-locality-reason-4",
        "source-locality-reason-5",
    ]
    assert sample["source_locality_reason_count"] == 8
    json.dumps(sample)


def test_query_role_gap_samples_include_fusion_selected_evidence_role() -> None:
    item = {
        "case_id": "fusion-selected-evidence-role-sample",
        "group": "single-hop",
        "retrieval": {
            "results": [
                _memory(
                    "location",
                    query_roles=("location_support",),
                    candidate_fusion={
                        "score_winner_query_role": "original_question",
                        "selected_evidence_query_role": "location_support",
                        "evidence_selection_reason_codes": [
                            "lower_score_within_band",
                            "focused_query_role",
                            "higher_evidence_quality",
                        ],
                    },
                ),
            ],
        },
        "evidence_bundle": {"items": []},
    }

    sample = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]["samples"][0]

    assert sample["fusion_score_winner_query_role"] == "original_question"
    assert sample["fusion_selected_evidence_query_role"] == "location_support"
    assert sample["fusion_selected_evidence_query_role_families"] == [
        "location_support",
        "relation_compact",
    ]
    assert sample["fusion_evidence_selection_reason_codes"] == [
        "lower_score_within_band",
        "focused_query_role",
        "higher_evidence_quality",
    ]
    assert sample["fusion_evidence_selection_reason_count"] == 3
    json.dumps(sample)


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


def test_query_role_gap_breakdown_reports_bundle_role_without_query_tag() -> None:
    item = {
        "case_id": "selected-role-not-query-tagged",
        "retrieval": {
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

    assert breakdown["selected_bundle_role_family_counts"] == {
        "location_support": 1,
        "relation_compact": 1,
    }
    assert breakdown["role_families_with_selected_bundle_role_only"] == [
        "location_support",
        "relation_compact",
    ]
    assert breakdown["role_family_gaps"]["location_support"] == {
        "candidate_count": 1,
        "lifted_candidate_count": 1,
        "selected_item_count": 0,
        "selection_rate": 0.0,
        "lifted_rate": 1.0,
        "bridge_query_hit_candidate_count": 0,
        "bridge_query_hit_selected_count": 0,
        "gap_reasons": [
            "not_selected",
            "selected_bundle_role_not_query_tagged",
        ],
        "selected_bundle_role_family_count": 1,
    }
    assert breakdown["role_family_gaps"]["relation_compact"]["gap_reasons"] == [
        "not_selected",
        "selected_bundle_role_not_query_tagged",
    ]
    sample = breakdown["samples"][0]
    assert sample["selected_bundle_role_families"] == [
        "location_support",
        "relation_compact",
    ]
    assert sample["selected_bundle_role_family_count"] == 2
    assert sample["selected_bundle_query_role_families"] == []
    assert sample["selected_bundle_query_role_family_count"] == 0


def test_query_role_family_gap_ignores_exact_role_loss_when_family_selected() -> None:
    item = {
        "case_id": "typed-profile-sibling-selected",
        "retrieval": {
            "results": [
                _memory(
                    "health",
                    query_roles=("health_support",),
                    lifted=True,
                ),
                _memory(
                    "current-goal",
                    query_roles=("current_goal_support",),
                    lifted=True,
                ),
            ],
        },
        "evidence_bundle": {
            "items": [
                {
                    "id": "current-goal",
                    "role": "current_goal_support",
                    "query_roles": ["current_goal_support"],
                }
            ]
        },
    }

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert breakdown["candidate_role_family_counts"] == {"relation_compact": 2}
    assert breakdown["selected_item_role_family_counts"] == {"relation_compact": 1}
    assert breakdown["role_families_without_selected_items"] == []
    assert breakdown["role_families_without_selected_evidence"] == []
    assert breakdown["role_family_gap_count"] == 0
    assert breakdown["role_family_gaps"] == {}
    assert breakdown["roles_without_selected_items"] == ["health_support"]


def test_query_role_family_gap_counts_visual_temporal_selected_evidence_families() -> None:
    item = {
        "case_id": "visual-temporal-fusion-selected",
        "retrieval": {
            "metadata": {
                "multi_query_merge": {
                    "query_role_counts": {"visual_temporal_support": 1},
                    "selected_evidence_query_role_counts": {
                        "visual_temporal_support": 1
                    },
                }
            },
            "results": [
                _memory(
                    "visual-temporal",
                    query_roles=("visual_temporal_support",),
                    lifted=True,
                ),
            ],
        },
        "evidence_bundle": {
            "items": [
                {
                    "id": "visual-temporal",
                    "role": "visual_temporal_support",
                }
            ]
        },
    }

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]

    assert breakdown["candidate_role_family_counts"] == {
        "temporal_support": 1,
        "visual_support": 1,
    }
    assert breakdown["selected_evidence_query_role_family_counts"] == {
        "temporal_support": 1,
        "visual_support": 1,
    }
    assert breakdown["role_families_without_selected_evidence"] == []
    assert breakdown["role_families_with_selected_evidence_only_in_fusion"] == [
        "temporal_support",
        "visual_support",
    ]
    assert breakdown["role_family_gap_count"] == 2
    assert breakdown["role_family_gaps"]["temporal_support"]["gap_reasons"] == [
        "selected_evidence_not_bundle_tagged"
    ]
    assert breakdown["role_family_gaps"]["visual_support"]["gap_reasons"] == [
        "selected_evidence_not_bundle_tagged"
    ]


def _memory(
    item_id: str,
    *,
    query_roles: tuple[str, ...],
    answerability_score: float = 0.7,
    source_locality_score: float = 0.7,
    bridge_query_hit: bool = False,
    lifted: bool = False,
    score_signals: dict[str, object] | None = None,
    policy_reason_codes: tuple[str, ...] = (),
    answerability_reason_codes: tuple[str, ...] = (),
    source_locality_reason_codes: tuple[str, ...] = (),
    candidate_fusion: dict[str, object] | None = None,
) -> dict[str, object]:
    candidate_features: dict[str, object] = {
        "query_roles": query_roles,
        "answerability_score": answerability_score,
        "source_locality_score": source_locality_score,
        "bridge_query_hit": bridge_query_hit,
    }
    if answerability_reason_codes:
        candidate_features["answerability_reason_codes"] = answerability_reason_codes
    if source_locality_reason_codes:
        candidate_features["source_locality_reason_codes"] = (
            source_locality_reason_codes
        )
    diagnostics: dict[str, object] = {
        "benchmark_candidate_features": candidate_features
    }
    if lifted:
        diagnostics["benchmark_rerank_boosted"] = True
    if score_signals is not None:
        diagnostics["score_signals"] = score_signals
    if candidate_fusion is not None:
        diagnostics["benchmark_candidate_fusion"] = candidate_fusion
    if policy_reason_codes:
        diagnostics["benchmark_rerank_policy"] = {
            "contributions": [
                {
                    "policy": "QueryRoleDiagnosticPolicy",
                    "score": 0.1,
                    "reason_codes": list(policy_reason_codes),
                }
            ]
        }
    return {
        "id": item_id,
        "metadata": {
            "diagnostics": diagnostics,
        },
    }
