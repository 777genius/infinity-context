from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
    quality_diagnostics,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_weak_support_reasons,
)


def test_bundle_weak_support_reasons_marks_role_label_only_support() -> None:
    bundle = {
        "items": [
            {
                "role": "primary",
                "covered_evidence_terms": ["D1:1"],
                "focused_evidence_score": 1.0,
            },
            {
                "role": "preference_support",
                "planner_reason_codes": ["role:preference_support"],
                "answerability_score": 0.8,
            },
        ]
    }

    assert bundle_weak_support_reasons(bundle) == ("role_label_only_support",)


def test_bundle_weak_support_reasons_marks_low_answerability_support() -> None:
    bundle = {
        "items": [
            {
                "role": "primary",
                "covered_evidence_terms": ["D1:1"],
                "focused_evidence_score": 1.0,
            },
            {
                "role": "supporting",
                "source_refs": ["D1:2"],
                "answerability_score": 0.42,
                "source_locality_score": 0.8,
            },
        ]
    }

    assert bundle_weak_support_reasons(bundle) == (
        "weak_selected_support",
        "low_answerability_support",
    )


def test_bundle_weak_support_reasons_marks_weak_source_locality_support() -> None:
    bundle = {
        "items": [
            {
                "role": "primary",
                "covered_evidence_terms": ["D1:1"],
                "focused_evidence_score": 1.0,
            },
            {
                "role": "location_support",
                "source_refs": ["D9:1", "D1:2"],
                "answerability_score": 0.82,
                "source_locality_score": 0.3,
            },
        ]
    }

    assert bundle_weak_support_reasons(bundle) == (
        "weak_selected_support",
        "weak_source_locality_support",
    )


def test_fast_gate_metrics_blocks_role_label_only_complete_bundle_quality() -> None:
    items = tuple(
        _item(
            case_id=f"case-{index}",
            evidence_bundle=_fast_gate_bundle(
                index,
                bundle_quality=_bundle_quality(
                    confidence_score=0.76,
                    confidence_band="high",
                    reason_codes=(
                        "has_primary_evidence",
                        "has_supporting_evidence",
                        "has_preference_support_evidence",
                        "high_answerability",
                    ),
                    selected_item_count=2,
                    primary_count=1,
                    supporting_count=1,
                    preference_support_count=1,
                ),
                items=[
                    {
                        "role": "primary",
                        "retrieval_order": 1,
                        "covered_evidence_terms": [f"D{index}:1"],
                        "focused_evidence_score": 1.0,
                    },
                    {
                        "role": "preference_support",
                        "retrieval_order": 2,
                        "planner_reason_codes": ["role:preference_support"],
                    },
                ]
                if index == 1
                else None,
            ),
        )
        for index in range(1, 41)
    )

    gate = fast_gate_metrics(items)
    table = quality_diagnostics(items)["bundle_quality_table"]
    breakdown = gate["bundle_quality_failure_breakdown"]

    assert gate["passed"] is False
    assert gate["ready_for_full_locomo"] is False
    assert gate["bundle_quality_gate_applied"] is True
    assert gate["weak_bundle_count"] == 1
    assert gate["gates"]["bundle_quality_medium_or_high"]["actual"] == 39
    assert table["weak_support_bundle_count"] == 1
    assert table["weak_support_reason_counts"] == {"role_label_only_support": 1}
    assert breakdown["risk_reason_counts"]["risk:role_label_only_support"] == 1
    assert breakdown["weak_samples"][0]["case_id"] == "case-1"
    assert "risk:role_label_only_support" in breakdown["weak_samples"][0][
        "reason_codes"
    ]


def test_quality_diagnostics_marks_noisy_complete_bundle_as_weak_support() -> None:
    diagnostics = quality_diagnostics(
        (
            _item(
                case_id="broad-complete",
                evidence_bundle={
                    "bundle_complete": True,
                    "evidence_term_count": 1,
                    "covered_evidence_terms": ["D1:1"],
                    "bundle_planner": {
                        "bundle_quality": _bundle_quality(
                            confidence_score=0.72,
                            confidence_band="medium",
                            reason_codes=(
                                "has_primary_evidence",
                                "has_supporting_evidence",
                                "has_source_refs",
                                "medium_answerability",
                            ),
                            selected_item_count=2,
                            primary_count=1,
                            supporting_count=1,
                            source_ref_support_item_count=2,
                        )
                    },
                    "items": [
                        {
                            "role": "primary",
                            "retrieval_order": 1,
                            "source_refs": ["D1:1"],
                            "focused_evidence_score": 1.0,
                            "broad_summary": True,
                        },
                        {
                            "role": "supporting",
                            "retrieval_order": 2,
                            "source_refs": ["D1:2"],
                            "answerability_score": 0.32,
                        },
                    ],
                },
            ),
        )
    )

    table = diagnostics["bundle_quality_table"]

    assert table["weak_bundle_count"] == 1
    assert table["medium_or_high_bundle_count"] == 0
    assert table["confidence_band_counts"] == {"medium": 1}
    assert table["weak_support_bundle_count"] == 1
    assert table["weak_support_reason_counts"] == {
        "all_selected_support_weak": 1,
        "low_answerability_support": 1,
    }
    assert table["risk_reason_counts"]["risk:all_selected_support_weak"] == 1
    assert table["risk_reason_counts"]["risk:low_answerability_support"] == 1
    assert "risk:all_selected_support_weak" in table["weak_samples"][0][
        "reason_codes"
    ]
    assert "risk:low_answerability_support" in table["weak_samples"][0][
        "reason_codes"
    ]


def test_fast_gate_metrics_rejects_unrelated_relation_as_inference_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="unrelated-relation-inference",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("support_goal",),
                    entities=("caroline",),
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
                            "role": "supporting",
                            "retrieval_order": 1,
                            "focused_evidence_score": 1.0,
                            "entity_hits": ["caroline"],
                            "relation_category_hits": ["preference"],
                            "planner_reason_codes": [
                                "preference_relation_category_hits"
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


def test_fast_gate_metrics_accepts_inference_specific_relation_support() -> None:
    gate = fast_gate_metrics(
        (
            _item(
                case_id="valid-inference-relation",
                group="multi-hop",
                retrieval=_retrieval_payload(
                    evidence_need=("inference_support",),
                    bundle_evidence_roles=("primary", "inference_support"),
                    relation_categories=("support_goal",),
                    entities=("caroline",),
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
                            "relation_hits": ["support_goal"],
                            "planner_reason_codes": [
                                "inference_support",
                                "inference_relation_hits",
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


def _item(
    *,
    case_id: str,
    evidence_bundle: dict[str, object],
    group: str = "multi-hop",
    retrieval: dict[str, object] | None = None,
    retrieval_quality: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "group": group,
        "scored": True,
        "judgment": {"score": 1.0},
        "retrieval_quality": retrieval_quality or {},
        "evidence_bundle": evidence_bundle,
        "retrieval": retrieval or {"metadata": {}, "results": []},
        "cutoff_results": {},
    }


def _retrieval_payload(
    *,
    evidence_need: tuple[str, ...],
    bundle_evidence_roles: tuple[str, ...],
    relation_categories: tuple[str, ...],
    entities: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "metadata": {
            "query_decomposition": {
                "query_profile": {
                    "evidence_need": evidence_need,
                    "bundle_evidence_roles": bundle_evidence_roles,
                    "relation_categories": relation_categories,
                    "entities": entities,
                },
                "retrieval_intent": {
                    "entity_count": len(entities),
                    "entities": [
                        {"canonical": entity, "surfaces": [entity]}
                        for entity in entities
                    ],
                    "evidence_need": list(evidence_need),
                    "bundle_evidence_roles": list(bundle_evidence_roles),
                    "relations": {
                        "intents": [
                            {"category": category}
                            for category in relation_categories
                        ]
                    },
                },
            }
        },
        "results": [],
    }


def _fast_gate_bundle(
    index: int,
    *,
    bundle_quality: dict[str, object],
    items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "bundle_complete": True,
        "evidence_term_count": 1,
        "covered_evidence_terms": [f"D{index}:1"],
        "bundle_planner": {"bundle_quality": bundle_quality},
        "items": items
        or [
            {
                "retrieval_order": 1 if index <= 30 else 2,
                "covered_evidence_terms": [f"D{index}:1"],
                "focused_evidence_score": 1.0,
            }
        ],
    }


def _bundle_quality(
    *,
    confidence_score: float,
    confidence_band: str,
    reason_codes: tuple[str, ...],
    selected_item_count: int,
    primary_count: int,
    supporting_count: int,
    preference_support_count: int = 0,
    source_ref_support_item_count: int = 0,
) -> dict[str, object]:
    return {
        "confidence_score": confidence_score,
        "confidence_band": confidence_band,
        "reason_codes": reason_codes,
        "selected_item_count": selected_item_count,
        "primary_count": primary_count,
        "supporting_count": supporting_count,
        "preference_support_count": preference_support_count,
        "source_ref_support_item_count": source_ref_support_item_count,
    }
