from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)


def test_distinct_set_diagnostics_survive_outer_mapping_bounds() -> None:
    diagnostics: dict[str, object] = {
        f"padding_{index:03d}": index for index in range(200)
    }
    expected_counters = {
        "keyword_aggregation_distinct_member_candidates": 11,
        "keyword_aggregation_distinct_member_reservations_used": 7,
        "keyword_aggregation_distinct_member_slots_used": 6,
        "pre_rerank_distinct_set_evidence_items_considered": 5,
        "pre_rerank_distinct_set_evidence_bodies_restored": 4,
        "pre_rerank_distinct_set_evidence_items_added_for_rerank": 3,
        "pre_rerank_distinct_set_evidence_items_rejected_before_rerank": 2,
        "distinct_set_evidence_items_considered": 9,
        "distinct_set_evidence_bodies_restored": 8,
        "distinct_set_evidence_items_readded": 7,
        "distinct_set_evidence_items_missing_after_ranking": 6,
        "distinct_set_evidence_items_rejected_by_rerank": 5,
        "distinct_set_candidates_considered": 4,
        "distinct_set_source_candidates": 3,
        "distinct_set_items_selected": 2,
        "distinct_set_member_slots_selected": 1,
        "distinct_set_redundant_items_suppressed": 10,
    }
    diagnostics.update(expected_counters)
    diagnostics["keyword_aggregation_admission_reasons"] = {
        "distinct_member_support": 7,
        "temporal_conflict": 2,
    }

    normalized = normalize_context_bundle_diagnostics(diagnostics, items=())

    assert normalized["diagnostics_truncated"] is True
    for key, value in expected_counters.items():
        assert normalized[key] == value
    assert normalized["keyword_aggregation_admission_reasons"] == {
        "distinct_member_support": 7,
        "temporal_conflict": 2,
    }
