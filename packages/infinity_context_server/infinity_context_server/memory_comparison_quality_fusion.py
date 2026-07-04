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


def bundle_source_identity_summary(
    bundle_quality: Mapping[str, object],
) -> dict[str, object]:
    return {
        "item_count": (
            positive_int(bundle_quality.get("total_source_identity_item_count")) or 0
        ),
        "ref_count": (
            positive_int(bundle_quality.get("total_source_identity_ref_count")) or 0
        ),
        "bundle_count": (
            positive_int(bundle_quality.get("source_identity_bundle_count")) or 0
        ),
        "avg_item_count": round(
            metric_value(bundle_quality, "avg_source_identity_item_count"),
            6,
        ),
        "avg_ref_count": round(
            metric_value(bundle_quality, "avg_source_identity_ref_count"),
            6,
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
    score_winner_query_role_counts: Counter[str] = Counter()
    selected_evidence_query_role_counts: Counter[str] = Counter()
    focused_query_evidence_selection_role_counts: Counter[str] = Counter()
    evidence_selection_reason_counts: Counter[str] = Counter()
    evidence_selection_samples: list[dict[str, object]] = []
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
        score_winner_query_role_counts.update(
            count_mapping(merge.get("score_winner_query_role_counts"))
        )
        selected_evidence_query_role_counts.update(
            count_mapping(merge.get("selected_evidence_query_role_counts"))
        )
        focused_query_evidence_selection_role_counts.update(
            count_mapping(merge.get("focused_query_evidence_selection_role_counts"))
        )
        evidence_selection_reason_counts.update(
            count_mapping(merge.get("evidence_selection_reason_counts"))
        )
        for sample in _bounded_selection_samples(merge.get("evidence_selection_samples")):
            if len(evidence_selection_samples) >= 10:
                break
            evidence_selection_samples.append(sample)
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
        "score_winner_query_role_counts": dict(
            sorted(score_winner_query_role_counts.items())
        ),
        "selected_evidence_query_role_counts": dict(
            sorted(selected_evidence_query_role_counts.items())
        ),
        "focused_query_evidence_selection_role_counts": dict(
            sorted(focused_query_evidence_selection_role_counts.items())
        ),
        "evidence_selection_reason_counts": dict(
            sorted(evidence_selection_reason_counts.items())
        ),
        "evidence_selection_samples": evidence_selection_samples,
        "max_query_match_count": max_query_match_count,
        "max_source_diversity_count": max_source_diversity_count,
        "max_rrf_score": round(max_rrf_score, 6),
    }


def _bounded_selection_samples(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    samples: list[dict[str, object]] = []
    for sample in value:
        if not isinstance(sample, Mapping):
            continue
        samples.append(
            {
                "dedupe_key": str(sample.get("dedupe_key") or ""),
                "reason_codes": _string_list(sample.get("reason_codes"), limit=6),
                "query_match_count": positive_int(sample.get("query_match_count")) or 0,
                "score_winner_item_id": str(sample.get("score_winner_item_id") or ""),
                "score_winner_query_role": str(
                    sample.get("score_winner_query_role") or ""
                ),
                "score_winner_source_type": str(
                    sample.get("score_winner_source_type") or ""
                ),
                "winner_score": round(metric_value(sample, "winner_score"), 6),
                "selected_evidence_item_id": str(
                    sample.get("selected_evidence_item_id") or ""
                ),
                "selected_evidence_query_role": str(
                    sample.get("selected_evidence_query_role") or ""
                ),
                "selected_evidence_source_type": str(
                    sample.get("selected_evidence_source_type") or ""
                ),
                "selected_evidence_score": round(
                    metric_value(sample, "selected_evidence_score"),
                    6,
                ),
                "selected_evidence_quality_score": round(
                    metric_value(sample, "selected_evidence_quality_score"),
                    6,
                ),
                "source_ref_count": positive_int(sample.get("source_ref_count")) or 0,
                "source_refs_sample": _string_list(
                    sample.get("source_refs_sample"),
                    limit=6,
                ),
            }
        )
        if len(samples) >= 10:
            break
    return tuple(samples)


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [str(item) for item in value if str(item).strip()][:limit]
