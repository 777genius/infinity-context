"""Aggregate quality diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

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
        "missing_event_support",
        "missing_contrast",
        "missing_emotion_response_support",
        "missing_inference_support",
        "missing_location_support",
        "missing_preference_support",
        "missing_symbolic_meaning_support",
        "missing_visual_support",
        "missing_required_bridge",
        "missing_required_causal_support",
        "missing_required_contrast",
        "missing_required_event_support",
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


def evidence_ref_rank_gate_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    cutoffs = (1, 2, 3, 5)
    cutoff_counts = {cutoff: 0 for cutoff in cutoffs}
    focused_top5_count = 0
    complete_count = 0
    samples: list[dict[str, object]] = []
    evidence_items = [
        item
        for item in items
        if item.get("scored") is True
        and _positive_int(_mapping(item.get("evidence_bundle")).get("evidence_term_count"))
    ]
    for item in evidence_items:
        bundle = _mapping(item.get("evidence_bundle"))
        required_refs = _required_evidence_refs(item)
        ref_positions, focused_ref_positions = _bundle_evidence_ref_positions(bundle)
        complete = bool(required_refs) and all(ref in ref_positions for ref in required_refs)
        if complete:
            complete_count += 1
        for cutoff in cutoffs:
            if required_refs and all(
                ref_positions.get(ref, 9999) <= cutoff for ref in required_refs
            ):
                cutoff_counts[cutoff] += 1
        if required_refs and all(
            focused_ref_positions.get(ref, 9999) <= 5 for ref in required_refs
        ):
            focused_top5_count += 1
        if len(samples) < 10 and (
            not complete or any(ref_positions.get(ref, 9999) > 5 for ref in required_refs)
        ):
            samples.append(_evidence_ref_failure_sample(item, required_refs, ref_positions))
    total = len(evidence_items)
    return {
        "evaluation_count": total,
        "bundle_complete_count": complete_count,
        "all_refs_top1_count": cutoff_counts[1],
        "all_refs_top2_count": cutoff_counts[2],
        "all_refs_top3_count": cutoff_counts[3],
        "all_refs_top5_count": cutoff_counts[5],
        "focused_refs_top5_count": focused_top5_count,
        "all_refs_top1_rate": _ratio(cutoff_counts[1], total),
        "all_refs_top2_rate": _ratio(cutoff_counts[2], total),
        "all_refs_top3_rate": _ratio(cutoff_counts[3], total),
        "all_refs_top5_rate": _ratio(cutoff_counts[5], total),
        "focused_refs_top5_rate": _ratio(focused_top5_count, total),
        "all_refs_top5_ok": bool(total) and cutoff_counts[5] == total,
        "focused_refs_top5_ok": bool(total) and focused_top5_count == total,
        "samples": samples,
    }


def quality_diagnostics(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "quality_diagnostics.v2",
        "evaluation_count": len(items),
        "per_intent": _per_intent_metrics(items),
        "bundle_incomplete": _bundle_incomplete_diagnostics(items),
        "bundle_quality_table": _bundle_quality_table(items),
        "policy_contribution_table": _policy_contribution_table(items),
        "evidence_feature_table": _evidence_feature_table(items),
        "source_ref_provenance_table": _source_ref_provenance_table(items),
        "answer_context_provenance_table": _answer_context_provenance_table(items),
        "query_role_effectiveness_table": _query_role_effectiveness_table(items),
        "query_plan_integrity_table": _query_plan_integrity_table(items),
        "risk_flag_table": _risk_flag_table(items),
        "rerank_lift_table": _rerank_lift_table(items),
        "false_positive_categories": _false_positive_categories(items),
        "query_leakage_report": _query_leakage_report(items),
    }


def fast_gate_metrics(
    items: Sequence[Mapping[str, object]],
    *,
    expected_case_count: int = 40,
) -> dict[str, object]:
    expected_case_count = max(1, expected_case_count)
    scored_count = sum(1 for item in items if item.get("scored") is True)
    bundle_complete_count = sum(1 for item in items if _bundle_complete(item))
    ref_gate = evidence_ref_rank_gate_metrics(items)
    query_overlap_count, profile_overlap_count = _leakage_counts(items)
    bundle_quality = _bundle_quality_table(items)
    bundle_incomplete = _bundle_incomplete_diagnostics(items)
    query_role_effectiveness = _query_role_effectiveness_table(items)
    query_plan_integrity = _query_plan_integrity_table(items)
    risk_flag_table = _risk_flag_table(items)
    source_ref_provenance = _source_ref_provenance_table(items)
    answer_context_provenance = _answer_context_provenance_table(items)
    bundle_quality_count = _positive_int(bundle_quality.get("bundle_count")) or 0
    medium_or_high_bundle_count = (
        _positive_int(bundle_quality.get("medium_or_high_bundle_count")) or 0
    )
    gates = {
        "case_count": _min_gate(scored_count, expected_case_count),
        "query_profile_leakage_zero": _zero_gate(
            query_overlap_count + profile_overlap_count
        ),
        "all_refs_top5": _min_gate(
            _positive_int(ref_gate.get("all_refs_top5_count")) or 0,
            expected_case_count,
        ),
        "focused_refs_top5": _min_gate(
            _positive_int(ref_gate.get("focused_refs_top5_count")) or 0,
            expected_case_count,
        ),
        "all_refs_top3": _min_gate(
            _positive_int(ref_gate.get("all_refs_top3_count")) or 0,
            max(0, expected_case_count - 1),
        ),
        "all_refs_top2": _min_gate(
            _positive_int(ref_gate.get("all_refs_top2_count")) or 0,
            max(0, expected_case_count - 4),
        ),
        "all_refs_top1": _min_gate(
            _positive_int(ref_gate.get("all_refs_top1_count")) or 0,
            max(0, expected_case_count - 10),
        ),
        "evidence_bundle_complete": _min_gate(
            bundle_complete_count,
            expected_case_count,
        ),
    }
    if bundle_quality_count:
        gates["bundle_quality_present"] = _min_gate(
            bundle_quality_count,
            expected_case_count,
        )
        gates["bundle_quality_medium_or_high"] = _min_gate(
            medium_or_high_bundle_count,
            expected_case_count,
        )
    failed_gates = tuple(name for name, gate in gates.items() if not gate["passed"])
    return {
        "schema_version": "fast_gate.v1",
        "expected_case_count": expected_case_count,
        "evaluation_count": scored_count,
        "evidence_ref_evaluation_count": ref_gate["evaluation_count"],
        "passed": not failed_gates,
        "ready_for_full_locomo": not failed_gates,
        "failed_gates": list(failed_gates),
        "query_overlap_count": query_overlap_count,
        "profile_overlap_count": profile_overlap_count,
        "bundle_quality_gate_applied": bool(bundle_quality_count),
        "bundle_quality_count": bundle_quality_count,
        "weak_bundle_count": _positive_int(bundle_quality.get("weak_bundle_count")) or 0,
        "bundle_support_counts": _bundle_support_counts(bundle_quality),
        "bundle_support_bundle_counts": _bundle_support_bundle_counts(bundle_quality),
        "bundle_gap_breakdown": _bundle_gap_breakdown(bundle_incomplete),
        "query_role_gap_breakdown": _query_role_gap_breakdown(
            query_role_effectiveness
        ),
        "query_plan_gap_breakdown": _query_plan_gap_breakdown(query_plan_integrity),
        "source_ref_provenance": source_ref_provenance,
        "answer_context_provenance": answer_context_provenance,
        "risk_flag_table": risk_flag_table,
        "gates": gates,
    }


def _per_intent_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for item in items:
        for key in _intent_keys(item):
            groups[key].append(item)
    return {
        key: _intent_metric_payload(group_items)
        for key, group_items in sorted(groups.items())
    }


def _intent_keys(item: Mapping[str, object]) -> tuple[str, ...]:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    rerank = _mapping(metadata.get("benchmark_rerank"))
    query_profile = _mapping(
        query_decomposition.get("query_profile") or rerank.get("query_profile")
    )
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = _str_tuple(query_profile.get("evidence_need")) or _str_tuple(
        intent.get("evidence_need")
    )
    bundle_evidence_roles = _str_tuple(
        query_profile.get("bundle_evidence_roles")
    ) or _str_tuple(intent.get("bundle_evidence_roles"))
    relation_categories = _str_tuple(
        query_profile.get("relation_categories")
    ) or _relation_categories(intent)
    time_intent = _mapping(intent.get("time_intent"))
    time_kind = str(time_intent.get("kind") or "").strip()
    keys = [f"need:{need}" for need in evidence_need]
    keys.extend(f"role:{role}" for role in bundle_evidence_roles)
    keys.extend(f"relation:{category}" for category in relation_categories)
    if time_kind and time_kind != "none":
        keys.append(f"time:{time_kind}")
    if not keys:
        keys.append("need:unknown")
    return tuple(dict.fromkeys(keys))


def _relation_categories(intent: Mapping[str, object]) -> tuple[str, ...]:
    relations = _mapping(intent.get("relations"))
    categories: list[str] = []
    for relation_intent in _sequence(relations.get("intents")):
        payload = _mapping(relation_intent)
        category = str(payload.get("category") or "").strip()
        if category:
            categories.append(category)
    return tuple(dict.fromkeys(categories))


def _intent_metric_payload(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    scored = [item for item in items if item.get("scored") is True]
    passed = sum(1 for item in scored if _judgment_score(item) >= 1.0)
    return {
        "total": len(items),
        "scored": len(scored),
        "passed": passed,
        "accuracy": _ratio(passed, len(scored)),
        "avg_expected_term_recall": _avg(_expected_recall(item) for item in scored),
        "avg_evidence_term_recall": _avg(
            _evidence_recall(item)
            for item in scored
            if "evidence_term_recall" in _mapping(item.get("retrieval_quality"))
        ),
        "bundle_complete_rate": _ratio(
            sum(1 for item in scored if _bundle_complete(item)),
            len(scored),
        ),
    }


def _risk_flag_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    no_risk_count = 0
    for item in items:
        flags = _intent_risk_flags(item)
        if not flags:
            no_risk_count += 1
            continue
        for flag in flags:
            groups[flag].append(item)
    return {
        "schema_version": "retrieval_intent_risk_flags.v1",
        "evaluation_count": len(items),
        "risk_flag_case_count": sum(
            1 for item in items if _intent_risk_flags(item)
        ),
        "no_risk_flag_case_count": no_risk_count,
        "flag_counts": {
            flag: len(flag_items) for flag, flag_items in sorted(groups.items())
        },
        "flag_stats": {
            flag: _risk_flag_stats(flag_items)
            for flag, flag_items in sorted(groups.items())
        },
    }


def _risk_flag_stats(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    scored = [item for item in items if item.get("scored") is True]
    passed = sum(1 for item in scored if _judgment_score(item) >= 1.0)
    query_overlap_count = 0
    profile_overlap_count = 0
    for item in items:
        integrity = _query_integrity(item)
        query_overlap_count += (
            _positive_int(integrity.get("expected_answer_query_overlap_count")) or 0
        )
        profile_overlap_count += (
            _positive_int(
                integrity.get("expected_answer_query_profile_overlap_count")
            )
            or 0
        )
    return {
        "case_count": len(items),
        "scored": len(scored),
        "passed": passed,
        "accuracy": _ratio(passed, len(scored)),
        "bundle_complete_count": sum(1 for item in scored if _bundle_complete(item)),
        "bundle_complete_rate": _ratio(
            sum(1 for item in scored if _bundle_complete(item)),
            len(scored),
        ),
        "query_overlap_count": query_overlap_count,
        "profile_overlap_count": profile_overlap_count,
        "avg_expected_term_recall": _avg(_expected_recall(item) for item in scored),
        "avg_evidence_term_recall": _avg(
            _evidence_recall(item)
            for item in scored
            if "evidence_term_recall" in _mapping(item.get("retrieval_quality"))
        ),
        "samples": [
            {
                "case_id": str(item.get("case_id") or ""),
                "group": str(item.get("group") or ""),
                "score": _judgment_score(item),
                "bundle_complete": _bundle_complete(item),
                "query_overlap_count": _query_overlap_count(item),
            }
            for item in items[:10]
        ],
    }


def _intent_risk_flags(item: Mapping[str, object]) -> tuple[str, ...]:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    rerank = _mapping(metadata.get("benchmark_rerank"))
    query_profile = _mapping(
        query_decomposition.get("query_profile") or rerank.get("query_profile")
    )
    query_intent = _mapping(query_decomposition.get("retrieval_intent"))
    rerank_intent = _mapping(rerank.get("retrieval_intent"))
    integrity = _query_integrity(item)
    return tuple(
        dict.fromkeys(
            (
                *_str_tuple(query_profile.get("risk_flags")),
                *_str_tuple(query_intent.get("risk_flags")),
                *_str_tuple(rerank_intent.get("risk_flags")),
                *_str_tuple(integrity.get("retrieval_intent_risk_flags")),
            )
        )
    )


def _bundle_incomplete_diagnostics(
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


def _bundle_gap_breakdown(bundle_incomplete: Mapping[str, object]) -> dict[str, object]:
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


def _query_role_gap_breakdown(
    query_role_effectiveness: Mapping[str, object],
) -> dict[str, object]:
    candidate_role_counts = _count_mapping(
        query_role_effectiveness.get("candidate_role_counts")
    )
    lifted_candidate_role_counts = _count_mapping(
        query_role_effectiveness.get("lifted_candidate_role_counts")
    )
    selected_item_role_counts = _count_mapping(
        query_role_effectiveness.get("selected_item_role_counts")
    )
    candidate_role_family_counts = _count_mapping(
        query_role_effectiveness.get("candidate_role_family_counts")
    )
    lifted_candidate_role_family_counts = _count_mapping(
        query_role_effectiveness.get("lifted_candidate_role_family_counts")
    )
    selected_item_role_family_counts = _count_mapping(
        query_role_effectiveness.get("selected_item_role_family_counts")
    )
    bridge_hit_candidate_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_candidate_counts")
    )
    bridge_hit_selected_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_selected_counts")
    )
    candidate_roles = sorted(
        role for role, count in candidate_role_counts.items() if count > 0
    )
    role_stats = _mapping(query_role_effectiveness.get("role_stats"))
    role_gaps: dict[str, dict[str, object]] = {}

    for role in candidate_roles:
        stats = _mapping(role_stats.get(role))
        candidate_count = candidate_role_counts.get(role, 0)
        lifted_count = lifted_candidate_role_counts.get(role, 0)
        selected_count = selected_item_role_counts.get(role, 0)
        bridge_candidate_count = bridge_hit_candidate_counts.get(role, 0)
        bridge_selected_count = bridge_hit_selected_counts.get(role, 0)
        gap_reasons: list[str] = []
        if selected_count <= 0:
            gap_reasons.append("not_selected")
        if lifted_count <= 0:
            gap_reasons.append("not_lifted")
        if bridge_candidate_count > bridge_selected_count:
            gap_reasons.append("bridge_hit_not_selected")
        if not gap_reasons:
            continue

        role_gaps[role] = {
            "candidate_count": candidate_count,
            "lifted_candidate_count": lifted_count,
            "selected_item_count": selected_count,
            "selection_rate": round(_metric_value(stats, "selection_rate"), 4),
            "lifted_rate": round(_metric_value(stats, "lifted_rate"), 4),
            "bridge_query_hit_candidate_count": bridge_candidate_count,
            "bridge_query_hit_selected_count": bridge_selected_count,
            "avg_candidate_answerability_score": round(
                _metric_value(stats, "avg_candidate_answerability_score"),
                4,
            ),
            "avg_selected_answerability_score": round(
                _metric_value(stats, "avg_selected_answerability_score"),
                4,
            ),
            "selected_bundle_role_counts": _count_mapping(
                stats.get("selected_bundle_role_counts")
            ),
            "gap_reasons": gap_reasons,
        }

    return {
        "schema_version": "query_role_gap_breakdown.v1",
        "role_count": _positive_int(query_role_effectiveness.get("role_count"))
        or len(
            set(candidate_role_counts)
            | set(lifted_candidate_role_counts)
            | set(selected_item_role_counts)
        ),
        "role_family_count": _positive_int(
            query_role_effectiveness.get("role_family_count")
        )
        or len(
            set(candidate_role_family_counts)
            | set(lifted_candidate_role_family_counts)
            | set(selected_item_role_family_counts)
        ),
        "candidate_role_count": len(candidate_roles),
        "role_gap_count": len(role_gaps),
        "candidate_role_counts": candidate_role_counts,
        "lifted_candidate_role_counts": lifted_candidate_role_counts,
        "selected_item_role_counts": selected_item_role_counts,
        "candidate_role_family_counts": candidate_role_family_counts,
        "lifted_candidate_role_family_counts": lifted_candidate_role_family_counts,
        "selected_item_role_family_counts": selected_item_role_family_counts,
        "bridge_query_hit_candidate_counts": bridge_hit_candidate_counts,
        "bridge_query_hit_selected_counts": bridge_hit_selected_counts,
        "roles_without_selected_items": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("roles_without_selected_items")
            )
            if candidate_role_counts.get(role, 0) > 0
        ],
        "roles_without_lifted_candidates": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("roles_without_lifted_candidates")
            )
            if candidate_role_counts.get(role, 0) > 0
        ],
        "bridge_hit_roles_without_selected_items": [
            role
            for role in candidate_roles
            if bridge_hit_candidate_counts.get(role, 0) > 0
            and bridge_hit_selected_counts.get(role, 0) <= 0
        ],
        "role_gaps": role_gaps,
    }


def _query_plan_gap_breakdown(
    query_plan_integrity: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "query_plan_gap_breakdown.v1",
        "plan_count": _positive_int(query_plan_integrity.get("plan_count")) or 0,
        "plan_gap_case_count": (
            _positive_int(query_plan_integrity.get("plan_gap_case_count")) or 0
        ),
        "missing_recommended_role_family_total": (
            _positive_int(
                query_plan_integrity.get(
                    "missing_recommended_role_family_total"
                )
            )
            or 0
        ),
        "dropped_query_count": (
            _positive_int(query_plan_integrity.get("dropped_query_count")) or 0
        ),
        "fanout_limit_hit_count": (
            _positive_int(query_plan_integrity.get("fanout_limit_hit_count")) or 0
        ),
        "type_limit_hit_count": (
            _positive_int(query_plan_integrity.get("type_limit_hit_count")) or 0
        ),
        "empty_query_candidate_count": (
            _positive_int(query_plan_integrity.get("empty_query_candidate_count"))
            or 0
        ),
        "gap_reason_counts": _count_mapping(
            query_plan_integrity.get("gap_reason_counts")
        ),
        "missing_recommended_role_family_counts": _count_mapping(
            query_plan_integrity.get("missing_recommended_role_family_counts")
        ),
        "missing_evidence_role_query_family_total": (
            _positive_int(
                query_plan_integrity.get(
                    "missing_evidence_role_query_family_total"
                )
            )
            or 0
        ),
        "required_evidence_role_counts": _count_mapping(
            query_plan_integrity.get("required_evidence_role_counts")
        ),
        "missing_evidence_role_query_family_counts": _count_mapping(
            query_plan_integrity.get("missing_evidence_role_query_family_counts")
        ),
        "dropped_role_family_counts": _count_mapping(
            query_plan_integrity.get("dropped_role_family_counts")
        ),
        "selected_role_family_counts": _count_mapping(
            query_plan_integrity.get("selected_role_family_counts")
        ),
        "samples": list(_sequence(query_plan_integrity.get("samples")))[:5],
    }


def _bundle_incomplete_reasons(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    quality = _mapping(item.get("retrieval_quality"))
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
    if not any(_metric_value(item, "focused_evidence_score") > 0 for item in _bundle_items(bundle)):
        reasons.append("no_focused_evidence")
    if _needs_contrast_evidence(item) and not _bundle_has_contrast_support(bundle):
        reasons.append("missing_contrast")
    if _needs_causal_support(item) and not _bundle_has_causal_support(bundle):
        reasons.append("missing_causal_support")
    if _needs_event_support(item) and not _bundle_has_event_support(bundle):
        reasons.append("missing_event_support")
    if _needs_inference_support(item) and not _bundle_has_inference_support(bundle):
        reasons.append("missing_inference_support")
    if _needs_location_support(item) and not _bundle_has_location_support(bundle):
        reasons.append("missing_location_support")
    if _needs_emotion_response_support(item) and not _bundle_has_emotion_response_support(bundle):
        reasons.append("missing_emotion_response_support")
    if _needs_symbolic_meaning_support(item) and not _bundle_has_symbolic_meaning_support(bundle):
        reasons.append("missing_symbolic_meaning_support")
    if _needs_preference_support(item) and not _bundle_has_preference_support(bundle):
        reasons.append("missing_preference_support")
    if _needs_visual_support(item) and not _bundle_has_visual_support(bundle):
        reasons.append("missing_visual_support")
    if _needs_temporal_support(item) and not _bundle_has_temporal_support(bundle):
        reasons.append("missing_temporal_support")
    for role in _str_tuple(bundle.get("missing_required_roles")):
        reasons.append(f"missing_required_{role}")
    reasons.extend(_multi_hop_bundle_gap_reasons(item, bundle))
    return tuple(dict.fromkeys(reasons or ("unknown_bundle_gap",)))


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
    if _needs_temporal_bridge(item) and not _bundle_has_temporal_support(bundle):
        reasons.append("missing_temporal_bridge")
    locality_score = _selected_source_locality_score(item)
    if locality_score and locality_score < 0.5:
        reasons.append("weak_source_locality")
    return tuple(reasons)


def _bundle_quality_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    quality_items: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    confidence_scores: list[float] = []
    risk_penalties: list[float] = []
    bridge_counts: list[int] = []
    causal_support_counts: list[int] = []
    event_support_counts: list[int] = []
    inference_support_counts: list[int] = []
    location_support_counts: list[int] = []
    emotion_response_support_counts: list[int] = []
    symbolic_meaning_support_counts: list[int] = []
    preference_support_counts: list[int] = []
    visual_support_counts: list[int] = []
    location_relation_category_hit_counts: list[int] = []
    source_proximity_support_counts: list[int] = []
    contrast_counts: list[int] = []
    selected_source_locality_scores: list[float] = []
    band_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    weak_samples: list[dict[str, object]] = []

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
        event_support_counts.append(
            _positive_int(quality.get("event_support_count")) or 0
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
        contrast_counts.append(_positive_int(quality.get("contrast_count")) or 0)
        if "average_selected_source_locality_score" in planner:
            selected_source_locality_scores.append(
                _metric_value(planner, "average_selected_source_locality_score")
            )
        band = str(quality.get("confidence_band") or "unknown").strip() or "unknown"
        band_counts[band] += 1
        reason_counts.update(_str_tuple(quality.get("reason_codes")))
        if len(weak_samples) < 10 and (
            band in {"none", "low"} or any(
                reason.startswith("risk:")
                for reason in _str_tuple(quality.get("reason_codes"))
            )
        ):
            weak_samples.append(_bundle_quality_sample(item, quality))

    weak_count = sum(
        count for band, count in band_counts.items() if band in {"none", "low"}
    )
    medium_or_high_count = sum(
        count for band, count in band_counts.items() if band in {"medium", "high"}
    )
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
        "avg_event_support_count": _avg(event_support_counts),
        "total_event_support_count": sum(event_support_counts),
        "event_support_bundle_count": sum(
            1 for count in event_support_counts if count > 0
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
        "avg_contrast_count": _avg(contrast_counts),
        "total_contrast_count": sum(contrast_counts),
        "contrast_bundle_count": sum(1 for count in contrast_counts if count > 0),
        "avg_selected_source_locality_score": _avg(selected_source_locality_scores),
        "weak_bundle_count": weak_count,
        "medium_or_high_bundle_count": medium_or_high_count,
        "confidence_band_counts": dict(sorted(band_counts.items())),
        "risk_reason_counts": {
            reason: count
            for reason, count in sorted(reason_counts.items())
            if reason.startswith("risk:")
        },
        "top_reason_counts": _top_counts(reason_counts),
        "weak_samples": weak_samples,
    }


def _bundle_support_counts(bundle_quality: Mapping[str, object]) -> dict[str, int]:
    return {
        "bridge": _positive_int(bundle_quality.get("total_bridge_count")) or 0,
        "causal": (
            _positive_int(bundle_quality.get("total_causal_support_count")) or 0
        ),
        "event": _positive_int(bundle_quality.get("total_event_support_count")) or 0,
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


def _bundle_support_bundle_counts(
    bundle_quality: Mapping[str, object],
) -> dict[str, int]:
    return {
        "bridge": _positive_int(bundle_quality.get("bridge_bundle_count")) or 0,
        "causal": (
            _positive_int(bundle_quality.get("causal_support_bundle_count")) or 0
        ),
        "event": _positive_int(bundle_quality.get("event_support_bundle_count")) or 0,
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
) -> dict[str, object]:
    return {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "confidence_score": round(_metric_value(quality, "confidence_score"), 6),
        "confidence_band": str(quality.get("confidence_band") or "unknown"),
        "risk_penalty": round(_metric_value(quality, "risk_penalty"), 6),
        "reason_codes": _str_tuple(quality.get("reason_codes")),
        "selected_item_count": _positive_int(quality.get("selected_item_count")) or 0,
        "primary_count": _positive_int(quality.get("primary_count")) or 0,
        "supporting_count": _positive_int(quality.get("supporting_count")) or 0,
        "source_ref_item_count": (
            _positive_int(quality.get("source_ref_item_count")) or 0
        ),
        "source_type_diversity": (
            _positive_int(quality.get("source_type_diversity")) or 0
        ),
        "retrieval_source_diversity": (
            _positive_int(quality.get("retrieval_source_diversity")) or 0
        ),
        "low_answerability_count": (
            _positive_int(quality.get("low_answerability_count")) or 0
        ),
        "causal_support_count": (
            _positive_int(quality.get("causal_support_count")) or 0
        ),
        "event_support_count": (
            _positive_int(quality.get("event_support_count")) or 0
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
        "contrast_count": _positive_int(quality.get("contrast_count")) or 0,
        "broad_summary_count": (
            _positive_int(quality.get("broad_summary_count")) or 0
        ),
        "conflict_or_stale_count": (
            _positive_int(quality.get("conflict_or_stale_count")) or 0
        ),
    }


def _policy_contribution_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    totals: dict[str, float] = defaultdict(float)
    active_counts: Counter[str] = Counter()
    reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for memory in _retrieval_results(items):
        policy = _mapping(
            _mapping(_mapping(memory.get("metadata")).get("diagnostics")).get(
                "benchmark_rerank_policy"
            )
        )
        for contribution in _sequence(policy.get("contributions")):
            payload = _mapping(contribution)
            name = str(payload.get("policy") or "unknown")
            score = _metric_value(payload, "score")
            totals[name] += score
            if score != 0:
                active_counts[name] += 1
            reason_counts[name].update(_str_tuple(payload.get("reason_codes")))
    return {
        name: {
            "active_count": active_counts[name],
            "total_score": round(total, 6),
            "avg_active_score": round(total / active_counts[name], 6)
            if active_counts[name]
            else 0.0,
            "reason_counts": dict(sorted(reason_counts[name].items())),
        }
        for name, total in sorted(totals.items())
    }


def _evidence_feature_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    surface_counts: Counter[str] = Counter()
    source_type_counts: Counter[str] = Counter()
    retrieval_source_counts: Counter[str] = Counter()
    query_role_counts: Counter[str] = Counter()
    relation_category_counts: Counter[str] = Counter()
    relation_category_hit_counts: Counter[str] = Counter()
    answerability_reason_counts: Counter[str] = Counter()
    source_locality_reason_counts: Counter[str] = Counter()
    time_intent_kind_counts: Counter[str] = Counter()
    typed_temporal_surface_counts: Counter[str] = Counter()
    answerability_scores: list[float] = []
    source_locality_scores: list[float] = []
    for memory in _retrieval_results(items):
        features = _candidate_features(memory)
        if not features:
            continue
        answerability_scores.append(_metric_value(features, "answerability_score"))
        source_locality_scores.append(_metric_value(features, "source_locality_score"))
        source_type_counts.update(_feature_source_types(features))
        retrieval_source_counts.update(_str_tuple(features.get("retrieval_sources")))
        query_role_counts.update(_str_tuple(features.get("query_roles")))
        time_intent_kind = str(features.get("time_intent_kind") or "").strip()
        if time_intent_kind and time_intent_kind != "none":
            time_intent_kind_counts[time_intent_kind] += 1
        if features.get("bridge_query_hit") is True:
            surface_counts["bridge_query_hit"] += 1
        relation_category_counts.update(_str_tuple(features.get("relation_categories")))
        relation_category_hit_counts.update(
            _str_tuple(features.get("relation_category_hits"))
        )
        answerability_reason_counts.update(
            _str_tuple(features.get("answerability_reason_codes"))
        )
        source_locality_reason_counts.update(
            _str_tuple(features.get("source_locality_reason_codes"))
        )
        for key in (
            "direct_speaker_turn",
            "broad_summary",
            "negation_surface",
            "currentness_surface",
            "stale_surface",
            "contrast_surface",
            "conflict_or_stale",
        ):
            if features.get(key) is True:
                surface_counts[key] += 1
        for key in (
            "has_duration_surface",
            "has_relative_time_surface",
            "has_explicit_time_surface",
            "has_temporal_sequence_surface",
        ):
            if features.get(key) is True:
                typed_temporal_surface_counts[key] += 1
    low_answerability_count = sum(1 for score in answerability_scores if score < 0.55)
    return {
        "candidate_count": len(answerability_scores),
        "avg_answerability_score": _avg(answerability_scores),
        "avg_source_locality_score": _avg(source_locality_scores),
        "low_answerability_count": low_answerability_count,
        "surface_counts": dict(sorted(surface_counts.items())),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "retrieval_source_counts": dict(sorted(retrieval_source_counts.items())),
        "query_role_counts": dict(sorted(query_role_counts.items())),
        "bridge_query_hit_count": surface_counts.get("bridge_query_hit", 0),
        "time_intent_kind_counts": dict(sorted(time_intent_kind_counts.items())),
        "typed_temporal_surface_counts": dict(
            sorted(typed_temporal_surface_counts.items())
        ),
        "relation_category_counts": dict(sorted(relation_category_counts.items())),
        "relation_category_hit_counts": dict(
            sorted(relation_category_hit_counts.items())
        ),
        "answerability_reason_counts": dict(sorted(answerability_reason_counts.items())),
        "source_locality_reason_counts": dict(
            sorted(source_locality_reason_counts.items())
        ),
    }


def _feature_source_types(features: Mapping[str, object]) -> tuple[str, ...]:
    source_types = _str_tuple(features.get("source_types"))
    if source_types:
        return source_types
    source_type = str(features.get("source_type") or "unknown").strip() or "unknown"
    return (source_type,)


def _source_ref_provenance_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    retrieval_candidate_count = 0
    retrieval_source_ref_candidate_count = 0
    retrieval_source_ref_count = 0
    fused_candidate_count = 0
    fused_source_ref_candidate_count = 0
    fused_source_ref_count = 0
    fused_ref_rescue_candidate_count = 0
    fused_ref_added_count = 0
    selected_bundle_item_count = 0
    selected_bundle_source_ref_item_count = 0
    selected_bundle_source_ref_count = 0
    source_refless_selected_samples: list[dict[str, object]] = []

    for item in items:
        for memory in _sequence(_mapping(item.get("retrieval")).get("results")):
            if not isinstance(memory, Mapping):
                continue
            retrieval_candidate_count += 1
            direct_memory_refs = _direct_source_refs_from_memory(memory)
            memory_refs = _source_refs_from_memory(memory)
            if memory_refs:
                retrieval_source_ref_candidate_count += 1
                retrieval_source_ref_count += len(memory_refs)

            fusion_refs = _fusion_source_refs(memory)
            if fusion_refs:
                fused_candidate_count += 1
                fused_source_ref_candidate_count += 1
                fused_source_ref_count += len(fusion_refs)
                added_refs = tuple(
                    ref for ref in fusion_refs if ref not in direct_memory_refs
                )
                if added_refs:
                    fused_ref_rescue_candidate_count += 1
                    fused_ref_added_count += len(added_refs)
            elif _mapping(_memory_diagnostics(memory).get("benchmark_candidate_fusion")):
                fused_candidate_count += 1

        for bundle_item in _bundle_items(_mapping(item.get("evidence_bundle"))):
            selected_bundle_item_count += 1
            source_refs = _source_refs_from_bundle_item(bundle_item)
            if source_refs:
                selected_bundle_source_ref_item_count += 1
                selected_bundle_source_ref_count += len(source_refs)
                continue
            if len(source_refless_selected_samples) < 10:
                source_refless_selected_samples.append(
                    {
                        "case_id": str(item.get("case_id") or ""),
                        "item_id": str(
                            bundle_item.get("id")
                            or bundle_item.get("item_id")
                            or ""
                        ),
                        "role": str(bundle_item.get("role") or ""),
                        "retrieval_order": (
                            _positive_int(bundle_item.get("retrieval_order"))
                            or _positive_int(bundle_item.get("rank"))
                            or 0
                        ),
                    }
                )

    return {
        "schema_version": "source_ref_provenance.v1",
        "retrieval_candidate_count": retrieval_candidate_count,
        "retrieval_source_ref_candidate_count": retrieval_source_ref_candidate_count,
        "retrieval_source_ref_count": retrieval_source_ref_count,
        "retrieval_source_refless_candidate_count": (
            retrieval_candidate_count - retrieval_source_ref_candidate_count
        ),
        "retrieval_source_ref_coverage_rate": _ratio(
            retrieval_source_ref_candidate_count,
            retrieval_candidate_count,
        ),
        "fused_candidate_count": fused_candidate_count,
        "fused_source_ref_candidate_count": fused_source_ref_candidate_count,
        "fused_source_ref_count": fused_source_ref_count,
        "fused_ref_rescue_candidate_count": fused_ref_rescue_candidate_count,
        "fused_ref_added_count": fused_ref_added_count,
        "selected_bundle_item_count": selected_bundle_item_count,
        "selected_bundle_source_ref_item_count": selected_bundle_source_ref_item_count,
        "selected_bundle_source_ref_count": selected_bundle_source_ref_count,
        "selected_bundle_source_refless_item_count": (
            selected_bundle_item_count - selected_bundle_source_ref_item_count
        ),
        "selected_bundle_source_ref_coverage_rate": _ratio(
            selected_bundle_source_ref_item_count,
            selected_bundle_item_count,
        ),
        "source_refless_selected_samples": source_refless_selected_samples,
    }


def _answer_context_provenance_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    context_count = 0
    evidence_bundle_context_count = 0
    source_ref_context_count = 0
    memory_count = 0
    source_ref_count = 0
    source_ref_item_count = 0
    source_refless_item_count = 0
    fallback_context_count = 0
    source_counts: Counter[str] = Counter()
    fallback_reason_counts: Counter[str] = Counter()
    source_refless_context_samples: list[dict[str, object]] = []

    for item in items:
        for cutoff, context in _answer_contexts(item):
            context_count += 1
            source = str(context.get("source") or "unknown").strip() or "unknown"
            source_counts[source] += 1
            if source == "evidence_bundle":
                evidence_bundle_context_count += 1
            else:
                fallback_context_count += 1
            fallback_reason = str(context.get("fallback_reason") or "").strip()
            if fallback_reason:
                fallback_reason_counts[fallback_reason] += 1

            context_memory_count = _positive_int(context.get("memory_count")) or 0
            context_source_ref_count = (
                _positive_int(context.get("source_ref_count")) or 0
            )
            context_source_ref_item_count = (
                _positive_int(context.get("source_ref_item_count")) or 0
            )
            context_source_refless_item_count = (
                _positive_int(context.get("source_refless_item_count")) or 0
            )
            memory_count += context_memory_count
            source_ref_count += context_source_ref_count
            source_ref_item_count += context_source_ref_item_count
            source_refless_item_count += context_source_refless_item_count
            if context_source_ref_count > 0 or context_source_ref_item_count > 0:
                source_ref_context_count += 1
            if context_source_refless_item_count > 0 and len(
                source_refless_context_samples
            ) < 10:
                source_refless_context_samples.append(
                    {
                        "case_id": str(item.get("case_id") or ""),
                        "cutoff": cutoff,
                        "source": source,
                        "memory_count": context_memory_count,
                        "source_refless_item_count": (
                            context_source_refless_item_count
                        ),
                        "fallback_reason": fallback_reason,
                    }
                )

    return {
        "schema_version": "answer_context_provenance.v1",
        "context_count": context_count,
        "evidence_bundle_context_count": evidence_bundle_context_count,
        "fallback_context_count": fallback_context_count,
        "source_ref_context_count": source_ref_context_count,
        "source_refless_context_count": context_count - source_ref_context_count,
        "memory_count": memory_count,
        "source_ref_count": source_ref_count,
        "source_ref_item_count": source_ref_item_count,
        "source_refless_item_count": source_refless_item_count,
        "source_ref_context_rate": _ratio(source_ref_context_count, context_count),
        "source_ref_item_coverage_rate": _ratio(
            source_ref_item_count,
            memory_count,
        ),
        "source_counts": dict(sorted(source_counts.items())),
        "fallback_reason_counts": dict(sorted(fallback_reason_counts.items())),
        "source_refless_context_samples": source_refless_context_samples,
    }


def _answer_contexts(
    item: Mapping[str, object],
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    contexts: list[tuple[str, Mapping[str, object]]] = []
    for cutoff, payload in _mapping(item.get("cutoff_results")).items():
        context = _mapping(_mapping(payload).get("answer_context"))
        if not context:
            continue
        contexts.append((str(cutoff), context))
    return tuple(
        sorted(
            contexts,
            key=lambda pair: (
                _positive_int(pair[0]) or 999999,
                pair[0],
            ),
        )
    )


def _query_plan_integrity_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    plan_count = 0
    plan_gap_case_count = 0
    selected_query_counts: list[int] = []
    dropped_query_count = 0
    fanout_limit_hit_count = 0
    type_limit_hit_count = 0
    empty_query_candidate_count = 0
    max_selected_query_token_count = 0
    missing_recommended_counts: Counter[str] = Counter()
    recommended_counts: Counter[str] = Counter()
    selected_family_counts: Counter[str] = Counter()
    dropped_family_counts: Counter[str] = Counter()
    role_family_counts: Counter[str] = Counter()
    selected_type_counts: Counter[str] = Counter()
    candidate_type_counts: Counter[str] = Counter()
    required_evidence_role_counts: Counter[str] = Counter()
    missing_evidence_role_query_family_counts: Counter[str] = Counter()
    gap_reason_counts: Counter[str] = Counter()
    samples: list[dict[str, object]] = []

    for item in items:
        query_plan = _query_plan(item)
        if not query_plan:
            continue
        plan_count += 1
        selected_query_counts.append(
            _positive_int(query_plan.get("selected_query_count")) or 0
        )
        dropped_count = _positive_int(query_plan.get("dropped_query_count")) or 0
        dropped_query_count += dropped_count

        recommended_counts.update(
            _str_tuple(query_plan.get("recommended_role_families"))
        )
        required_evidence_roles = _required_evidence_roles(item)
        required_evidence_role_counts.update(required_evidence_roles)
        missing_recommended = _str_tuple(
            query_plan.get("missing_recommended_role_families")
        )
        missing_recommended_counts.update(missing_recommended)
        role_family_counts.update(_count_mapping(query_plan.get("role_family_counts")))
        selected_family_counts.update(
            _count_mapping(query_plan.get("selected_role_family_counts"))
        )
        dropped_family_counts.update(
            _count_mapping(query_plan.get("dropped_role_family_counts"))
        )
        selected_type_counts.update(
            _count_mapping(query_plan.get("selected_type_counts"))
        )
        candidate_type_counts.update(
            _count_mapping(query_plan.get("candidate_type_counts"))
        )
        selected_role_families = _str_tuple(query_plan.get("selected_role_families"))
        missing_evidence_role_query_families = (
            _missing_evidence_role_query_families(
                required_evidence_roles,
                selected_role_families=selected_role_families,
            )
        )
        missing_evidence_role_query_family_counts.update(
            missing_evidence_role_query_families
        )

        fanout = _mapping(query_plan.get("fanout_integrity"))
        empty_count = (
            _positive_int(fanout.get("empty_query_candidate_count"))
            or _positive_int(query_plan.get("empty_query_candidate_count"))
            or 0
        )
        empty_query_candidate_count += empty_count
        token_count = _positive_int(fanout.get("max_selected_query_token_count")) or 0
        max_selected_query_token_count = max(max_selected_query_token_count, token_count)

        gap_reasons: list[str] = []
        if missing_recommended:
            gap_reasons.append("missing_recommended_role_family")
        if missing_evidence_role_query_families:
            gap_reasons.append("missing_evidence_role_query_family")
        if dropped_count:
            gap_reasons.append("dropped_queries")
        if fanout.get("fanout_limit_hit") is True:
            fanout_limit_hit_count += 1
            gap_reasons.append("fanout_limit_hit")
        if fanout.get("type_limit_hit") is True:
            type_limit_hit_count += 1
            gap_reasons.append("type_limit_hit")
        if empty_count:
            gap_reasons.append("empty_query_candidate")
        gap_reason_counts.update(gap_reasons)
        if gap_reasons:
            plan_gap_case_count += 1
            if len(samples) < 10:
                samples.append(
                    _query_plan_gap_sample(
                        item,
                        query_plan,
                        missing_recommended=missing_recommended,
                        required_evidence_roles=required_evidence_roles,
                        missing_evidence_role_query_families=(
                            missing_evidence_role_query_families
                        ),
                        gap_reasons=tuple(gap_reasons),
                        fanout=fanout,
                    )
                )

    return {
        "schema_version": "query_plan_integrity.v1",
        "plan_count": plan_count,
        "plan_gap_case_count": plan_gap_case_count,
        "avg_selected_query_count": _avg(selected_query_counts),
        "dropped_query_count": dropped_query_count,
        "fanout_limit_hit_count": fanout_limit_hit_count,
        "type_limit_hit_count": type_limit_hit_count,
        "empty_query_candidate_count": empty_query_candidate_count,
        "max_selected_query_token_count": max_selected_query_token_count,
        "missing_recommended_role_family_total": sum(
            missing_recommended_counts.values()
        ),
        "recommended_role_family_counts": _top_counts(recommended_counts),
        "missing_recommended_role_family_counts": _top_counts(
            missing_recommended_counts
        ),
        "required_evidence_role_counts": _top_counts(required_evidence_role_counts),
        "missing_evidence_role_query_family_total": sum(
            missing_evidence_role_query_family_counts.values()
        ),
        "missing_evidence_role_query_family_counts": _top_counts(
            missing_evidence_role_query_family_counts
        ),
        "role_family_counts": _top_counts(role_family_counts),
        "selected_role_family_counts": _top_counts(selected_family_counts),
        "dropped_role_family_counts": _top_counts(dropped_family_counts),
        "selected_type_counts": _top_counts(selected_type_counts),
        "candidate_type_counts": _top_counts(candidate_type_counts),
        "gap_reason_counts": _top_counts(gap_reason_counts),
        "samples": samples,
    }


def _query_plan_gap_sample(
    item: Mapping[str, object],
    query_plan: Mapping[str, object],
    *,
    missing_recommended: Sequence[str],
    required_evidence_roles: Sequence[str],
    missing_evidence_role_query_families: Sequence[str],
    gap_reasons: Sequence[str],
    fanout: Mapping[str, object],
) -> dict[str, object]:
    return {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "gap_reasons": list(gap_reasons),
        "selected_query_count": _positive_int(
            query_plan.get("selected_query_count")
        )
        or 0,
        "dropped_query_count": _positive_int(query_plan.get("dropped_query_count"))
        or 0,
        "selected_roles": _str_tuple(query_plan.get("selected_roles")),
        "dropped_roles": _str_tuple(query_plan.get("dropped_roles")),
        "dropped_type_limit_roles": _str_tuple(
            query_plan.get("dropped_type_limit_roles")
        ),
        "recommended_role_families": _str_tuple(
            query_plan.get("recommended_role_families")
        ),
        "selected_role_families": _str_tuple(
            query_plan.get("selected_role_families")
        ),
        "missing_recommended_role_families": tuple(missing_recommended),
        "required_evidence_roles": tuple(required_evidence_roles),
        "missing_evidence_role_query_families": tuple(
            missing_evidence_role_query_families
        ),
        "selected_type_counts": _count_mapping(query_plan.get("selected_type_counts")),
        "candidate_type_counts": _count_mapping(
            query_plan.get("candidate_type_counts")
        ),
        "fanout_limit_hit": fanout.get("fanout_limit_hit") is True,
        "type_limit_hit": fanout.get("type_limit_hit") is True,
        "empty_query_candidate_count": (
            _positive_int(fanout.get("empty_query_candidate_count")) or 0
        ),
        "max_selected_query_token_count": (
            _positive_int(fanout.get("max_selected_query_token_count")) or 0
        ),
    }


def _required_evidence_roles(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    roles = _str_tuple(bundle.get("required_roles"))
    if roles:
        return roles
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    roles = _str_tuple(query_profile.get("bundle_evidence_roles"))
    if roles:
        return roles
    return _str_tuple(intent.get("bundle_evidence_roles"))


def _missing_evidence_role_query_families(
    required_evidence_roles: Sequence[str],
    *,
    selected_role_families: Sequence[str],
) -> tuple[str, ...]:
    selected = set(selected_role_families)
    missing: list[str] = []
    for role in required_evidence_roles:
        role_key = str(role).strip()
        if not role_key:
            continue
        acceptable_families = _evidence_role_query_families(role_key)
        if acceptable_families and selected.intersection(acceptable_families):
            continue
        if not acceptable_families and selected:
            continue
        missing.append(role_key)
    return tuple(dict.fromkeys(missing))


def _evidence_role_query_families(role: str) -> tuple[str, ...]:
    return {
        "primary": ("base_query", "expanded_focus", "relation_compact"),
        "supporting": ("base_query", "expanded_focus", "relation_compact"),
        "bridge": ("multi_hop", "relation_compact", "expanded_focus"),
        "temporal_support": ("temporal_support", "expanded_focus"),
        "location_support": (
            "location_support",
            "relation_compact",
            "expanded_focus",
        ),
        "causal_support": ("multi_hop", "relation_compact", "expanded_focus"),
        "event_support": ("relation_compact", "expanded_focus"),
        "emotion_response_support": ("relation_compact", "expanded_focus"),
        "symbolic_meaning_support": ("relation_compact", "expanded_focus"),
        "inference_support": ("relation_compact", "expanded_focus", "base_query"),
        "preference_support": ("relation_compact", "expanded_focus", "base_query"),
        "visual_support": ("visual_support", "expanded_focus", "relation_compact"),
        "contrast": ("contrast_support", "relation_compact", "expanded_focus"),
        "entity_disambiguation": (
            "base_query",
            "expanded_focus",
            "relation_compact",
        ),
    }.get(role, ())


def _query_role_effectiveness_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    candidate_role_counts: Counter[str] = Counter()
    lifted_candidate_role_counts: Counter[str] = Counter()
    selected_item_role_counts: Counter[str] = Counter()
    candidate_role_family_counts: Counter[str] = Counter()
    lifted_candidate_role_family_counts: Counter[str] = Counter()
    selected_item_role_family_counts: Counter[str] = Counter()
    bridge_query_hit_candidate_counts: Counter[str] = Counter()
    bridge_query_hit_selected_counts: Counter[str] = Counter()
    selected_bundle_role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_answerability_scores: dict[str, list[float]] = defaultdict(list)
    selected_answerability_scores: dict[str, list[float]] = defaultdict(list)

    for item in items:
        for memory in _sequence(_mapping(item.get("retrieval")).get("results")):
            if not isinstance(memory, Mapping):
                continue
            features = _candidate_features(memory)
            query_roles = _str_tuple(features.get("query_roles"))
            if not query_roles:
                continue
            diagnostics = _memory_diagnostics(memory)
            lifted = _candidate_lifted(diagnostics)
            bridge_query_hit = features.get("bridge_query_hit") is True
            answerability_score = _metric_value(features, "answerability_score")
            for query_role in query_roles:
                query_role_family = _query_role_family(query_role)
                candidate_role_counts[query_role] += 1
                candidate_role_family_counts[query_role_family] += 1
                candidate_answerability_scores[query_role].append(answerability_score)
                if lifted:
                    lifted_candidate_role_counts[query_role] += 1
                    lifted_candidate_role_family_counts[query_role_family] += 1
                if bridge_query_hit:
                    bridge_query_hit_candidate_counts[query_role] += 1

        bundle = _mapping(item.get("evidence_bundle"))
        for bundle_item in _bundle_items(bundle):
            query_roles = _str_tuple(bundle_item.get("query_roles"))
            if not query_roles:
                continue
            bundle_role = str(bundle_item.get("role") or "unknown").strip() or "unknown"
            bridge_query_hit = bundle_item.get("bridge_query_hit") is True
            has_answerability_score = "answerability_score" in bundle_item
            answerability_score = _metric_value(bundle_item, "answerability_score")
            for query_role in query_roles:
                query_role_family = _query_role_family(query_role)
                selected_item_role_counts[query_role] += 1
                selected_item_role_family_counts[query_role_family] += 1
                selected_bundle_role_counts[query_role][bundle_role] += 1
                if has_answerability_score:
                    selected_answerability_scores[query_role].append(answerability_score)
                if bridge_query_hit:
                    bridge_query_hit_selected_counts[query_role] += 1

    query_roles = sorted(
        set(candidate_role_counts)
        | set(selected_item_role_counts)
        | set(lifted_candidate_role_counts)
    )
    role_stats = {
        query_role: _query_role_stat_payload(
            query_role,
            candidate_role_counts=candidate_role_counts,
            lifted_candidate_role_counts=lifted_candidate_role_counts,
            selected_item_role_counts=selected_item_role_counts,
            bridge_query_hit_candidate_counts=bridge_query_hit_candidate_counts,
            bridge_query_hit_selected_counts=bridge_query_hit_selected_counts,
            selected_bundle_role_counts=selected_bundle_role_counts,
            candidate_answerability_scores=candidate_answerability_scores,
            selected_answerability_scores=selected_answerability_scores,
        )
        for query_role in query_roles
    }
    return {
        "schema_version": "query_role_effectiveness.v1",
        "role_count": len(query_roles),
        "role_family_count": len(
            set(candidate_role_family_counts)
            | set(lifted_candidate_role_family_counts)
            | set(selected_item_role_family_counts)
        ),
        "candidate_role_counts": dict(sorted(candidate_role_counts.items())),
        "lifted_candidate_role_counts": dict(
            sorted(lifted_candidate_role_counts.items())
        ),
        "selected_item_role_counts": dict(sorted(selected_item_role_counts.items())),
        "candidate_role_family_counts": dict(
            sorted(candidate_role_family_counts.items())
        ),
        "lifted_candidate_role_family_counts": dict(
            sorted(lifted_candidate_role_family_counts.items())
        ),
        "selected_item_role_family_counts": dict(
            sorted(selected_item_role_family_counts.items())
        ),
        "bridge_query_hit_candidate_counts": dict(
            sorted(bridge_query_hit_candidate_counts.items())
        ),
        "bridge_query_hit_selected_counts": dict(
            sorted(bridge_query_hit_selected_counts.items())
        ),
        "roles_without_selected_items": [
            query_role for query_role in query_roles if not selected_item_role_counts[query_role]
        ],
        "roles_without_lifted_candidates": [
            query_role
            for query_role in query_roles
            if not lifted_candidate_role_counts[query_role]
        ],
        "role_stats": role_stats,
    }


def _query_role_family(query_role: str) -> str:
    role = str(query_role or "").strip()
    if (
        role == "temporal_support"
        or role == "visual_temporal_support"
        or role.endswith("_temporal_support")
        or role == "temporal_sequence_support"
    ):
        return "temporal_support"
    if role.startswith("multi_hop_"):
        return "multi_hop"
    if role in {"original_question", "expanded_focus", "compact_relation"}:
        return "base_query"
    if role == "contrast_support":
        return "contrast_support"
    return role or "unknown"


def _query_role_stat_payload(
    query_role: str,
    *,
    candidate_role_counts: Counter[str],
    lifted_candidate_role_counts: Counter[str],
    selected_item_role_counts: Counter[str],
    bridge_query_hit_candidate_counts: Counter[str],
    bridge_query_hit_selected_counts: Counter[str],
    selected_bundle_role_counts: Mapping[str, Counter[str]],
    candidate_answerability_scores: Mapping[str, Sequence[float]],
    selected_answerability_scores: Mapping[str, Sequence[float]],
) -> dict[str, object]:
    candidate_count = candidate_role_counts[query_role]
    lifted_count = lifted_candidate_role_counts[query_role]
    selected_count = selected_item_role_counts[query_role]
    return {
        "candidate_count": candidate_count,
        "lifted_candidate_count": lifted_count,
        "selected_item_count": selected_count,
        "selection_rate": _ratio(selected_count, candidate_count),
        "lifted_rate": _ratio(lifted_count, candidate_count),
        "bridge_query_hit_candidate_count": bridge_query_hit_candidate_counts[
            query_role
        ],
        "bridge_query_hit_selected_count": bridge_query_hit_selected_counts[query_role],
        "avg_candidate_answerability_score": _avg(
            candidate_answerability_scores.get(query_role, ())
        ),
        "avg_selected_answerability_score": _avg(
            selected_answerability_scores.get(query_role, ())
        ),
        "selected_bundle_role_counts": dict(
            sorted(selected_bundle_role_counts.get(query_role, Counter()).items())
        ),
    }


def _rerank_lift_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    boosted_count = 0
    positive_policy_scores: list[float] = []
    signal_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    safety_reason_counts: Counter[str] = Counter()
    relation_category_hit_counts: Counter[str] = Counter()
    low_answerability_lift_count = 0
    broad_summary_lift_count = 0
    conflict_or_stale_lift_count = 0
    direct_speaker_lift_count = 0
    provenance_safety_cap_count = 0
    samples: list[dict[str, object]] = []

    for item in items:
        for memory in _sequence(_mapping(item.get("retrieval")).get("results")):
            if not isinstance(memory, Mapping):
                continue
            diagnostics = _memory_diagnostics(memory)
            features = _candidate_features(memory)
            score_signals = _mapping(diagnostics.get("score_signals"))
            positive_policy_score = _positive_policy_score(diagnostics)
            signal_names = _positive_signal_names(score_signals)
            lifted = _candidate_lifted(diagnostics)
            if not lifted:
                continue

            boosted_count += 1
            positive_policy_scores.append(positive_policy_score)
            signal_counts.update(signal_names)
            relation_category_hit_counts.update(
                _str_tuple(features.get("relation_category_hits"))
            )

            policy_reasons = _active_policy_reasons(diagnostics)
            policy_counts.update(policy_reasons.keys())
            for reasons in policy_reasons.values():
                reason_counts.update(reasons)

            answerability_score = _metric_value(features, "answerability_score")
            if answerability_score < 0.55:
                low_answerability_lift_count += 1
            if features.get("broad_summary") is True:
                broad_summary_lift_count += 1
            if features.get("conflict_or_stale") is True:
                conflict_or_stale_lift_count += 1
            if features.get("direct_speaker_turn") is True:
                direct_speaker_lift_count += 1
            safety_reason_codes = _str_tuple(
                score_signals.get("benchmark_provenance_safety_reason_codes")
            )
            if score_signals.get("benchmark_provenance_safety_cap_applied") is True:
                provenance_safety_cap_count += 1
                safety_reason_counts.update(safety_reason_codes)

            if len(samples) < 10:
                samples.append(
                    _rerank_lift_sample(
                        item,
                        memory,
                        features=features,
                        score_signals=score_signals,
                        positive_policy_score=positive_policy_score,
                        policy_reasons=policy_reasons,
                    )
                )

    return {
        "boosted_candidate_count": boosted_count,
        "avg_positive_policy_score": _avg(positive_policy_scores),
        "top_signal_counts": _top_counts(signal_counts),
        "top_policy_counts": _top_counts(policy_counts),
        "top_policy_reason_counts": _top_counts(reason_counts),
        "relation_category_hit_counts": _top_counts(relation_category_hit_counts),
        "low_answerability_lift_count": low_answerability_lift_count,
        "broad_summary_lift_count": broad_summary_lift_count,
        "conflict_or_stale_lift_count": conflict_or_stale_lift_count,
        "direct_speaker_lift_count": direct_speaker_lift_count,
        "provenance_safety_cap_count": provenance_safety_cap_count,
        "provenance_safety_reason_counts": _top_counts(safety_reason_counts),
        "samples": samples,
    }


def _rerank_lift_sample(
    item: Mapping[str, object],
    memory: Mapping[str, object],
    *,
    features: Mapping[str, object],
    score_signals: Mapping[str, object],
    positive_policy_score: float,
    policy_reasons: Mapping[str, tuple[str, ...]],
) -> dict[str, object]:
    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": _memory_id(memory),
        "rank": _positive_int(memory.get("rank")) or 0,
        "score": round(_metric_value(memory, "score"), 6),
        "positive_policy_score": round(positive_policy_score, 6),
        "policy_reasons": {
            policy: list(reasons) for policy, reasons in sorted(policy_reasons.items())
        },
        "top_signals": _top_signal_values(score_signals),
        "relation_category_hits": _str_tuple(features.get("relation_category_hits")),
        "answerability_score": round(
            _metric_value(features, "answerability_score"),
            6,
        ),
        "source_type": str(features.get("source_type") or "unknown"),
        "direct_speaker_turn": features.get("direct_speaker_turn") is True,
        "broad_summary": features.get("broad_summary") is True,
        "conflict_or_stale": features.get("conflict_or_stale") is True,
    }
    safety_reason_codes = _str_tuple(
        score_signals.get("benchmark_provenance_safety_reason_codes")
    )
    if score_signals.get("benchmark_provenance_safety_cap_applied") is True:
        sample["provenance_safety_cap_applied"] = True
        sample["provenance_safety_reason_codes"] = safety_reason_codes
        sample["effective_boost_cap"] = round(
            _metric_value(score_signals, "benchmark_effective_boost_cap"),
            6,
        )
        sample["uncapped_boost_cap"] = round(
            _metric_value(score_signals, "benchmark_uncapped_boost_cap"),
            6,
        )
    query_roles = _str_tuple(features.get("query_roles"))
    if query_roles:
        sample["query_roles"] = query_roles
    if features.get("bridge_query_hit") is True:
        sample["bridge_query_hit"] = True
    return sample


def _candidate_lifted(diagnostics: Mapping[str, object]) -> bool:
    score_signals = _mapping(diagnostics.get("score_signals"))
    return (
        diagnostics.get("benchmark_rerank_boosted") is True
        or _positive_policy_score(diagnostics) > 0
        or bool(_positive_signal_names(score_signals))
    )


def _false_positive_categories(
    items: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        if item.get("scored") is not True:
            continue
        if _judgment_score(item) >= 1.0 and _expected_recall(item) >= 1.0:
            continue
        counts.update(_failure_categories(item))
    return dict(sorted(counts.items()))


def _failure_categories(item: Mapping[str, object]) -> tuple[str, ...]:
    categories: list[str] = []
    if _expected_recall(item) < 1.0:
        categories.append("expected_terms_missing")
    if _evidence_recall(item) < 1.0 and _has_evidence_recall(item):
        categories.append("evidence_refs_missing")
    if not _bundle_complete(item):
        categories.append("bundle_incomplete")
    if _query_overlap_count(item) > 0:
        categories.append("query_leakage_risk")
    if _only_broad_bundle_evidence(item):
        categories.append("only_broad_bundle_evidence")
    if not _policy_contribution_table((item,)):
        categories.append("no_policy_diagnostics")
    return tuple(dict.fromkeys(categories or ("judge_failed_despite_retrieval",)))


def _query_leakage_report(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    query_overlap = []
    profile_overlap = []
    for item in items:
        integrity = _query_integrity(item)
        query_count = _positive_int(
            integrity.get("expected_answer_query_overlap_count")
        ) or 0
        profile_count = _positive_int(
            integrity.get("expected_answer_query_profile_overlap_count")
        ) or 0
        if query_count:
            query_overlap.append((item, query_count))
        if profile_count:
            profile_overlap.append((item, profile_count))
    return {
        "query_overlap_case_count": len(query_overlap),
        "profile_overlap_case_count": len(profile_overlap),
        "clean": not query_overlap and not profile_overlap,
        "query_overlap_samples": _overlap_samples(query_overlap),
        "profile_overlap_samples": _overlap_samples(profile_overlap),
    }


def _leakage_counts(items: Sequence[Mapping[str, object]]) -> tuple[int, int]:
    query_overlap_count = 0
    profile_overlap_count = 0
    for item in items:
        integrity = _query_integrity(item)
        query_overlap_count += (
            _positive_int(integrity.get("expected_answer_query_overlap_count")) or 0
        )
        profile_overlap_count += (
            _positive_int(
                integrity.get("expected_answer_query_profile_overlap_count")
            )
            or 0
        )
    return query_overlap_count, profile_overlap_count


def _min_gate(actual: int, target: int) -> dict[str, object]:
    return {
        "passed": actual >= target,
        "actual": actual,
        "target": target,
        "mode": "min",
    }


def _zero_gate(actual: int) -> dict[str, object]:
    return {
        "passed": actual == 0,
        "actual": actual,
        "target": 0,
        "mode": "zero",
    }


def _overlap_samples(
    ranked: Sequence[tuple[Mapping[str, object], int]],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for item, count in sorted(ranked, key=lambda pair: pair[1], reverse=True)[:10]:
        integrity = _query_integrity(item)
        samples.append(
            {
                "case_id": str(item.get("case_id") or ""),
                "overlap_count": count,
                "query_terms": _str_tuple(
                    integrity.get("expected_answer_query_overlap_terms")
                ),
                "profile_terms": _str_tuple(
                    integrity.get("expected_answer_query_profile_overlap_terms")
                ),
            }
        )
    return samples


def _evidence_ref_failure_sample(
    item: Mapping[str, object],
    required_refs: Sequence[str],
    ref_positions: Mapping[str, int],
) -> dict[str, object]:
    return {
        "case_id": str(item.get("case_id") or ""),
        "required_refs": list(required_refs),
        "found_refs": sorted(ref_positions),
        "missing_refs": [ref for ref in required_refs if ref not in ref_positions],
        "ref_positions": dict(ref_positions),
    }


def _required_evidence_refs(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    quality = _mapping(item.get("retrieval_quality"))
    return tuple(
        dict.fromkeys(
            (
                *_str_tuple(bundle.get("covered_evidence_terms")),
                *_str_tuple(quality.get("missing_evidence_terms")),
            )
        )
    )


def _bundle_evidence_ref_positions(
    bundle: Mapping[str, object],
) -> tuple[dict[str, int], dict[str, int]]:
    positions: dict[str, int] = {}
    focused_positions: dict[str, int] = {}
    for item in _bundle_items(bundle):
        retrieval_order = (
            _positive_int(item.get("retrieval_order"))
            or _positive_int(item.get("rank"))
            or 9999
        )
        focused = _metric_value(item, "focused_evidence_score") > 0
        for ref in _str_tuple(item.get("covered_evidence_terms")):
            positions[ref] = min(positions.get(ref, retrieval_order), retrieval_order)
            if focused:
                focused_positions[ref] = min(
                    focused_positions.get(ref, retrieval_order),
                    retrieval_order,
                )
    return positions, focused_positions


def _retrieval_results(
    items: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        result
        for item in items
        for result in _sequence(_mapping(item.get("retrieval")).get("results"))
        if isinstance(result, Mapping)
    )


def _candidate_features(memory: Mapping[str, object]) -> Mapping[str, object]:
    diagnostics = _memory_diagnostics(memory)
    return _mapping(diagnostics.get("benchmark_candidate_features"))


def _source_refs_from_memory(memory: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *_direct_source_refs_from_memory(memory),
                *_fusion_source_refs(memory),
            )
        )
    )


def _direct_source_refs_from_memory(memory: Mapping[str, object]) -> tuple[str, ...]:
    return _str_tuple(memory.get("source_refs"))


def _fusion_source_refs(memory: Mapping[str, object]) -> tuple[str, ...]:
    fusion = _mapping(_memory_diagnostics(memory).get("benchmark_candidate_fusion"))
    return _str_tuple(fusion.get("source_refs"))


def _source_refs_from_bundle_item(item: Mapping[str, object]) -> tuple[str, ...]:
    return _str_tuple(item.get("source_refs"))


def _memory_diagnostics(memory: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_mapping(memory.get("metadata")).get("diagnostics"))


def _positive_policy_score(diagnostics: Mapping[str, object]) -> float:
    policy = _mapping(diagnostics.get("benchmark_rerank_policy"))
    total = 0.0
    for contribution in _sequence(policy.get("contributions")):
        score = _metric_value(_mapping(contribution), "score")
        if score > 0:
            total += score
    return round(total, 6)


def _active_policy_reasons(
    diagnostics: Mapping[str, object],
) -> dict[str, tuple[str, ...]]:
    policy_reasons: dict[str, tuple[str, ...]] = {}
    policy = _mapping(diagnostics.get("benchmark_rerank_policy"))
    for contribution in _sequence(policy.get("contributions")):
        payload = _mapping(contribution)
        score = _metric_value(payload, "score")
        reasons = _str_tuple(payload.get("reason_codes"))
        if score <= 0 and not reasons:
            continue
        name = str(payload.get("policy") or "unknown")
        policy_reasons[name] = reasons
    return policy_reasons


def _positive_signal_names(score_signals: Mapping[str, object]) -> tuple[str, ...]:
    names: list[str] = []
    for name, value in score_signals.items():
        if isinstance(value, bool):
            if value:
                names.append(str(name))
            continue
        if _metric_value(score_signals, str(name)) > 0:
            names.append(str(name))
    return tuple(names)


def _top_signal_values(score_signals: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    for name in _positive_signal_names(score_signals):
        value = score_signals.get(name)
        if isinstance(value, bool):
            values[name] = value
        else:
            values[name] = round(_metric_value(score_signals, name), 6)
    return dict(sorted(values.items(), key=lambda pair: str(pair[0]))[:8])


def _memory_id(memory: Mapping[str, object]) -> str:
    return str(memory.get("id") or memory.get("item_id") or "")


def _is_multi_hop_item(item: Mapping[str, object]) -> bool:
    if str(item.get("group") or "").replace("_", "-") == "multi-hop":
        return True
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    evidence_need = _str_tuple(query_profile.get("evidence_need"))
    return any(need in {"multi_hop", "multi-hop", "inference_support"} for need in evidence_need)


def _needs_temporal_bridge(item: Mapping[str, object]) -> bool:
    return _needs_temporal_support(item)


def _needs_temporal_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    return bool(
        {"temporal_support", "temporal_sequence"}.intersection(evidence_need)
        or "temporal" in relation_categories
    )


def _needs_contrast_evidence(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    return bool("contrast" in evidence_need or "contrast" in relation_categories)


def _needs_causal_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    if not relation_categories:
        relation_categories = tuple(
            str(relation.get("category") or "").strip()
            for relation in _sequence(
                _mapping(_mapping(intent.get("relations")).get("intents"))
            )
            if isinstance(relation, Mapping)
            and str(relation.get("category") or "").strip()
        )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    return bool(
        "causal_support" in evidence_need
        or "causal_support" in roles
        or "causal" in relation_categories
    )


def _needs_location_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    if not relation_categories:
        relation_categories = tuple(
            str(relation.get("category") or "").strip()
            for relation in _sequence(
                _mapping(_mapping(intent.get("relations")).get("intents"))
            )
            if isinstance(relation, Mapping)
            and str(relation.get("category") or "").strip()
        )
    return bool(
        "location_support" in evidence_need
        or "location_transition" in relation_categories
    )


def _needs_inference_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    return bool("inference_support" in evidence_need or "inference_support" in roles)


def _needs_preference_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    return bool(
        "preference" in evidence_need
        or "preference_support" in roles
        or "preference" in relation_categories
    )


def _needs_emotion_response_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    if not relation_categories:
        relation_categories = tuple(
            str(relation.get("category") or "").strip()
            for relation in _sequence(
                _mapping(_mapping(intent.get("relations")).get("intents"))
            )
            if isinstance(relation, Mapping)
            and str(relation.get("category") or "").strip()
        )
    return bool(
        "emotion_response" in evidence_need
        or "emotion_response_support" in roles
        or "emotion_response" in relation_categories
    )


def _needs_event_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    event_categories = {"participation_event", "registration_event"}
    return bool(
        event_categories & set(evidence_need)
        or "event_support" in roles
        or event_categories & set(relation_categories)
    )


def _needs_symbolic_meaning_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    return bool(
        "symbolic_meaning" in evidence_need
        or "symbolic_meaning_support" in roles
        or "symbolic_meaning" in relation_categories
    )


def _needs_visual_support(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    query_profile = _mapping(query_decomposition.get("query_profile"))
    intent = _mapping(query_decomposition.get("retrieval_intent"))
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _str_tuple(query_profile.get("relation_categories"))
    visual_terms = _str_tuple(query_profile.get("visual_terms"))
    return bool(
        "visual_evidence" in evidence_need
        or "visual_support" in roles
        or "visual" in relation_categories
        or visual_terms
    )


def _bundle_roles(bundle: Mapping[str, object]) -> set[str]:
    roles = {
        str(item.get("role") or "").strip()
        for item in _bundle_items(bundle)
        if str(item.get("role") or "").strip()
    }
    planner = _mapping(bundle.get("bundle_planner"))
    role_counts = _mapping(planner.get("role_counts"))
    roles.update(str(role).strip() for role in role_counts if str(role).strip())
    return roles


def _bundle_has_planner_reason(bundle: Mapping[str, object], reason: str) -> bool:
    return any(
        reason in _str_tuple(item.get("planner_reason_codes"))
        for item in _bundle_items(bundle)
    )


def _bundle_has_temporal_support(bundle: Mapping[str, object]) -> bool:
    if "temporal_support" in _bundle_roles(bundle):
        return True
    return any(
        bool(
            item.get("has_temporal_surface")
            or item.get("has_sequence_surface")
            or item.get("currentness_surface")
            or "temporal_surface" in _str_tuple(item.get("planner_reason_codes"))
            or "sequence_surface" in _str_tuple(item.get("planner_reason_codes"))
            or "currentness_surface" in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_contrast_support(bundle: Mapping[str, object]) -> bool:
    if "contrast" in _bundle_roles(bundle):
        return True
    return any(
        bool(
            item.get("contrast_surface")
            or item.get("stale_surface")
            or item.get("negation_surface")
            or "contrast_surface" in _str_tuple(item.get("planner_reason_codes"))
            or "stale_surface" in _str_tuple(item.get("planner_reason_codes"))
            or "negation_surface" in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_causal_support(bundle: Mapping[str, object]) -> bool:
    if "causal_support" in _bundle_roles(bundle):
        return True
    return any(
        bool(
            "causal_support" in _str_tuple(item.get("planner_reason_codes"))
            or "causal_relation_hits" in _str_tuple(item.get("planner_reason_codes"))
            or "causal_relation_category_hits"
            in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_location_support(bundle: Mapping[str, object]) -> bool:
    if "location_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "location_support"):
        return True
    return any(
        bool(
            "location_transition" in _str_tuple(item.get("relation_category_hits"))
            or "location_relation_category_hits"
            in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_preference_support(bundle: Mapping[str, object]) -> bool:
    if "preference_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "preference_support"):
        return True
    return any(
        bool(
            item.get("has_preference_evidence") is True
            or "preference" in _str_tuple(item.get("relation_category_hits"))
            or "preference_evidence" in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_emotion_response_support(bundle: Mapping[str, object]) -> bool:
    if "emotion_response_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "emotion_response_support"):
        return True
    return any(
        bool(
            "emotion_response" in _str_tuple(item.get("relation_category_hits"))
            or "emotion_response_relation_category_hits"
            in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_event_support(bundle: Mapping[str, object]) -> bool:
    if "event_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "event_support"):
        return True
    return any(
        bool(
            {"registration_event", "participation_event"}
            & set(_str_tuple(item.get("relation_category_hits")))
            or "event_relation_category_hits"
            in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_symbolic_meaning_support(bundle: Mapping[str, object]) -> bool:
    if "symbolic_meaning_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "symbolic_meaning_support"):
        return True
    return any(
        bool(
            "symbolic_meaning" in _str_tuple(item.get("relation_category_hits"))
            or "symbolic_meaning_relation_category_hits"
            in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_visual_support(bundle: Mapping[str, object]) -> bool:
    if "visual_support" in _bundle_roles(bundle):
        return True
    if _bundle_has_planner_reason(bundle, "visual_support"):
        return True
    return any(
        bool(
            item.get("has_visual_evidence") is True
            or "visual" in _str_tuple(item.get("relation_category_hits"))
            or "visual_evidence" in _str_tuple(item.get("planner_reason_codes"))
        )
        for item in _bundle_items(bundle)
    )


def _bundle_has_inference_support(bundle: Mapping[str, object]) -> bool:
    if "inference_support" in _bundle_roles(bundle):
        return True
    return any(
        bool(
            "inference_support" in _str_tuple(item.get("planner_reason_codes"))
            or (
                "inference_entity_hits" in _str_tuple(item.get("planner_reason_codes"))
                and "inference_relation_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def _selected_source_locality_score(item: Mapping[str, object]) -> float:
    planner = _bundle_planner(item)
    if "average_selected_source_locality_score" in planner:
        return _metric_value(planner, "average_selected_source_locality_score")
    bundle_items = _bundle_items(_mapping(item.get("evidence_bundle")))
    locality_scores = [
        _metric_value(bundle_item, "source_locality_score")
        for bundle_item in bundle_items
        if "source_locality_score" in bundle_item
    ]
    return _avg(locality_scores)


def _bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in _sequence(bundle.get("items")) if isinstance(item, Mapping))


def _bundle_quality(item: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_bundle_planner(item).get("bundle_quality"))


def _bundle_planner(item: Mapping[str, object]) -> Mapping[str, object]:
    bundle = _mapping(item.get("evidence_bundle"))
    return _mapping(bundle.get("bundle_planner"))


def _retrieval_metadata(item: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_mapping(item.get("retrieval")).get("metadata"))


def _query_integrity(item: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_retrieval_metadata(item).get("query_integrity"))


def _query_plan(item: Mapping[str, object]) -> Mapping[str, object]:
    query_decomposition = _mapping(
        _retrieval_metadata(item).get("query_decomposition")
    )
    return _mapping(query_decomposition.get("query_plan"))


def _query_overlap_count(item: Mapping[str, object]) -> int:
    integrity = _query_integrity(item)
    return (
        _positive_int(integrity.get("expected_answer_query_overlap_count"))
        or _positive_int(integrity.get("expected_answer_query_profile_overlap_count"))
        or 0
    )


def _only_broad_bundle_evidence(item: Mapping[str, object]) -> bool:
    bundle_items = _bundle_items(_mapping(item.get("evidence_bundle")))
    if not bundle_items:
        return False
    return all(
        _metric_value(bundle_item, "focused_evidence_score") <= 0
        for bundle_item in bundle_items
    )


def _bundle_complete(item: Mapping[str, object]) -> bool:
    return bool(_mapping(item.get("evidence_bundle")).get("bundle_complete"))


def _has_evidence_recall(item: Mapping[str, object]) -> bool:
    return "evidence_term_recall" in _mapping(item.get("retrieval_quality"))


def _expected_recall(item: Mapping[str, object]) -> float:
    return _metric_value(_mapping(item.get("retrieval_quality")), "expected_term_recall")


def _evidence_recall(item: Mapping[str, object]) -> float:
    return _metric_value(_mapping(item.get("retrieval_quality")), "evidence_term_recall")


def _judgment_score(item: Mapping[str, object]) -> float:
    return _metric_value(_mapping(item.get("judgment")), "score")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    return tuple(str(item) for item in _sequence(value) if str(item).strip())


def _count_mapping(value: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, raw_count in _mapping(value).items():
        role = str(key).strip()
        if not role:
            continue
        counts[role] = _positive_int(raw_count) or 0
    return dict(sorted(counts.items()))


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _top_counts(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(
        sorted(
            counter.most_common(limit),
            key=lambda pair: (-pair[1], pair[0]),
        )
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: Sequence[float] | object) -> float:
    sequence = tuple(float(value) for value in values)  # type: ignore[arg-type]
    return round(sum(sequence) / len(sequence), 4) if sequence else 0.0
