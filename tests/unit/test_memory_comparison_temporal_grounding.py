from __future__ import annotations

import json

from infinity_context_server.memory_comparison_benchmark import _compact_fast_gate_summary
from infinity_context_server.memory_comparison_quality_diagnostics import (
    quality_diagnostics,
)

from tests.unit.test_memory_comparison_quality_diagnostics import (
    _item,
    _retrieval_payload,
)


def test_quality_diagnostics_reports_temporal_grounding_gaps() -> None:
    grounded_retrieval = _retrieval_payload(
        evidence_need=("temporal_support",),
        bundle_evidence_roles=("primary", "temporal_sequence_support"),
        relation_categories=("temporal",),
        policy_score=0.2,
        memory_text=(
            "session_4 date: 9 October, 2022\n"
            "D4:3 Riley said the workshop happened after the earlier call."
        ),
        candidate_features={
            "query_roles": ["temporal_sequence_support"],
            "time_intent_kind": "temporal_sequence",
            "has_temporal_sequence_surface": True,
        },
    )
    grounded_retrieval["results"][0]["source_refs"] = [
        "locomo:conv-1:session_4:D4:3:turn"
    ]
    grounded_retrieval["results"][0]["metadata"]["diagnostics"][
        "time_start_ms"
    ] = 100
    grounded_retrieval["results"][0]["metadata"]["diagnostics"]["time_end_ms"] = 200

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-grounded",
                group="temporal",
                retrieval=grounded_retrieval,
                evidence_bundle={
                    "items": [
                        {
                            "id": "grounded",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo:conv-1:session_4:D4:3:turn"
                            ],
                            "text": "session_4 date: 9 October, 2022",
                            "time_start_ms": 100,
                            "time_end_ms": 200,
                        }
                    ]
                },
            ),
            _item(
                case_id="temporal-ungrounded",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                    candidate_features={
                        "query_roles": ["temporal_support"],
                        "time_intent_kind": "relative_time",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "ungrounded",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                        }
                    ]
                },
            ),
            _item(
                case_id="non-temporal-with-locomo-ref",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary",),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "items": [
                        {
                            "role": "primary",
                            "source_refs": ["locomo:conv-1:session_2:D2:1:turn"],
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["schema_version"] == "temporal_grounding.v1"
    assert table["temporal_case_count"] == 2
    assert table["retrieval_candidate_count"] == 2
    assert table["retrieval_session_boundary_candidate_count"] == 1
    assert table["retrieval_date_grounded_candidate_count"] == 1
    assert table["retrieval_range_grounded_candidate_count"] == 1
    assert table["retrieval_temporal_order_candidate_count"] == 1
    assert table["selected_item_count"] == 2
    assert table["selected_session_boundary_item_count"] == 1
    assert table["selected_date_grounded_item_count"] == 1
    assert table["selected_range_grounded_item_count"] == 1
    assert table["selected_temporal_order_item_count"] == 1
    assert table["selected_ungrounded_temporal_item_count"] == 1
    assert table["selected_grounding_gap_case_count"] == 1
    assert table["selected_source_window_item_count"] == 1
    assert table["selected_missing_source_window_item_count"] == 1
    assert table["selected_source_window_gap_case_count"] == 1
    assert table["selected_grounding_gap_samples"] == [
        {
            "case_id": "temporal-ungrounded",
            "group": "temporal",
            "item_id": "ungrounded",
            "role": "temporal_support",
            "query_roles": ["temporal_support"],
            "source_refs": [],
            "missing_grounding": ["session_boundary", "date_or_range"],
        }
    ]
    assert table["selected_source_window_gap_samples"] == [
        {
            "case_id": "temporal-ungrounded",
            "group": "temporal",
            "item_id": "ungrounded",
            "role": "temporal_support",
            "query_roles": ["temporal_support"],
            "source_refs": [],
            "missing_source_window": True,
        }
    ]


def test_temporal_grounding_counts_relative_date_surfaces_as_grounded_ranges() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("temporal_support",),
        bundle_evidence_roles=("primary", "relative_temporal_support"),
        relation_categories=("temporal",),
        policy_score=0.2,
        memory_text="Morgan checked in yesterday afternoon.",
        candidate_features={
            "query_roles": ["relative_temporal_support"],
            "time_intent_kind": "relative_time",
            "has_relative_time_surface": True,
        },
    )
    retrieval["results"][0]["source_refs"] = [
        "locomo:conv-1:session_7:D7:2:turn"
    ]

    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-relative-grounded",
                group="temporal",
                retrieval=retrieval,
                evidence_bundle={
                    "items": [
                        {
                            "id": "relative-grounded",
                            "role": "relative_temporal_support",
                            "query_roles": ["relative_temporal_support"],
                            "source_refs": [
                                "locomo:conv-1:session_7:D7:2:turn"
                            ],
                            "text": "Morgan checked in yesterday afternoon.",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["retrieval_relative_date_grounded_candidate_count"] == 1
    assert table["retrieval_range_grounded_candidate_count"] == 1
    assert table["selected_relative_date_grounded_item_count"] == 1
    assert table["selected_range_grounded_item_count"] == 1
    assert table["selected_strong_temporal_grounding_item_count"] == 1
    assert table["selected_temporal_grounding_issue_item_count"] == 0


def test_temporal_grounding_counts_exact_turn_refs_as_source_windows() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-exact-turn-ref",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "relative_temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ["relative_temporal_support"],
                        "time_intent_kind": "relative_time",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "exact-turn-ref",
                            "role": "relative_temporal_support",
                            "query_roles": ["relative_temporal_support"],
                            "source_refs": ["D7:2"],
                            "text": "Morgan checked in yesterday afternoon.",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_source_window_item_count"] == 1
    assert table["selected_missing_source_window_item_count"] == 0
    assert table["selected_strong_temporal_grounding_item_count"] == 1
    assert table["selected_temporal_grounding_issue_item_count"] == 0
    assert table["selected_temporal_grounding_issue_reason_counts"] == {}


def test_temporal_grounding_counts_hyphenated_raw_refs_as_source_windows() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-hyphenated-raw-ref",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_sequence_support"),
                    relation_categories=("temporal",),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ["temporal_sequence_support"],
                        "time_intent_kind": "temporal_sequence",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "hyphenated-raw-ref",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo-conv-private-session_8-D8-3-turn-secret"
                            ],
                            "text": "session_8 date: 9 October, 2022",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_source_window_item_count"] == 1
    assert table["selected_missing_source_window_item_count"] == 0
    assert table["selected_strong_temporal_grounding_item_count"] == 1
    assert table["selected_temporal_grounding_issue_item_count"] == 0
    assert table["selected_temporal_grounding_issue_reason_counts"] == {}


def test_temporal_grounding_counts_hyphenated_exact_turn_refs_as_session_boundary() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-hyphenated-exact-turn-ref",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_sequence_support"),
                    relation_categories=("temporal",),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ["temporal_sequence_support"],
                        "time_intent_kind": "temporal_sequence",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "hyphenated-exact-turn-ref",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": ["D7-2"],
                            "text": "date: 9 October, 2022 D7-2",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_source_window_item_count"] == 1
    assert table["selected_session_boundary_item_count"] == 1
    assert table["selected_temporal_order_item_count"] == 1
    assert table["selected_strong_temporal_grounding_item_count"] == 1
    assert table["selected_temporal_grounding_issue_item_count"] == 0


def test_temporal_grounding_keeps_exact_turn_window_unqualified() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-exact-turn-with-session-text",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_sequence_support"),
                    relation_categories=("temporal",),
                    policy_score=0.2,
                    candidate_features={
                        "query_roles": ["temporal_sequence_support"],
                        "time_intent_kind": "temporal_sequence",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "exact-turn-with-session-text",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": ["D7:2"],
                            "text": "session_9 D7:2 Morgan checked in.",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_source_window_item_count"] == 1
    assert table["selected_missing_source_window_item_count"] == 0
    assert table["selected_strong_temporal_grounding_item_count"] == 0
    assert table["selected_temporal_grounding_issue_reason_counts"] == {
        "missing_date_or_range": 1,
        "weak_session_boundary_without_date_or_range": 1,
        "weak_source_window_without_date_or_range": 1,
    }
    assert table["selected_temporal_grounding_issue_samples"] == [
        {
            "case_id": "temporal-exact-turn-with-session-text",
            "group": "temporal",
            "item_id": "exact-turn-with-session-text",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "source_refs": ["D7:2"],
            "issue_reasons": [
                "missing_date_or_range",
                "weak_source_window_without_date_or_range",
                "weak_session_boundary_without_date_or_range",
            ],
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": False,
                "temporal_order": True,
            },
        }
    ]


def test_temporal_grounding_reports_source_window_audit_gap_separately() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-session-only",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                    candidate_features={
                        "query_roles": ["temporal_support"],
                        "time_intent_kind": "temporal_lookup",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "session-only",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                            "source_refs": ["locomo:conv-1:session_4"],
                            "text": "session_4 date: 9 October, 2022",
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_ungrounded_temporal_item_count"] == 0
    assert table["selected_grounding_gap_case_count"] == 0
    assert table["selected_source_window_item_count"] == 0
    assert table["selected_missing_source_window_item_count"] == 1
    assert table["selected_source_window_gap_case_count"] == 1
    assert table["selected_source_window_gap_samples"] == [
        {
            "case_id": "temporal-session-only",
            "group": "temporal",
            "item_id": "session-only",
            "role": "temporal_support",
            "query_roles": ["temporal_support"],
            "source_refs": [],
            "source_ref_count": 1,
            "missing_source_window": True,
        }
    ]


def test_compact_fast_gate_summary_reports_retrieval_relative_date_counts() -> None:
    retrieval = _retrieval_payload(
        evidence_need=("temporal_support",),
        bundle_evidence_roles=("primary", "relative_temporal_support"),
        relation_categories=("temporal",),
        policy_score=0.2,
        memory_text="Morgan checked in yesterday afternoon.",
        candidate_features={
            "query_roles": ["relative_temporal_support"],
            "time_intent_kind": "relative_time",
            "has_relative_time_surface": True,
        },
    )
    retrieval["results"][0]["source_refs"] = [
        "locomo:conv-1:session_7:D7:2:turn"
    ]

    summary = _compact_fast_gate_summary(
        (
            _item(
                case_id="temporal-relative-compact",
                group="temporal",
                retrieval=retrieval,
                evidence_bundle={
                    "items": [
                        {
                            "id": "relative-grounded",
                            "role": "relative_temporal_support",
                            "query_roles": ["relative_temporal_support"],
                            "source_refs": [
                                "locomo:conv-1:session_7:D7:2:turn"
                            ],
                            "text": "Morgan checked in yesterday afternoon.",
                        }
                    ]
                },
            ),
        )
    )

    counts = summary["temporal_grounding_counts"]
    assert counts["retrieval_relative_date_grounded_candidate_count"] == 1
    assert counts["selected_relative_date_grounded_item_count"] == 1


def test_compact_temporal_grounding_samples_filter_unsafe_refs_and_bound_text() -> None:
    long_id = "temporal-item-" + ("x" * 200)
    private_refs = [
        f"locomo:conv-private:session_8:D8:{turn}:turn-secret"
        for turn in range(1, 5)
    ]

    item = _item(
        case_id="temporal-private-refs",
        group="temporal",
        retrieval=_retrieval_payload(
            evidence_need=("temporal_support",),
            bundle_evidence_roles=("primary", "temporal_sequence_support"),
            relation_categories=("temporal",),
            policy_score=0.0,
            candidate_features={
                "query_roles": ["temporal_sequence_support"],
                "time_intent_kind": "temporal_sequence",
            },
        ),
        evidence_bundle={
            "items": [
                {
                    "id": long_id,
                    "role": "temporal_sequence_support",
                    "query_roles": ["temporal_sequence_support"],
                    "source_refs": private_refs,
                }
            ]
        },
    )

    diagnostics = quality_diagnostics((item,))
    table_sample = diagnostics["temporal_grounding_table"][
        "selected_temporal_grounding_issue_samples"
    ][0]
    summary = _compact_fast_gate_summary((item,))
    compact_sample = summary["temporal_grounding_issue_samples"][0]

    assert table_sample["source_refs"] == [
        "source_session_turn_refs:session_8:D8:1",
        "source_turn_refs:D8:1",
        "source_session_turn_refs:session_8:D8:2",
        "source_turn_refs:D8:2",
        "source_session_turn_refs:session_8:D8:3",
    ]
    assert compact_sample["source_refs"] == table_sample["source_refs"]
    assert compact_sample["item_id"] == f"{long_id[:125]}..."
    serialized = json.dumps({"diagnostics": diagnostics, "summary": summary})
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_temporal_grounding_samples_filter_long_exact_refs_and_report_count() -> None:
    long_ref = f"D1:{'9' * 120}"
    item = _item(
        case_id="temporal-long-exact-ref",
        group="temporal",
        retrieval=_retrieval_payload(
            evidence_need=("temporal_support",),
            bundle_evidence_roles=("primary", "temporal_support"),
            relation_categories=("temporal",),
            policy_score=0.0,
            candidate_features={
                "query_roles": ["temporal_support"],
                "time_intent_kind": "temporal_lookup",
            },
        ),
        evidence_bundle={
            "items": [
                {
                    "id": "long-exact-ref",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                    "source_refs": [long_ref, "D1:2", "D1:2"],
                }
            ]
        },
    )

    diagnostics = quality_diagnostics((item,))
    table_sample = diagnostics["temporal_grounding_table"][
        "selected_temporal_grounding_issue_samples"
    ][0]
    compact_sample = _compact_fast_gate_summary((item,))[
        "temporal_grounding_issue_samples"
    ][0]

    assert table_sample["source_refs"] == ["D1:2"]
    assert table_sample["source_ref_count"] == 2
    assert compact_sample["source_refs"] == ["D1:2"]
    assert compact_sample["source_ref_count"] == 2
    serialized = json.dumps({"diagnostics": diagnostics, "summary": compact_sample})
    assert long_ref not in serialized


def test_temporal_grounding_reports_source_identity_mismatch() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-source-mismatch",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_sequence_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                    candidate_features={
                        "query_roles": ["temporal_sequence_support"],
                        "time_intent_kind": "temporal_sequence",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "mismatched-turn",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo:conv-1:session_4:D4:3:turn"
                            ],
                            "text": (
                                "session_5 date: 9 October, 2022 "
                                "D4:3 Riley said the workshop happened later."
                            ),
                        }
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_strong_temporal_grounding_item_count"] == 0
    assert table["selected_temporal_grounding_issue_item_count"] == 1
    assert table["selected_temporal_grounding_issue_reason_counts"] == {
        "source_identity_mismatch": 1
    }
    assert table["selected_temporal_grounding_issue_samples"] == [
        {
            "case_id": "temporal-source-mismatch",
            "group": "temporal",
            "item_id": "mismatched-turn",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "source_refs": [
                "source_session_turn_refs:session_4:D4:3",
                "source_turn_refs:D4:3",
            ],
            "issue_reasons": ["source_identity_mismatch"],
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": True,
                "temporal_order": True,
            },
            "source_identity_gap_codes": [
                "source_text_session_turn_mismatch"
            ],
        }
    ]


def test_compact_fast_gate_reports_temporal_source_identity_mismatch_safely() -> None:
    raw_private_ref = "locomo:conv-private:session_4:D4:3:turn-secret"
    item = _item(
        case_id="temporal-source-mismatch-compact",
        group="temporal",
        retrieval=_retrieval_payload(
            evidence_need=("temporal_support",),
            bundle_evidence_roles=("primary", "temporal_sequence_support"),
            relation_categories=("temporal",),
            policy_score=0.2,
            candidate_features={
                "query_roles": ["temporal_sequence_support"],
                "time_intent_kind": "temporal_sequence",
            },
        ),
        evidence_bundle={
            "bundle_complete": True,
            "item_count": 1,
            "primary_evidence_count": 1,
            "supporting_evidence_count": 0,
            "items": [
                {
                    "id": "mismatched-turn",
                    "role": "primary",
                    "query_roles": ["temporal_sequence_support"],
                    "source_refs": [raw_private_ref],
                    "text": (
                        "session_5 date: 9 October, 2022 "
                        "D4:3 Riley said the workshop happened later."
                    ),
                }
            ],
        },
    )

    summary = _compact_fast_gate_summary((item,))

    assert summary["temporal_grounding_counts"]["issue_reason_counts"] == {
        "source_identity_mismatch": 1
    }
    assert any(
        gap["category"] == "temporal_grounding"
        and gap["gap"] == "source_identity_mismatch"
        for gap in summary["top_actionable_gaps"]
    )
    assert summary["temporal_grounding_issue_samples"] == [
        {
            "case_id": "temporal-source-mismatch-compact",
            "group": "temporal",
            "item_id": "mismatched-turn",
            "role": "primary",
            "query_roles": ["temporal_sequence_support"],
            "issue_reasons": ["source_identity_mismatch"],
            "source_identity_gap_codes": [
                "source_text_session_turn_mismatch"
            ],
            "source_refs": [
                "source_session_turn_refs:session_4:D4:3",
                "source_turn_refs:D4:3",
            ],
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": True,
                "temporal_order": True,
            },
        }
    ]
    serialized = json.dumps(summary)
    assert raw_private_ref not in serialized
    assert "locomo:conv-private" not in serialized
    assert "turn-secret" not in serialized


def test_temporal_grounding_summarizes_missing_weak_and_conflicting_issues() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-issues",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_sequence_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                    candidate_features={
                        "query_roles": ["temporal_sequence_support"],
                        "time_intent_kind": "temporal_sequence",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": "strong",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo:conv-1:session_4:D4:3:turn"
                            ],
                            "text": "session_4 date: 9 October, 2022",
                        },
                        {
                            "id": "weak-source-window-only",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo:conv-1:session_5:D5:2:turn"
                            ],
                        },
                        {
                            "id": "conflicting",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                            "source_refs": [
                                "locomo:conv-1:session_6:D6:4:turn"
                            ],
                            "text": "session_6 date: 10 October, 2022",
                            "metadata": {
                                "diagnostics": {"stale_reason": "superseded"}
                            },
                        },
                        {
                            "id": "missing",
                            "role": "temporal_sequence_support",
                            "query_roles": ["temporal_sequence_support"],
                        },
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_strong_temporal_grounding_item_count"] == 1
    assert table["selected_temporal_grounding_issue_item_count"] == 3
    assert table["selected_temporal_grounding_issue_case_count"] == 1
    assert table["selected_missing_temporal_grounding_issue_item_count"] == 2
    assert table["selected_weak_temporal_grounding_issue_item_count"] == 1
    assert table["selected_conflicting_temporal_grounding_issue_item_count"] == 1
    assert table["selected_temporal_grounding_issue_reason_counts"] == {
        "conflicting_or_stale": 1,
        "missing_date_or_range": 2,
        "missing_session_boundary": 1,
        "missing_source_window": 1,
        "missing_temporal_grounding": 1,
        "weak_session_boundary_without_date_or_range": 1,
        "weak_source_window_without_date_or_range": 1,
    }
    assert table["selected_temporal_grounding_issue_sample_limit"] == 10
    assert table["selected_temporal_grounding_issue_sample_count"] == 3
    assert table["selected_temporal_grounding_issue_sample_omitted_count"] == 0
    assert table["selected_temporal_grounding_issue_samples"] == [
        {
            "case_id": "temporal-issues",
            "group": "temporal",
            "item_id": "weak-source-window-only",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "source_refs": [
                "source_session_turn_refs:session_5:D5:2",
                "source_turn_refs:D5:2",
            ],
            "issue_reasons": [
                "missing_date_or_range",
                "weak_source_window_without_date_or_range",
                "weak_session_boundary_without_date_or_range",
            ],
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": False,
                "temporal_order": True,
            },
        },
        {
            "case_id": "temporal-issues",
            "group": "temporal",
            "item_id": "conflicting",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "source_refs": [
                "source_session_turn_refs:session_6:D6:4",
                "source_turn_refs:D6:4",
            ],
            "issue_reasons": ["conflicting_or_stale"],
            "grounding_signals": {
                "source_window": True,
                "session_boundary": True,
                "date_or_range": True,
                "temporal_order": True,
            },
        },
        {
            "case_id": "temporal-issues",
            "group": "temporal",
            "item_id": "missing",
            "role": "temporal_sequence_support",
            "query_roles": ["temporal_sequence_support"],
            "source_refs": [],
            "issue_reasons": [
                "missing_source_window",
                "missing_session_boundary",
                "missing_date_or_range",
                "missing_temporal_grounding",
            ],
            "grounding_signals": {
                "source_window": False,
                "session_boundary": False,
                "date_or_range": False,
                "temporal_order": False,
            },
        },
    ]


def test_temporal_grounding_reports_issue_sample_omitted_count() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="temporal-many-issues",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                    candidate_features={
                        "query_roles": ["temporal_support"],
                        "time_intent_kind": "temporal_lookup",
                    },
                ),
                evidence_bundle={
                    "items": [
                        {
                            "id": f"temporal-gap-{index}",
                            "role": "temporal_support",
                            "query_roles": ["temporal_support"],
                        }
                        for index in range(12)
                    ]
                },
            ),
        )
    )

    table = diagnostics["temporal_grounding_table"]

    assert table["selected_temporal_grounding_issue_item_count"] == 12
    assert table["selected_temporal_grounding_issue_sample_limit"] == 10
    assert table["selected_temporal_grounding_issue_sample_count"] == 10
    assert table["selected_temporal_grounding_issue_sample_omitted_count"] == 2
    assert len(table["selected_temporal_grounding_issue_samples"]) == 10
