from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
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


def test_query_role_effectiveness_reports_all_selected_query_role_families() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "multi-family-selected-roles",
                "retrieval": {
                    "results": [
                        _memory("reason", query_roles=("causal_support",)),
                        _memory("location", query_roles=("location_support",)),
                        _memory("preference", query_roles=("preference_support",)),
                        _memory(
                            "visual-time",
                            query_roles=("visual_temporal_support",),
                        ),
                    ],
                },
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "reason",
                            "role": "causal_support",
                            "query_roles": ["causal_support"],
                        },
                        {
                            "id": "location",
                            "role": "location_support",
                            "query_roles": ["location_support"],
                        },
                        {
                            "id": "preference",
                            "role": "preference_support",
                            "query_roles": ["preference_support"],
                        },
                        {
                            "id": "visual-time",
                            "role": "temporal_support",
                            "query_roles": ["visual_temporal_support"],
                        },
                    ],
                },
            },
        )
    )

    table = diagnostics["query_role_effectiveness_table"]

    expected_family_counts = {
        "causal_support": 1,
        "location_support": 1,
        "preference_support": 1,
        "relation_compact": 3,
        "temporal_support": 1,
        "visual_support": 1,
    }
    assert table["candidate_role_family_counts"] == expected_family_counts
    assert table["selected_item_role_family_counts"] == expected_family_counts
    assert table["role_stats"]["preference_support"][
        "selected_bundle_role_counts"
    ] == {"preference_support": 1}


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


def test_query_role_effectiveness_distinguishes_unmeasured_source_locality() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "role-locality",
                "retrieval": {
                    "results": [
                        _memory(
                            "unmeasured",
                            query_roles=("location_support",),
                            source_locality_score=0.0,
                        ),
                        _memory(
                            "measured",
                            query_roles=("location_support",),
                            source_locality_score=0.8,
                        ),
                    ],
                },
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "unmeasured",
                            "role": "location_support",
                            "query_roles": ["location_support"],
                            "source_locality_score": 0.0,
                        },
                        {
                            "id": "measured",
                            "role": "location_support",
                            "query_roles": ["location_support"],
                            "source_locality_score": 0.8,
                        },
                    ],
                },
            },
        )
    )

    stats = diagnostics["query_role_effectiveness_table"]["role_stats"][
        "location_support"
    ]

    assert stats["avg_candidate_source_locality_score"] == 0.4
    assert stats["avg_measured_candidate_source_locality_score"] == 0.8
    assert stats["candidate_unmeasured_source_locality_count"] == 1
    assert stats["avg_selected_source_locality_score"] == 0.4
    assert stats["avg_measured_selected_source_locality_score"] == 0.8
    assert stats["selected_unmeasured_source_locality_count"] == 1


def test_query_role_effectiveness_reports_selected_weakness_by_query_role() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "selected-weakness-roles",
                "retrieval": {
                    "results": [
                        _memory("low", query_roles=("location_support",)),
                        _memory("weak", query_roles=("temporal_support",)),
                    ],
                },
                "evidence_bundle": {
                    "items": [
                        {
                            "id": "low",
                            "role": "location_support",
                            "query_roles": ["location_support"],
                            "answerability_score": 0.4,
                            "source_locality_score": 0.8,
                        },
                        {
                            "id": "weak",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                            "answerability_score": 0.8,
                            "source_locality_score": 0.3,
                        },
                    ],
                },
            },
        )
    )

    table = diagnostics["query_role_effectiveness_table"]

    assert table["selected_low_answerability_role_counts"] == {
        "location_support": 1
    }
    assert table["selected_weak_source_locality_role_counts"] == {
        "temporal_support": 1
    }
    assert table["role_stats"]["location_support"][
        "selected_low_answerability_count"
    ] == 1
    assert table["role_stats"]["location_support"][
        "selected_weak_source_locality_count"
    ] == 0
    assert table["role_stats"]["temporal_support"][
        "selected_low_answerability_count"
    ] == 0
    assert table["role_stats"]["temporal_support"][
        "selected_weak_source_locality_count"
    ] == 1


def test_query_role_effectiveness_reports_required_role_candidate_query_gaps() -> None:
    item = {
        "case_id": "required-role-gap",
        "retrieval": {
            "results": [
                _memory("location", query_roles=("location_support",)),
                _memory("profile", query_roles=("compact_relation",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "location_support",
                "temporal_support",
            ],
            "missing_required_roles": ["temporal_support"],
            "items": [
                {
                    "id": "location",
                    "role": "location_support",
                    "query_roles": ["location_support"],
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["required_evidence_role_counts"] == {
        "location_support": 1,
        "primary": 1,
        "temporal_support": 1,
    }
    assert table["missing_required_role_candidate_query_counts"] == {
        "temporal_support": 1
    }
    assert table["required_roles_without_candidate_queries"] == [
        "temporal_support"
    ]
    assert table["missing_required_evidence_role_counts"] == {
        "temporal_support": 1
    }
    assert table["missing_required_evidence_roles"] == ["temporal_support"]
    assert table["required_role_coverage_gap_count"] == 1
    assert table["required_role_coverage_gap_counts"] == {
        "candidate_query": 1,
        "missing_required_evidence": 1,
        "selected_evidence_query": 1,
    }
    assert table["required_role_coverage_gap_samples"] == [
        {
            "case_id": "required-role-gap",
            "group": "",
            "required_role": "temporal_support",
            "gap_reasons": [
                "candidate_query",
                "selected_evidence_query",
                "missing_required_evidence",
            ],
            "required_query_family": "temporal_support",
            "required_selected_query_families": [
                "expanded_focus",
                "temporal_support",
            ],
            "candidate_query_role_families": [
                "location_support",
                "relation_compact",
            ],
            "selected_query_role_families": [],
            "selected_evidence_query_role_families": [],
        }
    ]

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]
    assert breakdown["required_evidence_role_counts"] == {
        "location_support": 1,
        "primary": 1,
        "temporal_support": 1,
    }
    assert breakdown["missing_required_role_candidate_query_counts"] == {
        "temporal_support": 1
    }
    assert breakdown["required_roles_without_candidate_queries"] == [
        "temporal_support"
    ]
    assert breakdown["missing_required_evidence_roles"] == ["temporal_support"]
    assert breakdown["required_role_coverage_gap_counts"] == {
        "candidate_query": 1,
        "missing_required_evidence": 1,
        "selected_evidence_query": 1,
    }
    assert breakdown["required_role_coverage_gap_samples"] == (
        table["required_role_coverage_gap_samples"]
    )


def test_query_role_effectiveness_reports_required_role_selected_query_gaps() -> None:
    item = {
        "case_id": "required-selected-query-gap",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["base_query"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "temporal_support",
                        ],
                    },
                },
            },
            "results": [
                _memory("temporal", query_roles=("temporal_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "temporal_support",
            ],
            "items": [
                {
                    "id": "temporal",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["missing_required_role_candidate_query_counts"] == {}
    assert table["required_roles_without_candidate_queries"] == []
    assert table["missing_required_role_selected_query_counts"] == {
        "temporal_support": 1
    }
    assert table["required_roles_without_selected_queries"] == [
        "temporal_support"
    ]
    assert table["required_role_coverage_gap_count"] == 1
    assert table["required_role_coverage_gap_counts"] == {"selected_query": 1}
    assert table["required_role_coverage_gap_samples"] == [
        {
            "case_id": "required-selected-query-gap",
            "group": "",
            "required_role": "temporal_support",
            "gap_reasons": ["selected_query"],
            "required_query_family": "temporal_support",
            "required_selected_query_families": [
                "expanded_focus",
                "temporal_support",
            ],
            "candidate_query_role_families": ["temporal_support"],
            "selected_query_role_families": ["base_query"],
            "selected_evidence_query_role_families": ["temporal_support"],
        }
    ]

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]
    assert breakdown["missing_required_role_selected_query_counts"] == {
        "temporal_support": 1
    }
    assert breakdown["required_roles_without_selected_queries"] == [
        "temporal_support"
    ]
    assert breakdown["required_role_coverage_gap_count"] == 1
    assert breakdown["required_role_coverage_gap_counts"] == {"selected_query": 1}


def test_query_role_effectiveness_distinguishes_unrelated_selected_evidence_queries() -> None:
    unrelated_item = {
        "case_id": "unrelated-selected-query-role",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["temporal_support"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "temporal_support",
                        ],
                    },
                },
            },
            "results": [
                _memory("temporal-candidate", query_roles=("temporal_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "temporal_support",
            ],
            "items": [
                {
                    "id": "primary-selected",
                    "role": "primary",
                    "query_roles": ["temporal_support"],
                }
            ],
        },
    }
    covered_item = {
        "case_id": "expected-selected-query-role",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["temporal_support"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "temporal_support",
                        ],
                    },
                },
            },
            "results": [
                _memory("temporal-candidate", query_roles=("temporal_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "temporal_support",
            ],
            "items": [
                {
                    "id": "temporal-selected",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((unrelated_item, covered_item))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["missing_required_role_selected_query_counts"] == {}
    assert table["required_roles_without_selected_queries"] == []
    assert table["required_role_selected_evidence_query_counts"] == {
        "temporal_support": 1
    }
    assert table["missing_required_role_selected_evidence_query_counts"] == {
        "temporal_support": 1
    }
    assert table["required_roles_without_selected_evidence_queries"] == [
        "temporal_support"
    ]
    assert table["required_role_coverage_gap_count"] == 1
    assert table["required_role_coverage_gap_counts"] == {
        "selected_evidence_query": 1
    }
    assert table["required_role_coverage_gap_samples"][0] == {
        "case_id": "unrelated-selected-query-role",
        "group": "",
        "required_role": "temporal_support",
        "gap_reasons": ["selected_evidence_query"],
        "required_query_family": "temporal_support",
        "required_selected_query_families": [
            "expanded_focus",
            "temporal_support",
        ],
        "candidate_query_role_families": ["temporal_support"],
        "selected_query_role_families": ["temporal_support"],
        "selected_evidence_query_role_families": [],
    }

    breakdown = fast_gate_metrics(
        (unrelated_item, covered_item),
        expected_case_count=2,
    )["query_role_gap_breakdown"]
    assert breakdown["required_role_selected_evidence_query_counts"] == {
        "temporal_support": 1
    }
    assert breakdown["missing_required_role_selected_evidence_query_counts"] == {
        "temporal_support": 1
    }
    assert breakdown["required_roles_without_selected_evidence_queries"] == [
        "temporal_support"
    ]
    assert breakdown["required_role_coverage_gap_counts"] == {
        "selected_evidence_query": 1
    }
    assert breakdown["required_role_coverage_gap_samples"] == (
        table["required_role_coverage_gap_samples"]
    )


def test_query_role_effectiveness_maps_generic_support_role_by_query_family() -> None:
    item = {
        "case_id": "generic-support-selected-query-role",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["location_support"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "location_support",
                        ],
                    },
                },
            },
            "results": [
                _memory("location", query_roles=("location_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "location_support",
            ],
            "items": [
                {
                    "id": "location",
                    "role": "supporting",
                    "query_roles": ["location_support"],
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert table["missing_required_role_selected_evidence_query_counts"] == {}
    assert table["required_roles_without_selected_evidence_queries"] == []

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]
    assert breakdown["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert breakdown["missing_required_role_selected_evidence_query_counts"] == {}


def test_query_role_effectiveness_uses_fusion_selected_evidence_query_roles() -> None:
    item = {
        "case_id": "fusion-selected-evidence-required-role",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["location_support"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "location_support",
                        ],
                    },
                },
                "multi_query_merge": {
                    "selected_evidence_query_role_counts": {
                        "location_support": 1,
                    },
                },
            },
            "results": [
                _memory("location-candidate", query_roles=("location_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "location_support",
            ],
            "items": [
                {
                    "id": "location-selected",
                    "role": "location_support",
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert table["missing_required_role_selected_evidence_query_counts"] == {}
    assert table["required_roles_without_selected_evidence_queries"] == []

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]
    assert breakdown["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert breakdown["missing_required_role_selected_evidence_query_counts"] == {}
    assert breakdown["required_roles_without_selected_evidence_queries"] == []


def test_query_role_effectiveness_uses_fusion_selected_evidence_query_role_sample() -> None:
    item = {
        "case_id": "fusion-selected-evidence-query-role",
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_role_families": ["location_support"],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": [
                            "primary",
                            "location_support",
                        ],
                    },
                },
                "multi_query_merge": {
                    "evidence_selection_samples": [
                        {
                            "selected_evidence_item_id": "location-selected",
                            "selected_evidence_query_role": "location_support",
                        }
                    ],
                },
            },
            "results": [
                _memory("location-selected", query_roles=("location_support",)),
            ],
        },
        "evidence_bundle": {
            "required_roles": [
                "primary",
                "location_support",
            ],
            "items": [
                {
                    "id": "location-selected",
                    "role": "location_support",
                }
            ],
        },
    }

    diagnostics = quality_diagnostics((item,))
    table = diagnostics["query_role_effectiveness_table"]

    assert table["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert table["missing_required_role_selected_evidence_query_counts"] == {}
    assert table["required_roles_without_selected_evidence_queries"] == []

    breakdown = fast_gate_metrics((item,), expected_case_count=1)[
        "query_role_gap_breakdown"
    ]
    assert breakdown["required_role_selected_evidence_query_counts"] == {
        "location_support": 1
    }
    assert breakdown["missing_required_role_selected_evidence_query_counts"] == {}
    assert breakdown["required_roles_without_selected_evidence_queries"] == []


def test_query_role_effectiveness_accepts_compact_query_for_profile_required_role() -> None:
    diagnostics = quality_diagnostics(
        (
            {
                "case_id": "profile-required-role-covered",
                "retrieval": {
                    "results": [
                        _memory("profile", query_roles=("compact_relation",)),
                    ],
                },
                "evidence_bundle": {
                    "required_roles": ["primary", "health_support"],
                    "missing_required_roles": [],
                    "items": [
                        {
                            "id": "profile",
                            "role": "health_support",
                            "query_roles": ["compact_relation"],
                        }
                    ],
                },
            },
        )
    )

    table = diagnostics["query_role_effectiveness_table"]

    assert table["required_evidence_role_counts"] == {
        "health_support": 1,
        "primary": 1,
    }
    assert table["missing_required_role_candidate_query_counts"] == {}
    assert table["required_roles_without_candidate_queries"] == []


def test_query_plan_integrity_requires_answer_shape_query_families() -> None:
    items = (
        _query_plan_item(
            "missing-list",
            required_role="list_support",
            selected_role_families=("base_query",),
        ),
        _query_plan_item(
            "has-list",
            required_role="list_support",
            selected_role_families=("base_query", "list_support"),
        ),
        _query_plan_item(
            "missing-value",
            required_role="value_support",
            selected_role_families=("base_query", "relation_compact"),
        ),
        _query_plan_item(
            "has-value",
            required_role="value_support",
            selected_role_families=("base_query", "value_support"),
        ),
        _query_plan_item(
            "missing-count",
            required_role="count_support",
            selected_role_families=("base_query",),
        ),
        _query_plan_item(
            "has-count",
            required_role="count_support",
            selected_role_families=("base_query", "count_support"),
        ),
    )

    table = quality_diagnostics(items)["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "count_support": 1,
        "list_support": 1,
        "value_support": 1,
    }
    assert [
        sample["case_id"]
        for sample in table["samples"]
        if "missing_evidence_role_query_family" in sample["gap_reasons"]
    ] == ["missing-list", "missing-value", "missing-count"]


def test_query_plan_integrity_requires_negative_support_query_family() -> None:
    items = (
        _query_plan_item(
            "missing-negative",
            required_role="negative_support",
            selected_role_families=("base_query",),
        ),
        _query_plan_item(
            "has-negative",
            required_role="negative_support",
            selected_role_families=("base_query", "negative_support"),
        ),
    )

    table = quality_diagnostics(items)["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "negative_support": 1
    }
    samples = [
        sample
        for sample in table["samples"]
        if "missing_evidence_role_query_family" in sample["gap_reasons"]
    ]
    assert [sample["case_id"] for sample in samples] == ["missing-negative"]
    assert samples[0]["missing_evidence_role_query_families"] == (
        "negative_support",
    )


def _memory(
    item_id: str,
    *,
    query_roles: tuple[str, ...],
    answerability_score: float = 0.7,
    source_locality_score: float = 0.7,
) -> dict[str, object]:
    return {
        "id": item_id,
        "metadata": {
            "diagnostics": {
                "benchmark_candidate_features": {
                    "query_roles": query_roles,
                    "answerability_score": answerability_score,
                    "source_locality_score": source_locality_score,
                }
            }
        },
    }


def _query_plan_item(
    case_id: str,
    *,
    required_role: str,
    selected_role_families: tuple[str, ...],
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "retrieval": {
            "metadata": {
                "query_decomposition": {
                    "query_plan": {
                        "schema_version": "query_plan.v2",
                        "selected_query_count": len(selected_role_families),
                        "dropped_query_count": 0,
                        "selected_roles": list(selected_role_families),
                        "selected_role_families": list(selected_role_families),
                        "missing_recommended_role_families": [],
                    },
                    "query_profile": {
                        "bundle_evidence_roles": ["primary", required_role],
                    },
                },
            },
            "results": [],
        },
        "evidence_bundle": {},
    }
