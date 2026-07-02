from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
)


def test_fast_gate_metrics_reports_missing_contrast_evidence_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-contrast",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D7:5"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_contrast"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {"missing_contrast": 1}
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_contrast",
    ]


def test_fast_gate_metrics_rejects_contrast_role_label_without_surface() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="label-only-contrast",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "contrast",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["role:contrast"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_contrast"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {"missing_contrast": 1}
    assert "missing_contrast" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_contrast_surface_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-contrast-surface",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "contrast_surface": True,
                            "planner_reason_codes": ["contrast_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_contrast" not in breakdown["reason_counts"]
    assert "missing_contrast" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_rejects_stale_or_negation_without_current_contrast() -> None:
    for surface_key, reason_code in (
        ("stale_surface", "stale_surface"),
        ("negation_surface", "negation_surface"),
    ):
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"{surface_key}-only",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=("contrast",),
                        bundle_evidence_roles=("primary", "contrast"),
                        relation_categories=("contrast",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "contrast",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                                surface_key: True,
                                "planner_reason_codes": [reason_code],
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_contrast"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_contrast": 1
        }
        assert "missing_contrast" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_currentness_with_stale_as_contrast() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="current-and-stale",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("contrast",),
                    bundle_evidence_roles=("primary", "contrast"),
                    relation_categories=("contrast",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "contrast",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "currentness_surface": True,
                            "stale_surface": True,
                            "planner_reason_codes": [
                                "currentness_surface",
                                "stale_surface",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_contrast" not in breakdown["reason_counts"]
    assert "missing_contrast" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_rejects_temporal_role_label_without_surface() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="label-only-temporal",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "bundle_planner": {
                        "role_counts": {
                            "primary": 1,
                            "temporal_support": 1,
                        }
                    },
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["temporal_support"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_rejects_currentness_for_duration_temporal_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="duration-currentness-only",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "time_intent_kind": "duration",
                            "currentness_surface": True,
                            "planner_reason_codes": ["currentness_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_temporal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_temporal_support": 1
    }
    assert "missing_temporal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_duration_temporal_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-duration-temporal",
                group="temporal",
                retrieval=_retrieval_payload(
                    evidence_need=("temporal_support",),
                    bundle_evidence_roles=("primary", "temporal_support"),
                    relation_categories=("temporal",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "temporal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_duration_surface": True,
                            "planner_reason_codes": ["duration_surface"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_temporal_support" not in breakdown["reason_counts"]
    assert "missing_temporal_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reads_support_need_from_retrieval_intent_relation() -> None:
    cases = (
        ("temporal", "missing_temporal_support"),
        ("contrast", "missing_contrast"),
        ("preference", "missing_preference_support"),
    )

    for relation_category, missing_reason in cases:
        retrieval = _retrieval_payload(
            evidence_need=(),
            relation_categories=(),
            policy_score=0.0,
        )
        query_decomposition = retrieval["metadata"]["query_decomposition"]
        query_decomposition["retrieval_intent"]["relations"] = {
            "intents": [{"category": relation_category}]
        }

        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"intent-relation-{relation_category}",
                    group="single-hop",
                    retrieval=retrieval,
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reads_support_need_from_bundle_roles() -> None:
    cases = (
        ("temporal_support", "missing_temporal_support"),
        ("contrast", "missing_contrast"),
        ("location_support", "missing_location_support"),
    )

    for bundle_role, missing_reason in cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"role-need-{bundle_role}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=(),
                        bundle_evidence_roles=("primary", bundle_role),
                        relation_categories=(),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "primary",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_merges_support_need_from_profile_and_intent() -> None:
    retrieval = _retrieval_payload(
        evidence_need=(),
        bundle_evidence_roles=("primary",),
        relation_categories=("status_profile",),
        policy_score=0.0,
    )
    query_decomposition = retrieval["metadata"]["query_decomposition"]
    query_decomposition["retrieval_intent"]["evidence_need"] = ["visual_evidence"]
    query_decomposition["retrieval_intent"]["bundle_evidence_roles"] = [
        "primary",
        "visual_support",
    ]
    query_decomposition["retrieval_intent"]["relations"] = {
        "intents": [{"category": "preference"}]
    }

    gate = fast_gate_metrics(
        (
            _item(
                case_id="mixed-profile-intent-support",
                group="single-hop",
                retrieval=retrieval,
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_visual_support": 1,
    }
    assert "missing_visual_support" in breakdown["samples"][0]["reasons"]
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reports_missing_location_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D8:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": [],
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_location_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_location_support": 1
    }
    assert breakdown["samples"][0]["reasons"] == [
        "missing_supporting",
        "missing_evidence_refs",
        "missing_location_support",
    ]


def test_fast_gate_metrics_accepts_location_relation_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    relation_categories=("location_transition",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["location_transition"],
                            "planner_reason_codes": [
                                "location_relation_category_hits"
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_location_support" not in breakdown["reason_counts"]
    assert "missing_location_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_rejects_weak_location_relation_evidence() -> None:
    weak_cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("broad-summary", {"broad_summary": True}),
        ("stale-conflict", {"conflict_or_stale": True}),
        ("weak-locality", {"source_locality_score": 0.3}),
        ("low-answerability", {"answerability_score": 0.31}),
    )
    for case_id, weak_fields in weak_cases:
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"weak-location-{case_id}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=("location_support",),
                        bundle_evidence_roles=("primary", "location_support"),
                        relation_categories=("location_transition",),
                        entities=("caroline",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [
                            {
                                "role": "location_support",
                                "retrieval_order": 1,
                                "focused_evidence_score": 1.0,
                                "entity_hits": ["caroline"],
                                "relation_category_hits": ["location_transition"],
                                "source_locality_score": 0.9,
                                "answerability_score": 0.72,
                                "planner_reason_codes": [
                                    "location_support",
                                    "location_relation_category_hits",
                                ],
                                **weak_fields,
                            }
                        ],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"]["missing_location_support"] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {
            "missing_location_support": 1
        }
        assert "missing_location_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_requires_grounded_location_relation_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-location",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("location_support",),
                    bundle_evidence_roles=("primary", "location_support"),
                    relation_categories=("location_transition",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "location_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["location_transition"],
                            "planner_reason_codes": [
                                "location_support",
                                "location_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_location_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_location_support": 1
    }
    assert "missing_location_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_rejects_support_role_labels_without_typed_evidence() -> None:
    cases = (
        (
            "location",
            ("location_support",),
            ("primary", "location_support"),
            ("location_transition",),
            "location_support",
            "missing_location_support",
        ),
        (
            "preference",
            ("preference",),
            ("primary", "preference_support"),
            ("preference",),
            "preference_support",
            "missing_preference_support",
        ),
        (
            "visual",
            ("visual_evidence",),
            ("primary", "visual_support"),
            ("visual",),
            "visual_support",
            "missing_visual_support",
        ),
        (
            "emotion",
            ("emotion_response",),
            ("primary", "emotion_response_support"),
            ("emotion_response",),
            "emotion_response_support",
            "missing_emotion_response_support",
        ),
        (
            "symbolic",
            ("symbolic_meaning",),
            ("primary", "symbolic_meaning_support"),
            ("symbolic_meaning",),
            "symbolic_meaning_support",
            "missing_symbolic_meaning_support",
        ),
        (
            "event",
            ("registration_event",),
            ("primary", "event_support"),
            ("registration_event",),
            "event_support",
            "missing_event_support",
        ),
        (
            "exchange",
            ("exchange",),
            ("primary", "exchange_support"),
            ("exchange",),
            "exchange_support",
            "missing_exchange_support",
        ),
        (
            "communication",
            ("communication",),
            ("primary", "communication_support"),
            ("communication",),
            "communication_support",
            "missing_communication_support",
        ),
    )

    for (
        case_suffix,
        evidence_need,
        bundle_roles,
        relation_categories,
        support_role,
        missing_reason,
    ) in cases:
        item_payload = {
            "role": support_role,
            "retrieval_order": 1,
            "focused_evidence_score": 1.0,
            "entity_hits": ["caroline"],
            "planner_reason_codes": [support_role],
        }
        if support_role == "communication_support":
            item_payload["speaker_hits"] = ["caroline"]
            item_payload["planner_reason_codes"].append(
                "communication_speaker_hits"
            )
        gate = fast_gate_metrics(
            (
                _item(
                    case_id=f"label-only-{case_suffix}",
                    group="single-hop",
                    retrieval=_retrieval_payload(
                        evidence_need=evidence_need,
                        bundle_evidence_roles=bundle_roles,
                        relation_categories=relation_categories,
                        entities=("caroline",),
                        policy_score=0.0,
                    ),
                    evidence_bundle={
                        "bundle_complete": False,
                        "item_count": 1,
                        "primary_evidence_count": 1,
                        "supporting_evidence_count": 0,
                        "query_support_term_recall": 0.5,
                        "covered_evidence_terms": [],
                        "items": [item_payload],
                    },
                ),
            ),
            expected_case_count=1,
        )

        breakdown = gate["bundle_gap_breakdown"]

        assert breakdown["reason_counts"][missing_reason] == 1
        assert breakdown["evidence_need_gap_reason_counts"] == {missing_reason: 1}
        assert missing_reason in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_reports_missing_inference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-inference",
                group="open-domain",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("support_goal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D2:3"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["inference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_inference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_inference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_inference_support": 1,
        "missing_required_inference_support": 1,
    }
    assert "missing_inference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_inference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_requires_relation_inference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-inference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("status_profile",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "inference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "planner_reason_codes": [
                                "inference_support",
                                "inference_entity_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_inference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_inference_support": 1
    }
    assert "missing_inference_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_relation_inference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="grounded-inference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("status_profile",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "inference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["status_profile"],
                            "planner_reason_codes": [
                                "inference_support",
                                "inference_entity_hits",
                                "inference_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_inference_support" not in breakdown["reason_counts"]
    assert "missing_inference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_causal_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D3:4"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["causal_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["reason_counts"]["missing_required_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1,
        "missing_required_causal_support": 1,
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_requires_grounded_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="ungrounded-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["causal"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_requires_relation_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="relationless-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_entity_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_causal_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_causal_support": 1
    }
    assert "missing_causal_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_relation_causal_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="grounded-causal",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("causal_support",),
                    bundle_evidence_roles=("primary", "causal_support"),
                    relation_categories=("causal",),
                    entities=("caroline",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "causal_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["causal"],
                            "planner_reason_codes": [
                                "causal_support",
                                "causal_entity_hits",
                                "causal_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_causal_support" not in breakdown["reason_counts"]
    assert "missing_causal_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_preference_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D4:1"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["preference_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_preference_support"] == 1
    assert breakdown["reason_counts"]["missing_required_preference_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_preference_support": 1,
        "missing_required_preference_support": 1,
    }
    assert "missing_preference_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_preference_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_preference_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-preference",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("preference",),
                    bundle_evidence_roles=("primary", "preference_support"),
                    relation_categories=("preference",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "preference_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_preference_evidence": True,
                            "relation_category_hits": ["preference"],
                            "planner_reason_codes": [
                                "preference_support",
                                "preference_evidence",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_preference_support" not in breakdown["reason_counts"]
    assert "missing_required_preference_support" not in breakdown["reason_counts"]
    assert "missing_preference_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_emotion_response_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["emotion_response_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_emotion_response_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_emotion_response_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_emotion_response_support": 1,
        "missing_required_emotion_response_support": 1,
    }
    assert "missing_emotion_response_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_emotion_response_support" in breakdown["samples"][0][
        "reasons"
    ]


def test_fast_gate_metrics_accepts_emotion_response_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-emotion-response",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("emotion_response",),
                    bundle_evidence_roles=("primary", "emotion_response_support"),
                    relation_categories=("emotion_response",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "emotion_response_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["emotion_response"],
                            "planner_reason_codes": [
                                "emotion_response_support",
                                "emotion_response_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_emotion_response_support" not in breakdown["reason_counts"]
    assert "missing_required_emotion_response_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_emotion_response_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_symbolic_meaning_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["symbolic_meaning_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_symbolic_meaning_support"] == 1
    assert (
        breakdown["reason_counts"]["missing_required_symbolic_meaning_support"]
        == 1
    )
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_required_symbolic_meaning_support": 1,
        "missing_symbolic_meaning_support": 1,
    }
    assert "missing_symbolic_meaning_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_symbolic_meaning_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-symbolic-meaning",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("symbolic_meaning",),
                    bundle_evidence_roles=("primary", "symbolic_meaning_support"),
                    relation_categories=("symbolic_meaning",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "symbolic_meaning_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["symbolic_meaning"],
                            "planner_reason_codes": [
                                "symbolic_meaning_support",
                                "symbolic_meaning_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_symbolic_meaning_support" not in breakdown["reason_counts"]
    assert "missing_required_symbolic_meaning_support" not in breakdown[
        "reason_counts"
    ]
    assert "missing_symbolic_meaning_support" not in breakdown[
        "evidence_need_gap_reason_counts"
    ]


def test_fast_gate_metrics_reports_missing_event_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("participation_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("participation_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["event_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_event_support"] == 1
    assert breakdown["reason_counts"]["missing_required_event_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_event_support": 1,
        "missing_required_event_support": 1,
    }
    assert "missing_event_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_event_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-event",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("registration_event",),
                    bundle_evidence_roles=("primary", "event_support"),
                    relation_categories=("registration_event",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "event_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["registration_event"],
                            "planner_reason_codes": [
                                "event_support",
                                "event_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_event_support" not in breakdown["reason_counts"]
    assert "missing_required_event_support" not in breakdown["reason_counts"]
    assert "missing_event_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_exchange_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["exchange_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_exchange_support"] == 1
    assert breakdown["reason_counts"]["missing_required_exchange_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_exchange_support": 1,
        "missing_required_exchange_support": 1,
    }


def test_fast_gate_metrics_accepts_exchange_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-exchange",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("exchange",),
                    bundle_evidence_roles=("primary", "exchange_support"),
                    relation_categories=("exchange",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "exchange_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["exchange"],
                            "planner_reason_codes": [
                                "exchange_support",
                                "exchange_relation_category_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_exchange_support" not in breakdown["reason_counts"]
    assert "missing_required_exchange_support" not in breakdown["reason_counts"]
    assert "missing_exchange_support" not in breakdown["evidence_need_gap_reason_counts"]


def test_fast_gate_metrics_reports_missing_communication_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["communication_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_communication_support"] == 1
    assert breakdown["reason_counts"]["missing_required_communication_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_communication_support": 1,
        "missing_required_communication_support": 1,
    }


def test_fast_gate_metrics_accepts_communication_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-communication",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("communication",),
                    bundle_evidence_roles=("primary", "communication_support"),
                    relation_categories=("communication",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "communication_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "relation_category_hits": ["communication"],
                            "planner_reason_codes": [
                                "communication_support",
                                "communication_relation_category_hits",
                                "communication_speaker_hits",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_communication_support" not in breakdown["reason_counts"]
    assert "missing_required_communication_support" not in breakdown["reason_counts"]
    assert (
        "missing_communication_support"
        not in breakdown["evidence_need_gap_reason_counts"]
    )


def test_fast_gate_metrics_reports_missing_visual_support_gap() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="missing-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                retrieval_quality={
                    "expected_term_recall": 0.5,
                    "evidence_term_recall": 0.0,
                    "missing_evidence_terms": ["D5:2"],
                },
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "missing_required_roles": ["visual_support"],
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "covered_evidence_terms": [],
                            "focused_evidence_score": 1.0,
                            "planner_reason_codes": ["primary_signal"],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert breakdown["reason_counts"]["missing_visual_support"] == 1
    assert breakdown["reason_counts"]["missing_required_visual_support"] == 1
    assert breakdown["evidence_need_gap_reason_counts"] == {
        "missing_visual_support": 1,
        "missing_required_visual_support": 1,
    }
    assert "missing_visual_support" in breakdown["samples"][0]["reasons"]
    assert "missing_required_visual_support" in breakdown["samples"][0]["reasons"]


def test_fast_gate_metrics_accepts_visual_support_evidence() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="has-visual",
                group="single-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("visual_evidence",),
                    bundle_evidence_roles=("primary", "visual_support"),
                    relation_categories=("visual",),
                    policy_score=0.0,
                ),
                evidence_bundle={
                    "bundle_complete": False,
                    "item_count": 1,
                    "primary_evidence_count": 1,
                    "supporting_evidence_count": 0,
                    "query_support_term_recall": 0.5,
                    "covered_evidence_terms": [],
                    "items": [
                        {
                            "role": "visual_support",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "has_visual_evidence": True,
                            "relation_category_hits": ["visual"],
                            "planner_reason_codes": [
                                "visual_support",
                                "visual_grounding",
                            ],
                        }
                    ],
                },
            ),
        ),
        expected_case_count=1,
    )

    breakdown = gate["bundle_gap_breakdown"]

    assert "missing_visual_support" not in breakdown["reason_counts"]
    assert "missing_required_visual_support" not in breakdown["reason_counts"]
    assert "missing_visual_support" not in breakdown["evidence_need_gap_reason_counts"]


def _item(
    *,
    case_id: str,
    score: float = 1.0,
    group: str = "multi-hop",
    retrieval_quality: dict[str, object] | None = None,
    evidence_bundle: dict[str, object] | None = None,
    retrieval: dict[str, object] | None = None,
    cutoff_results: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": group,
        "scored": True,
        "judgment": {"score": score},
        "retrieval_quality": retrieval_quality or {},
        "evidence_bundle": evidence_bundle or {},
        "retrieval": retrieval or {"metadata": {}, "results": []},
        "cutoff_results": cutoff_results or {},
    }


def _retrieval_payload(
    *,
    evidence_need: tuple[str, ...],
    policy_score: float,
    bundle_evidence_roles: tuple[str, ...] = (),
    relation_categories: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
    risk_flags: tuple[str, ...] = (),
    query_overlap_count: int = 0,
    query_plan: dict[str, object] | None = None,
    candidate_features: dict[str, object] | None = None,
    score_signals: dict[str, object] | None = None,
    item_id: str | None = None,
    rank: int = 1,
    score: float = 0.5,
    memory_text: str = "",
) -> dict[str, object]:
    return {
        "metadata": {
            "query_decomposition": {
                "query_profile": {
                    "evidence_need": evidence_need,
                    "bundle_evidence_roles": bundle_evidence_roles,
                    "relation_categories": relation_categories,
                    "entities": entities,
                    "risk_flags": risk_flags,
                },
                "retrieval_intent": {
                    "entity_count": len(entities),
                    "entities": [
                        {"canonical": entity, "surfaces": [entity]}
                        for entity in entities
                    ],
                    "evidence_need": list(evidence_need),
                    "bundle_evidence_roles": list(bundle_evidence_roles),
                    "risk_flags": list(risk_flags),
                    "relations": {
                        "intents": [
                            {"category": category}
                            for category in relation_categories
                        ]
                    },
                },
                "query_plan": query_plan or {},
            },
            "query_integrity": {
                "expected_answer_query_overlap_count": query_overlap_count,
                "expected_answer_query_overlap_terms": ["answer"]
                if query_overlap_count
                else [],
                "retrieval_intent_risk_flags": list(risk_flags),
            },
        },
        "results": [
            {
                **({"id": item_id} if item_id else {}),
                "rank": rank,
                "score": score,
                "memory": memory_text,
                "metadata": {
                    "diagnostics": {
                        "benchmark_rerank_boosted": bool(policy_score),
                        "score_signals": score_signals or {},
                        "benchmark_candidate_features": candidate_features or {},
                        "benchmark_rerank_policy": {
                            "contributions": [
                                {
                                    "policy": "FocusedTurnPolicy",
                                    "score": policy_score,
                                    "reason_codes": ["focused_turn"]
                                    if policy_score
                                    else [],
                                }
                            ]
                        }
                    }
                }
            }
        ],
    }
