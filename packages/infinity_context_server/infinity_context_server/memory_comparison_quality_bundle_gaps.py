"""Bundle gap diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

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
    direct_source_refs_from_memory as _direct_source_refs_from_memory,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    fusion_source_refs as _fusion_source_refs,
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
    retrieval_results as _retrieval_results,
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
    source_refs_from_bundle_item as _source_refs_from_bundle_item,
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
_REF_SAMPLE_LIMIT = 8
_WEAK_PROVENANCE_LIMIT = 5
_SOURCE_LOCALITY_SAMPLE_LIMIT = 5
_SOURCE_LOCALITY_WINDOW_LIMIT = 3
_TURN_REF_RE = re.compile(
    r"\b(?:(?P<session>session_\d+):)?D(?P<source>\d+):(?P<turn>\d+)\b",
    re.IGNORECASE,
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
        if _bundle_complete(item):
            continue
        incomplete_case_count += 1
        item_reasons = _bundle_incomplete_reasons(item)
        reasons.update(item_reasons)
        if len(samples) < 10:
            missing_source_locality = _missing_evidence_source_locality(item, bundle)
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
                    "covered_evidence_terms": _bounded_refs(
                        bundle.get("covered_evidence_terms")
                    ),
                    "missing_evidence_terms": _bounded_refs(
                        _mapping(item.get("retrieval_quality")).get(
                            "missing_evidence_terms"
                        )
                    ),
                    **(
                        {
                            "missing_evidence_source_locality": (
                                missing_source_locality
                            )
                        }
                        if missing_source_locality
                        else {}
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
                "source_window_locality_samples": (
                    _source_window_locality_samples_for_reason(samples, reason)
                ),
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


def _bounded_refs(value: object) -> tuple[str, ...]:
    return _str_tuple(value)[:_REF_SAMPLE_LIMIT]


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


def _source_window_locality_samples_for_reason(
    samples: Sequence[object],
    reason: str,
) -> list[dict[str, object]]:
    locality_samples: list[dict[str, object]] = []
    for sample in samples:
        payload = _mapping(sample)
        if reason not in _str_tuple(payload.get("reasons")):
            continue
        locality = _mapping(payload.get("missing_evidence_source_locality"))
        if not locality:
            continue
        locality_samples.append(
            {
                "case_id": str(payload.get("case_id") or ""),
                "missing_turn_ref_count": (
                    _positive_int(locality.get("missing_turn_ref_count")) or 0
                ),
                "same_source_missing_count": (
                    _positive_int(locality.get("same_source_missing_count")) or 0
                ),
                "near_retrieved_window_count": (
                    _positive_int(locality.get("near_retrieved_window_count")) or 0
                ),
                "source_absent_count": (
                    _positive_int(locality.get("source_absent_count")) or 0
                ),
                "missing_ref_windows": list(
                    _sequence(locality.get("missing_ref_windows"))
                )[:_SOURCE_LOCALITY_WINDOW_LIMIT],
            }
        )
        if len(locality_samples) >= _SOURCE_LOCALITY_SAMPLE_LIMIT:
            break
    return locality_samples


def _missing_evidence_source_locality(
    item: Mapping[str, object],
    bundle: Mapping[str, object],
) -> dict[str, object]:
    missing_refs = _turn_refs(
        _str_tuple(
            _mapping(item.get("retrieval_quality")).get("missing_evidence_terms")
        )
    )
    if not missing_refs:
        return {}
    retrieval_turns = _source_turns(
        source_ref
        for memory in _retrieval_results((item,))
        for source_ref in _safe_memory_source_refs(memory)
    )
    bundle_turns = _source_turns(
        source_ref
        for bundle_item in _bundle_items(bundle)
        for source_ref in _source_refs_from_bundle_item(bundle_item)
    )
    windows = [
        _missing_ref_window(
            ref,
            retrieval_turns=retrieval_turns,
            bundle_turns=bundle_turns,
        )
        for ref in missing_refs
    ]
    same_source_missing_count = sum(
        1 for window in windows if window["retrieved_same_source"] is True
    )
    near_retrieved_window_count = sum(
        1
        for window in windows
        if (
            isinstance(window.get("nearest_retrieved_turn_distance"), int)
            and int(window["nearest_retrieved_turn_distance"]) <= 2
        )
    )
    return {
        "schema_version": "missing_evidence_source_locality.v1",
        "missing_turn_ref_count": len(missing_refs),
        "retrieved_source_id_count": len(retrieval_turns),
        "bundle_source_id_count": len(bundle_turns),
        "same_source_missing_count": same_source_missing_count,
        "near_retrieved_window_count": near_retrieved_window_count,
        "source_absent_count": len(missing_refs) - same_source_missing_count,
        "missing_ref_windows": windows[:_SOURCE_LOCALITY_WINDOW_LIMIT],
    }


def _missing_ref_window(
    ref: tuple[str, int],
    *,
    retrieval_turns: Mapping[str, tuple[int, ...]],
    bundle_turns: Mapping[str, tuple[int, ...]],
) -> dict[str, object]:
    source_id, turn = ref
    nearest_retrieved = _nearest_turn(source_id, turn, retrieval_turns)
    nearest_bundle = _nearest_turn(source_id, turn, bundle_turns)
    window: dict[str, object] = {
        "ref": f"{source_id}:{turn}",
        "source_id": source_id,
        "retrieved_same_source": source_id in retrieval_turns,
        "bundle_same_source": source_id in bundle_turns,
    }
    if nearest_retrieved is not None:
        nearest_turn, distance = nearest_retrieved
        window["nearest_retrieved_turn_ref"] = f"{source_id}:{nearest_turn}"
        window["nearest_retrieved_turn_distance"] = distance
    if nearest_bundle is not None:
        nearest_turn, distance = nearest_bundle
        window["nearest_bundle_turn_ref"] = f"{source_id}:{nearest_turn}"
        window["nearest_bundle_turn_distance"] = distance
    return window


def _safe_memory_source_refs(memory: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *_direct_source_refs_from_memory(memory),
                *_fusion_source_refs(memory),
            )
        )
    )


def _nearest_turn(
    source_id: str,
    turn: int,
    source_turns: Mapping[str, tuple[int, ...]],
) -> tuple[int, int] | None:
    turns = source_turns.get(source_id)
    if not turns:
        return None
    nearest = min(turns, key=lambda candidate: (abs(candidate - turn), candidate))
    return nearest, abs(nearest - turn)


def _source_turns(values: Iterable[str]) -> dict[str, tuple[int, ...]]:
    turns_by_source: dict[str, set[int]] = defaultdict(set)
    for source_id, turn in _turn_refs(values):
        turns_by_source[source_id].add(turn)
    return {
        source_id: tuple(sorted(turns))
        for source_id, turns in sorted(turns_by_source.items())
    }


def _turn_refs(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    refs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        for match in _TURN_REF_RE.finditer(str(value)):
            source_id = f"D{match.group('source')}"
            session_id = str(match.group("session") or "").strip().lower()
            if session_id:
                source_id = f"{session_id}:{source_id}"
            ref = (source_id, int(match.group("turn")))
            if ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


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
