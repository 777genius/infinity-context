from __future__ import annotations

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
            "source_refs": ["locomo:conv-1:session_4"],
            "missing_source_window": True,
        }
    ]


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
