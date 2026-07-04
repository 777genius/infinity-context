"""Bundle-quality table helpers for memory-comparison diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import avg as _avg
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_complete as _bundle_complete,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_planner as _bundle_planner,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    count_mapping as _count_mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    metric_value as _metric_value,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    top_counts as _top_counts,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_weak_support_reasons as _bundle_weak_support_reasons,
)


def bundle_quality_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    quality_items: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    confidence_scores: list[float] = []
    risk_penalties: list[float] = []
    bridge_counts: list[int] = []
    causal_support_counts: list[int] = []
    communication_support_counts: list[int] = []
    event_support_counts: list[int] = []
    exchange_support_counts: list[int] = []
    inference_support_counts: list[int] = []
    location_support_counts: list[int] = []
    emotion_response_support_counts: list[int] = []
    symbolic_meaning_support_counts: list[int] = []
    preference_support_counts: list[int] = []
    visual_support_counts: list[int] = []
    location_relation_category_hit_counts: list[int] = []
    source_proximity_support_counts: list[int] = []
    source_proximity_closest_distances: list[float] = []
    source_proximity_distance_counts: Counter[str] = Counter()
    source_ref_support_item_counts: list[int] = []
    source_ref_support_ref_counts: list[int] = []
    source_identity_item_counts: list[int] = []
    source_identity_ref_counts: list[int] = []
    source_identity_support_item_counts: list[int] = []
    source_identity_support_ref_counts: list[int] = []
    source_type_support_diversities: list[int] = []
    retrieval_source_support_diversities: list[int] = []
    contrast_counts: list[int] = []
    contrast_surface_counts: list[int] = []
    negative_absence_support_counts: list[int] = []
    negation_surface_counts: list[int] = []
    currentness_surface_counts: list[int] = []
    stale_surface_counts: list[int] = []
    selected_source_locality_scores: list[float] = []
    measured_selected_source_locality_scores: list[float] = []
    unmeasured_selected_source_locality_counts: list[int] = []
    measured_answerability_scores: list[float] = []
    unmeasured_answerability_counts: list[int] = []
    dropped_source_ref_overlap_counts: list[int] = []
    dropped_noisy_source_overlap_counts: list[int] = []
    dropped_source_ref_overlap_keys: Counter[str] = Counter()
    dropped_noisy_source_overlap_keys: Counter[str] = Counter()
    band_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    weak_support_reason_counts: Counter[str] = Counter()
    weak_support_bundle_count = 0
    weak_support_medium_or_high_count = 0
    weak_samples: list[dict[str, object]] = []
    confidence_gap_counts: Counter[str] = Counter()
    confidence_gap_bundle_count = 0
    confidence_gap_samples: list[dict[str, object]] = []

    for item in items:
        planner = _bundle_planner(item)
        quality = _mapping(planner.get("bundle_quality"))
        if not quality:
            continue
        quality_items.append((item, quality))
        score = _metric_value(quality, "confidence_score")
        confidence_scores.append(score)
        risk_penalties.append(_metric_value(quality, "risk_penalty"))
        bridge_counts.append(_positive_int(quality.get("bridge_count")) or 0)
        causal_support_counts.append(
            _positive_int(quality.get("causal_support_count")) or 0
        )
        communication_support_counts.append(
            _positive_int(quality.get("communication_support_count")) or 0
        )
        event_support_counts.append(
            _positive_int(quality.get("event_support_count")) or 0
        )
        exchange_support_counts.append(
            _positive_int(quality.get("exchange_support_count")) or 0
        )
        inference_support_counts.append(
            _positive_int(quality.get("inference_support_count")) or 0
        )
        location_support_counts.append(
            _positive_int(quality.get("location_support_count")) or 0
        )
        emotion_response_support_counts.append(
            _positive_int(quality.get("emotion_response_support_count")) or 0
        )
        symbolic_meaning_support_counts.append(
            _positive_int(quality.get("symbolic_meaning_support_count")) or 0
        )
        preference_support_counts.append(
            _positive_int(quality.get("preference_support_count")) or 0
        )
        visual_support_counts.append(
            _positive_int(quality.get("visual_support_count")) or 0
        )
        location_relation_category_hit_counts.append(
            _positive_int(quality.get("location_relation_category_hit_count")) or 0
        )
        source_proximity_support_counts.append(
            _positive_int(quality.get("source_proximity_support_count")) or 0
        )
        source_identity_item_counts.append(
            _positive_int(quality.get("source_identity_item_count")) or 0
        )
        source_identity_ref_counts.append(
            _positive_int(quality.get("source_identity_ref_count")) or 0
        )
        source_identity_support_item_counts.append(
            _positive_int(quality.get("source_identity_support_item_count")) or 0
        )
        source_identity_support_ref_counts.append(
            _positive_int(quality.get("source_identity_support_ref_count")) or 0
        )
        source_type_support_diversities.append(
            _positive_int(quality.get("source_type_support_diversity")) or 0
        )
        retrieval_source_support_diversities.append(
            _positive_int(quality.get("retrieval_source_support_diversity")) or 0
        )
        closest_distance = _positive_int(
            quality.get("source_proximity_closest_distance")
        )
        if closest_distance is not None:
            source_proximity_closest_distances.append(float(closest_distance))
        source_proximity_distance_counts.update(
            _count_mapping(quality.get("source_proximity_distance_counts"))
        )
        source_ref_support_item_counts.append(
            _positive_int(quality.get("source_ref_support_item_count")) or 0
        )
        source_ref_support_ref_counts.append(
            _positive_int(quality.get("source_ref_support_ref_count")) or 0
        )
        contrast_counts.append(_positive_int(quality.get("contrast_count")) or 0)
        contrast_surface_counts.append(
            _positive_int(quality.get("contrast_surface_count")) or 0
        )
        negative_absence_support_counts.append(
            _positive_int(quality.get("negative_absence_support_count")) or 0
        )
        negation_surface_counts.append(
            _positive_int(quality.get("negation_surface_count")) or 0
        )
        currentness_surface_counts.append(
            _positive_int(quality.get("currentness_surface_count")) or 0
        )
        stale_surface_counts.append(
            _positive_int(quality.get("stale_surface_count")) or 0
        )
        if "average_selected_source_locality_score" in planner:
            selected_source_locality_scores.append(
                _metric_value(planner, "average_selected_source_locality_score")
            )
        if "average_measured_selected_source_locality_score" in planner:
            measured_source_locality = _metric_value(
                planner,
                "average_measured_selected_source_locality_score",
            )
            if measured_source_locality > 0:
                measured_selected_source_locality_scores.append(
                    measured_source_locality
                )
        if "unmeasured_selected_source_locality_count" in planner:
            unmeasured_selected_source_locality_counts.append(
                _positive_int(
                    planner.get("unmeasured_selected_source_locality_count")
                )
                or 0
            )
        if "average_measured_answerability_score" in quality:
            measured_answerability = _metric_value(
                quality,
                "average_measured_answerability_score",
            )
            if measured_answerability > 0:
                measured_answerability_scores.append(measured_answerability)
        if "unmeasured_answerability_count" in quality:
            unmeasured_answerability_counts.append(
                _positive_int(quality.get("unmeasured_answerability_count")) or 0
            )
        dropped_source_ref_overlap_counts.append(
            _positive_int(planner.get("dropped_source_ref_overlap_count")) or 0
        )
        dropped_noisy_source_overlap_counts.append(
            _positive_int(planner.get("dropped_noisy_source_overlap_count")) or 0
        )
        dropped_source_ref_overlap_keys.update(
            _str_tuple(planner.get("dropped_source_ref_overlap_keys_sample"))
        )
        dropped_noisy_source_overlap_keys.update(
            _str_tuple(planner.get("dropped_noisy_source_overlap_keys_sample"))
        )
        band = str(quality.get("confidence_band") or "unknown").strip() or "unknown"
        band_counts[band] += 1
        quality_reasons = _str_tuple(quality.get("reason_codes"))
        weak_support_reasons = _bundle_weak_support_reasons(
            _mapping(item.get("evidence_bundle"))
        )
        derived_risk_reasons = tuple(
            f"risk:{reason}" for reason in weak_support_reasons
        )
        reason_counts.update((*quality_reasons, *derived_risk_reasons))
        weak_support_reason_counts.update(weak_support_reasons)
        if weak_support_reasons:
            weak_support_bundle_count += 1
            if band in {"medium", "high"}:
                weak_support_medium_or_high_count += 1
        confidence_gap_reasons = _confidence_gap_reasons(
            item,
            band=band,
            weak_support_reasons=weak_support_reasons,
        )
        if confidence_gap_reasons:
            confidence_gap_bundle_count += 1
            confidence_gap_counts.update(confidence_gap_reasons)
            if len(confidence_gap_samples) < 10:
                confidence_gap_samples.append(
                    _confidence_gap_sample(
                        item,
                        quality,
                        confidence_gap_reasons=confidence_gap_reasons,
                        weak_support_reasons=weak_support_reasons,
                        extra_reason_codes=derived_risk_reasons,
                    )
                )
        if len(weak_samples) < 10 and (
            band in {"none", "low"}
            or bool(weak_support_reasons)
            or any(reason.startswith("risk:") for reason in quality_reasons)
        ):
            weak_samples.append(
                _bundle_quality_sample(
                    item,
                    quality,
                    extra_reason_codes=derived_risk_reasons,
                )
            )

    weak_count = sum(
        count for band, count in band_counts.items() if band in {"none", "low"}
    ) + weak_support_medium_or_high_count
    medium_or_high_count = sum(
        count for band, count in band_counts.items() if band in {"medium", "high"}
    ) - weak_support_medium_or_high_count
    return {
        "bundle_count": len(quality_items),
        "avg_confidence_score": _avg(confidence_scores),
        "avg_risk_penalty": _avg(risk_penalties),
        "avg_bridge_count": _avg(bridge_counts),
        "total_bridge_count": sum(bridge_counts),
        "bridge_bundle_count": sum(1 for count in bridge_counts if count > 0),
        "avg_causal_support_count": _avg(causal_support_counts),
        "total_causal_support_count": sum(causal_support_counts),
        "causal_support_bundle_count": sum(
            1 for count in causal_support_counts if count > 0
        ),
        "avg_communication_support_count": _avg(communication_support_counts),
        "total_communication_support_count": sum(communication_support_counts),
        "communication_support_bundle_count": sum(
            1 for count in communication_support_counts if count > 0
        ),
        "avg_event_support_count": _avg(event_support_counts),
        "total_event_support_count": sum(event_support_counts),
        "event_support_bundle_count": sum(
            1 for count in event_support_counts if count > 0
        ),
        "avg_exchange_support_count": _avg(exchange_support_counts),
        "total_exchange_support_count": sum(exchange_support_counts),
        "exchange_support_bundle_count": sum(
            1 for count in exchange_support_counts if count > 0
        ),
        "avg_inference_support_count": _avg(inference_support_counts),
        "total_inference_support_count": sum(inference_support_counts),
        "inference_support_bundle_count": sum(
            1 for count in inference_support_counts if count > 0
        ),
        "avg_location_support_count": _avg(location_support_counts),
        "total_location_support_count": sum(location_support_counts),
        "location_support_bundle_count": sum(
            1 for count in location_support_counts if count > 0
        ),
        "avg_emotion_response_support_count": _avg(emotion_response_support_counts),
        "total_emotion_response_support_count": sum(
            emotion_response_support_counts
        ),
        "emotion_response_support_bundle_count": sum(
            1 for count in emotion_response_support_counts if count > 0
        ),
        "avg_symbolic_meaning_support_count": _avg(
            symbolic_meaning_support_counts
        ),
        "total_symbolic_meaning_support_count": sum(
            symbolic_meaning_support_counts
        ),
        "symbolic_meaning_support_bundle_count": sum(
            1 for count in symbolic_meaning_support_counts if count > 0
        ),
        "avg_preference_support_count": _avg(preference_support_counts),
        "total_preference_support_count": sum(preference_support_counts),
        "preference_support_bundle_count": sum(
            1 for count in preference_support_counts if count > 0
        ),
        "avg_visual_support_count": _avg(visual_support_counts),
        "total_visual_support_count": sum(visual_support_counts),
        "visual_support_bundle_count": sum(
            1 for count in visual_support_counts if count > 0
        ),
        "total_location_relation_category_hit_count": sum(
            location_relation_category_hit_counts
        ),
        "avg_source_proximity_support_count": _avg(source_proximity_support_counts),
        "total_source_proximity_support_count": sum(source_proximity_support_counts),
        "source_proximity_bundle_count": sum(
            1 for count in source_proximity_support_counts if count > 0
        ),
        "avg_source_proximity_closest_distance": _avg(
            source_proximity_closest_distances
        ),
        "source_proximity_closest_distance_min": (
            min(source_proximity_closest_distances)
            if source_proximity_closest_distances
            else 0.0
        ),
        "source_proximity_distance_counts": dict(
            sorted(source_proximity_distance_counts.items())
        ),
        "avg_source_ref_support_item_count": _avg(source_ref_support_item_counts),
        "total_source_ref_support_item_count": sum(source_ref_support_item_counts),
        "source_ref_support_bundle_count": sum(
            1 for count in source_ref_support_item_counts if count > 0
        ),
        "avg_source_ref_support_ref_count": _avg(source_ref_support_ref_counts),
        "total_source_ref_support_ref_count": sum(source_ref_support_ref_counts),
        "avg_source_identity_item_count": _avg(source_identity_item_counts),
        "total_source_identity_item_count": sum(source_identity_item_counts),
        "source_identity_bundle_count": sum(
            1 for count in source_identity_item_counts if count > 0
        ),
        "avg_source_identity_ref_count": _avg(source_identity_ref_counts),
        "total_source_identity_ref_count": sum(source_identity_ref_counts),
        "avg_source_identity_support_item_count": _avg(
            source_identity_support_item_counts
        ),
        "total_source_identity_support_item_count": sum(
            source_identity_support_item_counts
        ),
        "source_identity_support_bundle_count": sum(
            1 for count in source_identity_support_item_counts if count > 0
        ),
        "avg_source_identity_support_ref_count": _avg(
            source_identity_support_ref_counts
        ),
        "total_source_identity_support_ref_count": sum(
            source_identity_support_ref_counts
        ),
        "avg_source_type_support_diversity": _avg(
            source_type_support_diversities
        ),
        "max_source_type_support_diversity": (
            max(source_type_support_diversities)
            if source_type_support_diversities
            else 0
        ),
        "avg_retrieval_source_support_diversity": _avg(
            retrieval_source_support_diversities
        ),
        "max_retrieval_source_support_diversity": (
            max(retrieval_source_support_diversities)
            if retrieval_source_support_diversities
            else 0
        ),
        "avg_contrast_count": _avg(contrast_counts),
        "total_contrast_count": sum(contrast_counts),
        "contrast_bundle_count": sum(1 for count in contrast_counts if count > 0),
        "avg_contrast_surface_count": _avg(contrast_surface_counts),
        "total_contrast_surface_count": sum(contrast_surface_counts),
        "contrast_surface_bundle_count": sum(
            1 for count in contrast_surface_counts if count > 0
        ),
        "avg_negative_absence_support_count": _avg(negative_absence_support_counts),
        "total_negative_absence_support_count": sum(
            negative_absence_support_counts
        ),
        "negative_absence_support_bundle_count": sum(
            1 for count in negative_absence_support_counts if count > 0
        ),
        "avg_negation_surface_count": _avg(negation_surface_counts),
        "total_negation_surface_count": sum(negation_surface_counts),
        "negation_surface_bundle_count": sum(
            1 for count in negation_surface_counts if count > 0
        ),
        "avg_currentness_surface_count": _avg(currentness_surface_counts),
        "total_currentness_surface_count": sum(currentness_surface_counts),
        "currentness_surface_bundle_count": sum(
            1 for count in currentness_surface_counts if count > 0
        ),
        "avg_stale_surface_count": _avg(stale_surface_counts),
        "total_stale_surface_count": sum(stale_surface_counts),
        "stale_surface_bundle_count": sum(
            1 for count in stale_surface_counts if count > 0
        ),
        "avg_selected_source_locality_score": _avg(selected_source_locality_scores),
        "avg_measured_selected_source_locality_score": _avg(
            measured_selected_source_locality_scores
        ),
        "total_unmeasured_selected_source_locality_count": sum(
            unmeasured_selected_source_locality_counts
        ),
        "avg_measured_answerability_score": _avg(measured_answerability_scores),
        "total_unmeasured_answerability_count": sum(unmeasured_answerability_counts),
        "avg_dropped_source_ref_overlap_count": _avg(
            dropped_source_ref_overlap_counts
        ),
        "total_dropped_source_ref_overlap_count": sum(
            dropped_source_ref_overlap_counts
        ),
        "source_ref_overlap_drop_bundle_count": sum(
            1 for count in dropped_source_ref_overlap_counts if count > 0
        ),
        "top_dropped_source_ref_overlap_keys": _top_counts(
            dropped_source_ref_overlap_keys
        ),
        "avg_dropped_noisy_source_overlap_count": _avg(
            dropped_noisy_source_overlap_counts
        ),
        "total_dropped_noisy_source_overlap_count": sum(
            dropped_noisy_source_overlap_counts
        ),
        "noisy_source_overlap_drop_bundle_count": sum(
            1 for count in dropped_noisy_source_overlap_counts if count > 0
        ),
        "top_dropped_noisy_source_overlap_keys": _top_counts(
            dropped_noisy_source_overlap_keys
        ),
        "weak_bundle_count": weak_count,
        "medium_or_high_bundle_count": medium_or_high_count,
        "confidence_band_counts": dict(sorted(band_counts.items())),
        "weak_support_bundle_count": weak_support_bundle_count,
        "weak_support_reason_counts": dict(sorted(weak_support_reason_counts.items())),
        "confidence_gap_bundle_count": confidence_gap_bundle_count,
        "confidence_gap_counts": dict(sorted(confidence_gap_counts.items())),
        "risk_reason_counts": {
            reason: count
            for reason, count in sorted(reason_counts.items())
            if reason.startswith("risk:")
        },
        "top_reason_counts": _top_counts(reason_counts),
        "confidence_gap_samples": confidence_gap_samples,
        "weak_samples": weak_samples,
    }


def bundle_quality_failure_breakdown(
    bundle_quality: Mapping[str, object],
    *,
    expected_case_count: int,
) -> dict[str, object]:
    medium_or_high_count = (
        _positive_int(bundle_quality.get("medium_or_high_bundle_count")) or 0
    )
    weak_count = _positive_int(bundle_quality.get("weak_bundle_count")) or 0
    return {
        "schema_version": "bundle_quality_failure_breakdown.v1",
        "required_medium_or_high_bundle_count": expected_case_count,
        "medium_or_high_bundle_count": medium_or_high_count,
        "medium_or_high_bundle_gap": max(
            0,
            expected_case_count - medium_or_high_count,
        ),
        "weak_bundle_count": weak_count,
        "confidence_gap_bundle_count": (
            _positive_int(bundle_quality.get("confidence_gap_bundle_count")) or 0
        ),
        "confidence_gap_counts": _count_mapping(
            bundle_quality.get("confidence_gap_counts")
        ),
        "risk_reason_counts": _count_mapping(bundle_quality.get("risk_reason_counts")),
        "top_reason_counts": _count_mapping(bundle_quality.get("top_reason_counts")),
        "confidence_gap_samples": list(
            _sequence(bundle_quality.get("confidence_gap_samples"))
        )[:5],
        "weak_samples": list(_sequence(bundle_quality.get("weak_samples")))[:5],
    }


def bundle_support_counts(bundle_quality: Mapping[str, object]) -> dict[str, int]:
    return {
        "bridge": _positive_int(bundle_quality.get("total_bridge_count")) or 0,
        "causal": (
            _positive_int(bundle_quality.get("total_causal_support_count")) or 0
        ),
        "communication": (
            _positive_int(bundle_quality.get("total_communication_support_count"))
            or 0
        ),
        "event": _positive_int(bundle_quality.get("total_event_support_count")) or 0,
        "exchange": (
            _positive_int(bundle_quality.get("total_exchange_support_count")) or 0
        ),
        "inference": (
            _positive_int(bundle_quality.get("total_inference_support_count")) or 0
        ),
        "location": (
            _positive_int(bundle_quality.get("total_location_support_count")) or 0
        ),
        "emotion_response": (
            _positive_int(
                bundle_quality.get("total_emotion_response_support_count")
            )
            or 0
        ),
        "symbolic_meaning": (
            _positive_int(
                bundle_quality.get("total_symbolic_meaning_support_count")
            )
            or 0
        ),
        "preference": (
            _positive_int(bundle_quality.get("total_preference_support_count")) or 0
        ),
        "visual": _positive_int(bundle_quality.get("total_visual_support_count")) or 0,
        "contrast": _positive_int(bundle_quality.get("total_contrast_count")) or 0,
        "source_proximity": (
            _positive_int(
                bundle_quality.get("total_source_proximity_support_count")
            )
            or 0
        ),
    }


def bundle_support_bundle_counts(
    bundle_quality: Mapping[str, object],
) -> dict[str, int]:
    return {
        "bridge": _positive_int(bundle_quality.get("bridge_bundle_count")) or 0,
        "causal": (
            _positive_int(bundle_quality.get("causal_support_bundle_count")) or 0
        ),
        "communication": (
            _positive_int(bundle_quality.get("communication_support_bundle_count"))
            or 0
        ),
        "event": _positive_int(bundle_quality.get("event_support_bundle_count")) or 0,
        "exchange": (
            _positive_int(bundle_quality.get("exchange_support_bundle_count")) or 0
        ),
        "inference": (
            _positive_int(bundle_quality.get("inference_support_bundle_count")) or 0
        ),
        "location": (
            _positive_int(bundle_quality.get("location_support_bundle_count")) or 0
        ),
        "emotion_response": (
            _positive_int(
                bundle_quality.get("emotion_response_support_bundle_count")
            )
            or 0
        ),
        "symbolic_meaning": (
            _positive_int(
                bundle_quality.get("symbolic_meaning_support_bundle_count")
            )
            or 0
        ),
        "preference": (
            _positive_int(bundle_quality.get("preference_support_bundle_count")) or 0
        ),
        "visual": _positive_int(bundle_quality.get("visual_support_bundle_count")) or 0,
        "contrast": _positive_int(bundle_quality.get("contrast_bundle_count")) or 0,
        "source_proximity": (
            _positive_int(bundle_quality.get("source_proximity_bundle_count")) or 0
        ),
    }


def _bundle_quality_sample(
    item: Mapping[str, object],
    quality: Mapping[str, object],
    *,
    extra_reason_codes: Sequence[str] = (),
) -> dict[str, object]:
    reason_codes = tuple(
        dict.fromkeys((*_str_tuple(quality.get("reason_codes")), *extra_reason_codes))
    )
    return {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "confidence_score": round(_metric_value(quality, "confidence_score"), 6),
        "confidence_band": str(quality.get("confidence_band") or "unknown"),
        "risk_penalty": round(_metric_value(quality, "risk_penalty"), 6),
        "reason_codes": reason_codes,
        "selected_item_count": _positive_int(quality.get("selected_item_count")) or 0,
        "primary_count": _positive_int(quality.get("primary_count")) or 0,
        "supporting_count": _positive_int(quality.get("supporting_count")) or 0,
        "source_ref_item_count": (
            _positive_int(quality.get("source_ref_item_count")) or 0
        ),
        "source_identity_item_count": (
            _positive_int(quality.get("source_identity_item_count")) or 0
        ),
        "source_identity_ref_count": (
            _positive_int(quality.get("source_identity_ref_count")) or 0
        ),
        "source_type_diversity": (
            _positive_int(quality.get("source_type_diversity")) or 0
        ),
        "retrieval_source_diversity": (
            _positive_int(quality.get("retrieval_source_diversity")) or 0
        ),
        "source_type_support_diversity": (
            _positive_int(quality.get("source_type_support_diversity")) or 0
        ),
        "retrieval_source_support_diversity": (
            _positive_int(quality.get("retrieval_source_support_diversity")) or 0
        ),
        "low_answerability_count": (
            _positive_int(quality.get("low_answerability_count")) or 0
        ),
        "causal_support_count": (
            _positive_int(quality.get("causal_support_count")) or 0
        ),
        "communication_support_count": (
            _positive_int(quality.get("communication_support_count")) or 0
        ),
        "event_support_count": (
            _positive_int(quality.get("event_support_count")) or 0
        ),
        "exchange_support_count": (
            _positive_int(quality.get("exchange_support_count")) or 0
        ),
        "inference_support_count": (
            _positive_int(quality.get("inference_support_count")) or 0
        ),
        "location_support_count": (
            _positive_int(quality.get("location_support_count")) or 0
        ),
        "emotion_response_support_count": (
            _positive_int(quality.get("emotion_response_support_count")) or 0
        ),
        "symbolic_meaning_support_count": (
            _positive_int(quality.get("symbolic_meaning_support_count")) or 0
        ),
        "preference_support_count": (
            _positive_int(quality.get("preference_support_count")) or 0
        ),
        "visual_support_count": (
            _positive_int(quality.get("visual_support_count")) or 0
        ),
        "location_relation_category_hit_count": (
            _positive_int(quality.get("location_relation_category_hit_count")) or 0
        ),
        "source_proximity_support_count": (
            _positive_int(quality.get("source_proximity_support_count")) or 0
        ),
        "source_proximity_closest_distance": (
            _positive_int(quality.get("source_proximity_closest_distance"))
        ),
        "source_proximity_distance_counts": dict(
            sorted(
                _count_mapping(
                    quality.get("source_proximity_distance_counts")
                ).items()
            )
        ),
        "contrast_count": _positive_int(quality.get("contrast_count")) or 0,
        "broad_summary_count": (
            _positive_int(quality.get("broad_summary_count")) or 0
        ),
        "conflict_or_stale_count": (
            _positive_int(quality.get("conflict_or_stale_count")) or 0
        ),
    }


def _confidence_gap_reasons(
    item: Mapping[str, object],
    *,
    band: str,
    weak_support_reasons: Sequence[str],
) -> tuple[str, ...]:
    bundle_complete = _bundle_complete(item)
    if band in {"medium", "high"}:
        reasons: list[str] = []
        if not bundle_complete:
            reasons.append("medium_or_high_incomplete_bundle")
        if weak_support_reasons:
            reasons.append("medium_or_high_weak_support")
        return tuple(reasons)
    if band in {"none", "low"} and bundle_complete and not weak_support_reasons:
        return ("low_confidence_complete_bundle",)
    return ()


def _confidence_gap_sample(
    item: Mapping[str, object],
    quality: Mapping[str, object],
    *,
    confidence_gap_reasons: Sequence[str],
    weak_support_reasons: Sequence[str],
    extra_reason_codes: Sequence[str],
) -> dict[str, object]:
    bundle = _mapping(item.get("evidence_bundle"))
    retrieval_quality = _mapping(item.get("retrieval_quality"))
    sample = _bundle_quality_sample(
        item,
        quality,
        extra_reason_codes=extra_reason_codes,
    )
    sample.update(
        {
            "bundle_complete": _bundle_complete(item),
            "item_count": _positive_int(bundle.get("item_count")) or 0,
            "confidence_gap_reasons": tuple(confidence_gap_reasons),
            "weak_support_reasons": tuple(weak_support_reasons),
            "covered_evidence_terms": _str_tuple(bundle.get("covered_evidence_terms")),
            "missing_evidence_terms": _str_tuple(
                retrieval_quality.get("missing_evidence_terms")
            ),
        }
    )
    return sample
