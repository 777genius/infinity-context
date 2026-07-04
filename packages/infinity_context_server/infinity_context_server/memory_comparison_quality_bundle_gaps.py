"""Bundle gap diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_complete as _bundle_complete,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
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
from infinity_context_server.memory_comparison_quality_accessors import ratio as _ratio
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
    bundle_has_typed_relation_support as _bundle_has_typed_relation_support,
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
    needs_typed_relation_support_roles as _needs_typed_relation_support_roles,
)
from infinity_context_server.memory_comparison_quality_support import (
    needs_visual_support as _needs_visual_support,
)
from infinity_context_server.memory_comparison_quality_support import (
    typed_relation_support_roles as _typed_relation_support_roles,
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
        "missing_typed_relation_support",
        *(
            f"missing_{role}"
            for role in _typed_relation_support_roles()
        ),
        *(
            f"missing_required_{role}"
            for role in _typed_relation_support_roles()
        ),
    }
)
_COVERAGE_GAP_LIMIT = 5
_WEAK_PROVENANCE_LIMIT = 5


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
        if _bundle_complete(item):
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


def evidence_bundle_gap_report(
    *,
    evaluation_count: int,
    bundle_gap_breakdown: Mapping[str, object],
    source_ref_provenance: Mapping[str, object],
    answer_context_provenance: Mapping[str, object],
) -> dict[str, object]:
    """Compact evidence bundle coverage and provenance gaps for LoCoMo triage."""
    evaluation_count = max(0, evaluation_count)
    reason_counts = _count_mapping(bundle_gap_breakdown.get("reason_counts"))
    coverage_gaps = _coverage_gap_rows(
        reason_counts,
        evaluation_count=evaluation_count,
        samples=_sequence(bundle_gap_breakdown.get("samples")),
    )
    weak_provenance = _weak_provenance_rows(
        source_ref_provenance,
        answer_context_provenance,
    )
    status = "gaps_found" if coverage_gaps or weak_provenance else "no_observed_gaps"
    return {
        "schema_version": "evidence_bundle_gap_report.v1",
        "status": status,
        "evaluation_count": evaluation_count,
        "incomplete_case_count": (
            _positive_int(bundle_gap_breakdown.get("incomplete_case_count")) or 0
        ),
        "coverage_gap_reason_total": (
            _positive_int(bundle_gap_breakdown.get("reason_total")) or 0
        ),
        "coverage_gap_count": len(coverage_gaps),
        "weak_provenance_signal_count": len(weak_provenance),
        "top_coverage_gaps": coverage_gaps,
        "weak_provenance_signals": weak_provenance,
        "top_action": (
            str((coverage_gaps or weak_provenance)[0].get("action") or "")
            if (coverage_gaps or weak_provenance)
            else ""
        ),
    }


def _coverage_gap_rows(
    reason_counts: Mapping[str, int],
    *,
    evaluation_count: int,
    samples: Sequence[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for reason, count in sorted(
        reason_counts.items(),
        key=lambda pair: (-int(pair[1]), str(pair[0])),
    )[:_COVERAGE_GAP_LIMIT]:
        rows.append(
            {
                "reason": reason,
                "count": count,
                "case_rate": _ratio(count, evaluation_count),
                "action": _coverage_gap_action(reason),
                "sample_case_ids": _sample_case_ids_for_reason(samples, reason),
            }
        )
    return rows


def _weak_provenance_rows(
    source_ref_provenance: Mapping[str, object],
    answer_context_provenance: Mapping[str, object],
) -> list[dict[str, object]]:
    signals = (
        _weak_provenance_signal(
            name="selected_bundle_source_refless_items",
            count=(
                _positive_int(
                    source_ref_provenance.get(
                        "selected_bundle_source_refless_item_count"
                    )
                )
                or 0
            ),
            denominator=(
                _positive_int(source_ref_provenance.get("selected_bundle_item_count"))
                or 0
            ),
            action="Attach canonical source_refs to selected bundle evidence.",
            samples=_sequence(
                source_ref_provenance.get("source_refless_selected_samples")
            ),
        ),
        _weak_provenance_signal(
            name="answer_context_source_refless_items",
            count=(
                _positive_int(answer_context_provenance.get("source_refless_item_count"))
                or 0
            ),
            denominator=(
                _positive_int(answer_context_provenance.get("memory_count")) or 0
            ),
            action="Keep answer context evidence tied to source-bearing bundle items.",
            samples=_sequence(
                answer_context_provenance.get("source_refless_context_samples")
            ),
        ),
        _weak_provenance_signal(
            name="mixed_source_answer_contexts",
            count=(
                _positive_int(answer_context_provenance.get("mixed_source_context_count"))
                or 0
            ),
            denominator=(
                _positive_int(answer_context_provenance.get("context_count")) or 0
            ),
            action="Avoid mixing source-backed and source-less context items.",
            samples=_sequence(
                answer_context_provenance.get("mixed_source_context_samples")
            ),
        ),
        _weak_provenance_signal(
            name="backfilled_answer_contexts",
            count=(
                _positive_int(answer_context_provenance.get("backfilled_context_count"))
                or 0
            ),
            denominator=(
                _positive_int(answer_context_provenance.get("context_count")) or 0
            ),
            action="Prefer complete evidence bundles before answer-context backfill.",
            samples=_sequence(
                answer_context_provenance.get("backfilled_context_samples")
            ),
        ),
        _weak_provenance_signal(
            name="missing_required_role_contexts",
            count=(
                _positive_int(
                    answer_context_provenance.get("missing_required_role_context_count")
                )
                or 0
            ),
            denominator=(
                _positive_int(answer_context_provenance.get("context_count")) or 0
            ),
            action="Repair bundle role coverage before rendering answer context.",
            samples=_sequence(
                answer_context_provenance.get("backfill_skip_context_samples")
            ),
            evidence={
                "role_counts": _count_mapping(
                    answer_context_provenance.get("missing_required_role_counts")
                )
            },
        ),
    )
    return [
        signal
        for signal in sorted(
            (signal for signal in signals if signal["count"] > 0),
            key=lambda payload: (-int(payload["count"]), str(payload["name"])),
        )[:_WEAK_PROVENANCE_LIMIT]
    ]


def _weak_provenance_signal(
    *,
    name: str,
    count: int,
    denominator: int,
    action: str,
    samples: Sequence[object],
    evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    signal: dict[str, object] = {
        "name": name,
        "count": count,
        "rate": _ratio(count, denominator),
        "action": action,
        "sample_case_ids": _sample_case_ids(samples),
    }
    if evidence:
        signal["evidence"] = dict(evidence)
    return signal


def _coverage_gap_action(reason: str) -> str:
    if reason == "no_bundle_items":
        return "Inspect bundle selection before answer-context fallback."
    if reason == "missing_primary":
        return "Select one direct primary evidence item for each scored case."
    if reason == "missing_supporting":
        return "Add supporting evidence for multi-fact or role-specific questions."
    if reason == "missing_evidence_refs":
        return "Verify evidence-term coverage for expected LoCoMo turn refs."
    if reason == "no_focused_evidence":
        return "Prefer focused turn evidence over broad or generic bundle items."
    if reason == "weak_source_locality":
        return "Prefer localized source-turn evidence over distant summaries."
    if reason.startswith("missing_required_"):
        return "Add role-specific evidence selection for required bundle roles."
    if reason.startswith("missing_"):
        return "Add evidence selection for this missing coverage role."
    return "Review bundle planner coverage for this gap reason."


def _sample_case_ids_for_reason(
    samples: Sequence[object],
    reason: str,
) -> list[str]:
    return _sample_case_ids(
        sample
        for sample in samples
        if reason in _str_tuple(_mapping(sample).get("reasons"))
    )


def _sample_case_ids(samples: Sequence[object]) -> list[str]:
    case_ids: list[str] = []
    for sample in samples:
        case_id = str(_mapping(sample).get("case_id") or "").strip()
        if case_id and case_id not in case_ids:
            case_ids.append(case_id)
        if len(case_ids) >= 5:
            break
    return case_ids


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
    for role in _needs_typed_relation_support_roles(item):
        if not _bundle_has_typed_relation_support(
            bundle,
            role,
            require_grounding=require_grounding,
        ):
            reasons.append("missing_typed_relation_support")
            reasons.append(f"missing_{role}")
    planner = _mapping(bundle.get("bundle_planner"))
    for role in tuple(
        dict.fromkeys(
            (
                *_str_tuple(bundle.get("missing_required_roles")),
                *_str_tuple(planner.get("missing_required_roles")),
            )
        )
    ):
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
