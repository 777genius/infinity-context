from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    quality_diagnostics,
)


def test_query_role_effectiveness_uses_planner_role_families() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "role-family-alignment",
                "retrieval": {
                    "results": [
                        _memory("expanded", query_roles=("expanded_focus",)),
                        _memory("compact", query_roles=("compact_relation",)),
                        _memory(
                            "communication",
                            query_roles=("communication_support",),
                        ),
                    ],
                },
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "compact",
                            "role": "communication_support",
                            "query_roles": ["compact_relation"],
                            "answerability_score": 0.82,
                        },
                        {
                            "id": "communication",
                            "role": "communication_support",
                            "query_roles": ["communication_support"],
                            "answerability_score": 0.9,
                        },
                    ],
                },
            },
        )
    )

    table = diagnostics["query_role_effectiveness_table"]

    assert table["candidate_role_family_counts"] == {
        "expanded_focus": 1,
        "relation_compact": 2,
    }
    assert table["selected_item_role_family_counts"] == {"relation_compact": 2}
    assert table["role_stats"]["compact_relation"]["selected_bundle_role_counts"] == {
        "communication_support": 1
    }
    assert table["role_stats"]["communication_support"][
        "selected_bundle_role_counts"
    ] == {"communication_support": 1}


def test_query_role_effectiveness_distinguishes_unmeasured_answerability() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "role-answerability",
                "retrieval": {
                    "results": [
                        _memory(
                            "unmeasured",
                            query_roles=("temporal_support",),
                            answerability_score=0.0,
                        ),
                        _memory(
                            "measured",
                            query_roles=("temporal_support",),
                            answerability_score=0.8,
                        ),
                    ],
                },
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "unmeasured",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                            "answerability_score": 0.0,
                        },
                        {
                            "id": "measured",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                            "answerability_score": 0.8,
                        },
                    ],
                },
            },
        )
    )

    stats = diagnostics["query_role_effectiveness_table"]["role_stats"][
        "temporal_support"
    ]

    assert stats["avg_candidate_answerability_score"] == 0.4
    assert stats["avg_measured_candidate_answerability_score"] == 0.8
    assert stats["candidate_unmeasured_answerability_count"] == 1
    assert stats["avg_selected_answerability_score"] == 0.4
    assert stats["avg_measured_selected_answerability_score"] == 0.8
    assert stats["selected_unmeasured_answerability_count"] == 1


def _memory(
    item_id: str,
    *,
    query_roles: tuple[str, ...],
    answerability_score: float = 0.7,
) -> dict[str, object]:
    return {
        "id": item_id,
        "metadata": {
            "diagnostics": {
                "benchmark_candidate_features": {
                    "query_roles": query_roles,
                    "answerability_score": answerability_score,
                }
            }
        },
    }
