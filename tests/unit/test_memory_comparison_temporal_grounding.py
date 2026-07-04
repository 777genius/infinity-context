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
