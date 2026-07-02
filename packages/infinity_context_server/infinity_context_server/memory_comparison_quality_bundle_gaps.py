"""Bundle gap diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
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
    retrieval_metadata as _retrieval_metadata,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    selected_measured_source_locality_score as _selected_measured_source_locality_score,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    selected_source_locality_score as _selected_source_locality_score,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    unmeasured_selected_source_locality_count as _unmeasured_selected_source_locality_count,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_causal_support as _bundle_has_causal_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_communication_support as _bundle_has_communication_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_contrast_support as _bundle_has_contrast_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_emotion_response_support as _bundle_has_emotion_response_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_event_support as _bundle_has_event_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_exchange_support as _bundle_has_exchange_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_inference_support as _bundle_has_inference_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_location_support as _bundle_has_location_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_planner_reason as _bundle_has_planner_reason,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_preference_support as _bundle_has_preference_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_symbolic_meaning_support as _bundle_has_symbolic_meaning_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_temporal_support as _bundle_has_temporal_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_has_visual_support as _bundle_has_visual_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    bundle_roles as _bundle_roles,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_causal_support as _needs_causal_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_communication_support as _needs_communication_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_contrast_evidence as _needs_contrast_evidence,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_emotion_response_support as _needs_emotion_response_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_event_support as _needs_event_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_exchange_support as _needs_exchange_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_inference_support as _needs_inference_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_location_support as _needs_location_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_preference_support as _needs_preference_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_symbolic_meaning_support as _needs_symbolic_meaning_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_temporal_support as _needs_temporal_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_visual_support as _needs_visual_support,
)

_BRIDGE_GAP_REASONS = frozenset(
    {
        "missing_bridge",
        "missing_bridge_entity",
        "missing_bridge_relation",
        "missing_temporal_bridge",
        "weak_source_locality",
    }
)
_EVIDENCE_NEED_GAP_REASONS = frozenset(
    {
        "missing_causal_support",
        "missing_communication_support",
        "missing_event_support",
        "missing_exchange_support",
        "missing_contrast",
        "missing_emotion_response_support",
        "missing_inference_support",
        "missing_location_support",
        "missing_preference_support",
        "missing_symbolic_meaning_support",
        "missing_visual_support",
        "missing_required_bridge",
        "missing_required_causal_support",
        "missing_required_communication_support",
        "missing_required_contrast",
        "missing_required_event_support",
        "missing_required_exchange_support",
        "missing_required_emotion_response_support",
        "missing_required_inference_support",
        "missing_required_location_support",
        "missing_required_preference_support",
        "missing_required_symbolic_meaning_support",
        "missing_required_temporal_support",
        "missing_required_visual_support",
        "missing_temporal_support",
    }
)


def bundle_incomplete_diagnostics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    reasons: Counter[str] = Counter()
    samples: list[dict[str, object]] = []
    incomplete_case_count = 0
    for item in items:
        if item.get("scored") is not True:
            continue
        bundle = _mapping(item.get("evidence_bundle"))
        if bool(bundle.get("bundle_complete")):
            continue
        incomplete_case_count += 1
        item_reasons = _bundle_incomplete_reasons(item)
        reasons.update(item_reasons)
        if len(samples) < 10:
            samples.append(
                {
                    "case_id": str(item.get("case_id") or ""),
                    "group": str(item.get("group") or ""),
                    "reasons": list(item_reasons),
                    "item_count": _positive_int(bundle.get("item_count")) or 0,
                    "bundle_roles": sorted(_bundle_roles(bundle)),
                    "average_selected_source_locality_score": round(
                        _selected_source_locality_score(item),
                        6,
                    ),
                    "average_measured_selected_source_locality_score": round(
                        _selected_measured_source_locality_score(item),
                        6,
                    ),
                    "unmeasured_selected_source_locality_count": (
                        _unmeasured_selected_source_locality_count(item)
                    ),
                    "covered_evidence_terms": _str_tuple(
                        bundle.get("covered_evidence_terms")
                    ),
                    "missing_evidence_terms": _str_tuple(
                        _mapping(item.get("retrieval_quality")).get(
                            "missing_evidence_terms"
                        )
                    ),
                }
            )
    return {
        "count": sum(reasons.values()),
        "case_count": incomplete_case_count,
        "reason_counts": dict(sorted(reasons.items())),
        "samples": samples,
    }


def bundle_gap_breakdown(bundle_incomplete: Mapping[str, object]) -> dict[str, object]:
    reason_counts = _mapping(bundle_incomplete.get("reason_counts"))
    bridge_gap_reason_counts = {
        reason: count
        for reason, count in sorted(reason_counts.items())
        if str(reason) in _BRIDGE_GAP_REASONS
    }
    evidence_need_gap_reason_counts = {
        reason: count
        for reason, count in sorted(reason_counts.items())
        if str(reason) in _EVIDENCE_NEED_GAP_REASONS
    }
    return {
        "schema_version": "bundle_gap_breakdown.v1",
        "incomplete_case_count": _positive_int(bundle_incomplete.get("case_count"))
        or 0,
        "reason_total": _positive_int(bundle_incomplete.get("count")) or 0,
        "reason_counts": dict(sorted(reason_counts.items())),
        "bridge_gap_reason_counts": bridge_gap_reason_counts,
        "evidence_need_gap_reason_counts": evidence_need_gap_reason_counts,
        "top_reasons": dict(
            sorted(
                reason_counts.items(),
                key=lambda pair: (-int(pair[1]), str(pair[0])),
            )[:10]
        ),
        "samples": list(_sequence(bundle_incomplete.get("samples")))[:5],
    }


def _bundle_incomplete_reasons(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    quality = _mapping(item.get("retrieval_quality"))
    require_grounding = _query_has_entities(item)
    reasons: list[str] = []
    if (_positive_int(bundle.get("item_count")) or 0) == 0:
        reasons.append("no_bundle_items")
    if (_positive_int(bundle.get("primary_evidence_count")) or 0) == 0:
        reasons.append("missing_primary")
    if (_positive_int(bundle.get("supporting_evidence_count")) or 0) == 0:
        reasons.append("missing_supporting")
    if _str_tuple(quality.get("missing_evidence_terms")):
        reasons.append("missing_evidence_refs")
    if _metric_value(bundle, "query_support_term_recall") == 0:
        reasons.append("no_query_support_recall")
    if not any(
        _metric_value(item, "focused_evidence_score") > 0
        for item in _bundle_items(bundle)
    ):
        reasons.append("no_focused_evidence")
    if _needs_contrast_evidence(item) and not _bundle_has_contrast_support(bundle):
        reasons.append("missing_contrast")
    if _needs_causal_support(item) and not _bundle_has_causal_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_causal_support")
    if _needs_communication_support(item) and not _bundle_has_communication_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_communication_support")
    if _needs_event_support(item) and not _bundle_has_event_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_event_support")
    if _needs_exchange_support(item) and not _bundle_has_exchange_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_exchange_support")
    if _needs_inference_support(item) and not _bundle_has_inference_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_inference_support")
    if _needs_location_support(item) and not _bundle_has_location_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_location_support")
    if (
        _needs_emotion_response_support(item)
        and not _bundle_has_emotion_response_support(
            bundle,
            require_grounding=require_grounding,
        )
    ):
        reasons.append("missing_emotion_response_support")
    if (
        _needs_symbolic_meaning_support(item)
        and not _bundle_has_symbolic_meaning_support(
            bundle,
            require_grounding=require_grounding,
        )
    ):
        reasons.append("missing_symbolic_meaning_support")
    if _needs_preference_support(item) and not _bundle_has_preference_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_preference_support")
    if _needs_visual_support(item) and not _bundle_has_visual_support(
        bundle,
        require_grounding=require_grounding,
    ):
        reasons.append("missing_visual_support")
    if _needs_temporal_support(item) and not _bundle_has_temporal_support(bundle):
        reasons.append("missing_temporal_support")
    for role in _str_tuple(bundle.get("missing_required_roles")):
        reasons.append(f"missing_required_{role}")
    reasons.extend(_multi_hop_bundle_gap_reasons(item, bundle))
    return tuple(dict.fromkeys(reasons or ("unknown_bundle_gap",)))


def _query_has_entities(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    retrieval_intent = _mapping(query_decomposition.get("retrieval_intent"))
    return bool(
        _str_tuple(query_profile.get("entities"))
        or _str_tuple(query_profile.get("entity_surfaces"))
        or _str_tuple(query_profile.get("speaker_surfaces"))
        or _sequence(retrieval_intent.get("entities"))
        or _positive_int(retrieval_intent.get("entity_count"))
    )


def _multi_hop_bundle_gap_reasons(
    item: Mapping[str, object],
    bundle: Mapping[str, object],
) -> tuple[str, ...]:
    if not _is_multi_hop_item(item):
        return ()
    bundle_items = _bundle_items(bundle)
    if not bundle_items:
        return ()

    reasons: list[str] = []
    if "bridge" not in _bundle_roles(bundle):
        reasons.append("missing_bridge")
    if not _bundle_has_planner_reason(bundle, "bridge_entity_hits"):
        reasons.append("missing_bridge_entity")
    if not _bundle_has_planner_reason(bundle, "bridge_relation_hits"):
        reasons.append("missing_bridge_relation")
    if _needs_temporal_support(item) and not _bundle_has_temporal_support(bundle):
        reasons.append("missing_temporal_bridge")
    locality_score = _selected_measured_source_locality_score(item)
    if locality_score and locality_score < 0.5:
        reasons.append("weak_source_locality")
    return tuple(reasons)


def _is_multi_hop_item(item: Mapping[str, object]) -> bool:
    if str(item.get("group") or "").replace("_", "-") == "multi-hop":
        return True
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    retrieval_intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = tuple(
        dict.fromkeys(
            _str_tuple(query_profile.get("evidence_need"))
            + _str_tuple(retrieval_intent.get("evidence_need"))
        )
    )
    multi_hop_markers = tuple(
        dict.fromkeys(
            _str_tuple(query_profile.get("multi_hop_markers"))
            + _str_tuple(retrieval_intent.get("multi_hop_markers"))
        )
    )
    if multi_hop_markers:
        return True
    return any(
        need in {"multi_hop", "multi-hop", "inference_support"}
        for need in evidence_need
    )
