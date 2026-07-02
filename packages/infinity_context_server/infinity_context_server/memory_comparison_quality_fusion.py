"""Fusion and source-proximity summaries for memory-comparison diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    count_mapping,
    mapping,
    metric_value,
    positive_int,
    retrieval_metadata,
)


def bundle_source_proximity_summary(
    bundle_quality: Mapping[str, object],
) -> dict[str, object]:
    return {
        "support_count": (
            positive_int(bundle_quality.get("total_source_proximity_support_count"))
            or 0
        ),
        "bundle_count": (
            positive_int(bundle_quality.get("source_proximity_bundle_count")) or 0
        ),
        "avg_support_count": round(
            metric_value(bundle_quality, "avg_source_proximity_support_count"),
            6,
        ),
        "avg_closest_distance": round(
            metric_value(bundle_quality, "avg_source_proximity_closest_distance"),
            6,
        ),
        "closest_distance_min": round(
            metric_value(bundle_quality, "source_proximity_closest_distance_min"),
            6,
        ),
        "distance_counts": dict(
            sorted(
                count_mapping(
                    bundle_quality.get("source_proximity_distance_counts")
                ).items()
            )
        ),
    }


def candidate_fusion_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    evaluation_count = 0
    raw_result_count = 0
    unique_result_count = 0
    duplicate_result_count = 0
    multi_query_hit_count = 0
    bridge_query_hit_count = 0
    lower_score_selection_count = 0
    source_type_selection_count = 0
    focused_query_selection_count = 0
    query_role_counts: Counter[str] = Counter()
    max_query_match_count = 0
    max_source_diversity_count = 0
    max_rrf_score = 0.0

    for item in items:
        merge = mapping(retrieval_metadata(item).get("multi_query_merge"))
        if not merge:
            continue
        evaluation_count += 1
        raw_result_count += positive_int(merge.get("raw_result_count")) or 0
        unique_result_count += positive_int(merge.get("unique_result_count")) or 0
        duplicate_result_count += positive_int(merge.get("duplicate_result_count")) or 0
        multi_query_hit_count += positive_int(merge.get("multi_query_hit_count")) or 0
        bridge_query_hit_count += positive_int(merge.get("bridge_query_hit_count")) or 0
        lower_score_selection_count += (
            positive_int(merge.get("lower_score_evidence_selection_count")) or 0
        )
        source_type_selection_count += (
            positive_int(merge.get("source_type_evidence_selection_count")) or 0
        )
        focused_query_selection_count += (
            positive_int(merge.get("focused_query_evidence_selection_count")) or 0
        )
        query_role_counts.update(count_mapping(merge.get("query_role_counts")))
        max_query_match_count = max(
            max_query_match_count,
            positive_int(merge.get("max_query_match_count")) or 0,
        )
        max_source_diversity_count = max(
            max_source_diversity_count,
            positive_int(merge.get("max_source_diversity_count")) or 0,
        )
        max_rrf_score = max(max_rrf_score, metric_value(merge, "max_rrf_score"))

    return {
        "evaluation_count": evaluation_count,
        "raw_result_count": raw_result_count,
        "unique_result_count": unique_result_count,
        "duplicate_result_count": duplicate_result_count,
        "multi_query_hit_count": multi_query_hit_count,
        "bridge_query_hit_count": bridge_query_hit_count,
        "lower_score_evidence_selection_count": lower_score_selection_count,
        "source_type_evidence_selection_count": source_type_selection_count,
        "focused_query_evidence_selection_count": focused_query_selection_count,
        "query_role_counts": dict(sorted(query_role_counts.items())),
        "max_query_match_count": max_query_match_count,
        "max_source_diversity_count": max_source_diversity_count,
        "max_rrf_score": round(max_rrf_score, 6),
    }
