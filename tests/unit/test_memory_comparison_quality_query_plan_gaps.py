from __future__ import annotations

from infinity_context_server.memory_comparison_quality_diagnostics import (
    quality_diagnostics,
)
from infinity_context_server.memory_comparison_quality_query_plan_gaps import (
    evidence_role_query_families,
    query_plan_gap_breakdown,
)


def test_query_plan_integrity_maps_required_role_aliases() -> None:
    items = (
        _query_plan_item("missing-location-alias", required_role="location"),
        _query_plan_item("missing-visual-alias", required_role="visual"),
        _query_plan_item(
            "missing-multi-hop-alias",
            required_role="multi_hop_support",
        ),
        _query_plan_item(
            "missing-contrast-alias",
            required_role="contrast_support",
        ),
        _query_plan_item(
            "covered-location-alias",
            required_role="location",
            selected_role_families=("base_query", "location_support"),
        ),
    )

    table = quality_diagnostics(items)["query_plan_integrity_table"]

    assert table["missing_evidence_role_query_family_counts"] == {
        "contrast_support": 1,
        "location": 1,
        "multi_hop_support": 1,
        "visual": 1,
    }
    assert [
        sample["case_id"]
        for sample in table["samples"]
        if "missing_evidence_role_query_family" in sample["gap_reasons"]
    ] == [
        "missing-location-alias",
        "missing-visual-alias",
        "missing-multi-hop-alias",
        "missing-contrast-alias",
    ]


def test_evidence_role_query_families_covers_aliases_and_profile_roles() -> None:
    assert evidence_role_query_families(" location ") == (
        "location_support",
        "relation_compact",
        "expanded_focus",
    )
    assert evidence_role_query_families("multi_hop_bridge") == (
        "multi_hop",
        "relation_compact",
        "expanded_focus",
    )
    assert evidence_role_query_families("contrast_support") == (
        "contrast_support",
        "relation_compact",
        "expanded_focus",
    )
    assert evidence_role_query_families("visual_temporal_support") == (
        "temporal_support",
        "expanded_focus",
    )
    assert evidence_role_query_families("negative_support") == (
        "negative_support",
    )
    assert evidence_role_query_families("health_support") == (
        "relation_compact",
        "expanded_focus",
    )
    assert evidence_role_query_families("community_membership_support") == (
        "relation_compact",
        "expanded_focus",
    )
    assert evidence_role_query_families("unmapped_support") == ()


def test_query_plan_gap_breakdown_caps_samples_deterministically() -> None:
    samples = tuple(
        {
            "case_id": f"case-{index}",
            "group": "single-hop",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": ("location",),
            "selected_role_families": (
                "base_query",
                "expanded_focus",
                "relation_compact",
                "temporal_support",
                "multi_hop",
                "location_support",
            ),
            "required_evidence_roles": ("primary", "location"),
            "selected_query_count": index,
        }
        for index in range(1, 8)
    )

    breakdown = query_plan_gap_breakdown(
        {
            "plan_count": 7,
            "plan_gap_case_count": 7,
            "missing_evidence_role_query_family_total": 7,
            "missing_evidence_role_query_family_counts": {"location": 7},
            "gap_reason_counts": {"missing_evidence_role_query_family": 7},
            "samples": samples,
        }
    )

    assert [sample["case_id"] for sample in breakdown["samples"]] == [
        "case-1",
        "case-2",
        "case-3",
        "case-4",
        "case-5",
    ]
    assert [
        sample["case_id"] for sample in breakdown["compact_samples"]
    ] == [
        "case-1",
        "case-2",
        "case-3",
        "case-4",
        "case-5",
    ]
    assert breakdown["compact_samples"][0]["selected_role_families"] == [
        "base_query",
        "expanded_focus",
        "relation_compact",
        "temporal_support",
        "multi_hop",
    ]
    assert breakdown["missing_evidence_role_query_family_details"]["location"][
        "sample_case_ids"
    ] == [
        "case-1",
        "case-2",
        "case-3",
        "case-4",
        "case-5",
    ]


def test_query_plan_gap_breakdown_reports_gap_reason_details() -> None:
    samples = (
        {
            "case_id": "role-gap-1",
            "group": "temporal",
            "gap_reasons": (
                "missing_evidence_role_query_family",
                "dropped_queries",
            ),
            "missing_evidence_role_query_families": ("temporal_support",),
        },
        {
            "case_id": "fanout-gap-1",
            "group": "multi-hop",
            "gap_reasons": ("fanout_limit_hit", "dropped_queries"),
        },
        {
            "case_id": "role-gap-2",
            "group": "location",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": ("location",),
        },
    )

    breakdown = query_plan_gap_breakdown(
        {
            "plan_count": 3,
            "plan_gap_case_count": 3,
            "gap_reason_counts": {
                "dropped_queries": 2,
                "fanout_limit_hit": 1,
                "missing_evidence_role_query_family": 2,
            },
            "missing_evidence_role_query_family_total": 2,
            "missing_evidence_role_query_family_counts": {
                "location": 1,
                "temporal_support": 1,
            },
            "samples": samples,
        }
    )

    assert list(breakdown["gap_reason_details"]) == [
        "dropped_queries",
        "missing_evidence_role_query_family",
        "fanout_limit_hit",
    ]
    assert breakdown["gap_reason_details"]["dropped_queries"] == {
        "reason": "dropped_queries",
        "reason_label": "dropped queries",
        "impact_count": 2,
        "action": (
            "Inspect dropped role families and fanout limits for query-plan "
            "coverage loss."
        ),
        "sample_case_ids": ["role-gap-1", "fanout-gap-1"],
    }
    assert breakdown["gap_reason_details"][
        "missing_evidence_role_query_family"
    ]["sample_case_ids"] == ["role-gap-1", "role-gap-2"]
    assert breakdown["gap_reason_details"]["fanout_limit_hit"][
        "sample_case_ids"
    ] == ["fanout-gap-1"]


def test_query_plan_gap_breakdown_explains_missing_recommended_family_causes() -> None:
    samples = (
        {
            "case_id": "fanout-dropped-temporal",
            "missing_recommended_role_families": ("temporal_support",),
            "dropped_roles": ("temporal_support",),
            "fanout_limit_hit": True,
        },
        {
            "case_id": "absent-temporal",
            "missing_recommended_role_families": ("temporal_support",),
        },
        {
            "case_id": "type-dropped-location",
            "missing_recommended_role_families": ("location_support",),
            "dropped_role_families": ("location_support",),
            "type_limit_hit": True,
        },
    )

    breakdown = query_plan_gap_breakdown(
        {
            "plan_count": 3,
            "plan_gap_case_count": 3,
            "missing_recommended_role_family_total": 3,
            "missing_recommended_role_family_counts": {
                "temporal_support": 2,
                "location_support": 1,
            },
            "samples": samples,
        }
    )

    details = breakdown["missing_recommended_role_family_details"]
    assert list(details) == ["temporal_support", "location_support"]
    assert details["temporal_support"] == {
        "role_family": "temporal_support",
        "role_family_label": "temporal support",
        "impact_count": 2,
        "sample_cause_counts": {
            "dropped_by_fanout_limit": 1,
            "candidate_absent": 1,
        },
        "action": (
            "Preserve temporal support queries before the query fanout cap "
            "drops lower-priority recommended coverage."
        ),
        "sample_case_ids": ["fanout-dropped-temporal", "absent-temporal"],
    }
    assert details["location_support"]["sample_cause_counts"] == {
        "dropped_by_type_limit": 1
    }
    assert details["location_support"]["action"] == (
        "Preserve location support queries when type limits replace or drop "
        "candidate query families."
    )


def test_query_plan_gap_breakdown_compact_samples_cap_text_payloads() -> None:
    long_text = "x" * 200
    samples = tuple(
        {
            "case_id": f"case-{index}-{long_text}",
            "group": f"group-{long_text}",
            "gap_reasons": ("missing_evidence_role_query_family",),
            "missing_evidence_role_query_families": (f"location-{long_text}",),
            "selected_role_families": tuple(
                f"family-{family_index}-{long_text}" for family_index in range(7)
            ),
            "dropped_role_families": tuple(
                f"dropped-family-{family_index}-{long_text}"
                for family_index in range(7)
            ),
            "required_evidence_roles": (
                "primary",
                f"location-{long_text}",
            ),
            "selected_query_count": index,
        }
        for index in range(1, 8)
    )

    breakdown = query_plan_gap_breakdown(
        {
            "plan_count": 7,
            "plan_gap_case_count": 7,
            "missing_evidence_role_query_family_total": 7,
            "missing_evidence_role_query_family_counts": {
                f"location-{long_text}": 7
            },
            "gap_reason_counts": {"missing_evidence_role_query_family": 7},
            "samples": samples,
        }
    )

    compact_samples = breakdown["compact_samples"]
    assert len(compact_samples) == 5
    assert compact_samples[0]["case_id"].endswith("...")
    assert compact_samples[0]["group"].endswith("...")
    assert len(compact_samples[0]["selected_role_families"]) == 5
    assert len(compact_samples[0]["dropped_role_families"]) == 5
    assert all(
        len(value) <= 128
        for sample in compact_samples
        for value in (
            sample["case_id"],
            sample["group"],
            *sample["missing_evidence_role_query_families"],
            *sample["selected_role_families"],
            *sample["dropped_role_families"],
            *sample["required_evidence_roles"],
        )
    )
    sample_case_ids = breakdown["missing_evidence_role_query_family_details"][
        f"location-{long_text}"
    ]["sample_case_ids"]
    assert len(sample_case_ids) == 5
    assert all(len(case_id) <= 128 for case_id in sample_case_ids)


def _query_plan_item(
    case_id: str,
    *,
    required_role: str,
    selected_role_families: tuple[str, ...] = ("base_query",),
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
