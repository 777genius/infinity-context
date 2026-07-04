"""Query-role diagnostics for memory-comparison quality reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import avg as _avg
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    candidate_features as _candidate_features,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    memory_diagnostics as _memory_diagnostics,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    metric_value as _metric_value,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_policy_score as _positive_policy_score,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_signal_names as _positive_signal_names,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    ratio as _ratio,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)
from infinity_context_server.memory_comparison_quality_support import (
    typed_relation_support_roles as _typed_relation_support_roles,
)

_TYPED_RELATION_SUPPORT_ROLES = frozenset(_typed_relation_support_roles())
_REQUIRED_ROLE_COVERAGE_SAMPLE_LIMIT = 10
_REQUIRED_ROLE_FAMILY_SAMPLE_LIMIT = 8

_PROFILE_SUPPORT_ROLES = frozenset(
    {
        "action_support",
        "activity_support",
        "age_support",
        "alias_support",
        "commitment_support",
        "contact_support",
        "current_goal_support",
        "date_support",
        "diet_support",
        "education_support",
        "employment_support",
        "health_support",
        "identity_support",
        "pet_support",
        "skill_support",
        "status_support",
        "support_goal_support",
        "vehicle_support",
    }
)


def query_role_effectiveness_table(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    candidate_role_counts: Counter[str] = Counter()
    lifted_candidate_role_counts: Counter[str] = Counter()
    selected_item_role_counts: Counter[str] = Counter()
    typed_relation_hit_role_counts: Counter[str] = Counter()
    typed_relation_lifted_hit_role_counts: Counter[str] = Counter()
    candidate_role_family_counts: Counter[str] = Counter()
    lifted_candidate_role_family_counts: Counter[str] = Counter()
    selected_item_role_family_counts: Counter[str] = Counter()
    bridge_query_hit_candidate_counts: Counter[str] = Counter()
    bridge_query_hit_selected_counts: Counter[str] = Counter()
    bridge_query_hit_candidate_family_counts: Counter[str] = Counter()
    bridge_query_hit_selected_family_counts: Counter[str] = Counter()
    selected_bundle_role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    selected_low_answerability_role_counts: Counter[str] = Counter()
    selected_weak_source_locality_role_counts: Counter[str] = Counter()
    required_evidence_role_counts: Counter[str] = Counter()
    required_role_selected_evidence_query_counts: Counter[str] = Counter()
    missing_required_evidence_role_counts: Counter[str] = Counter()
    missing_required_role_candidate_query_counts: Counter[str] = Counter()
    missing_required_role_selected_query_counts: Counter[str] = Counter()
    missing_required_role_selected_evidence_query_counts: Counter[str] = Counter()
    required_role_coverage_gap_counts: Counter[str] = Counter()
    required_role_coverage_gap_count = 0
    required_role_coverage_gap_samples: list[dict[str, object]] = []
    candidate_answerability_scores: dict[str, list[float]] = defaultdict(list)
    selected_answerability_scores: dict[str, list[float]] = defaultdict(list)
    candidate_source_locality_scores: dict[str, list[float]] = defaultdict(list)
    selected_source_locality_scores: dict[str, list[float]] = defaultdict(list)

    for item in items:
        item_candidate_role_families: set[str] = set()
        for memory in _sequence(_mapping(item.get("retrieval")).get("results")):
            if not isinstance(memory, Mapping):
                continue
            features = _candidate_features(memory)
            query_roles = _str_tuple(features.get("query_roles"))
            if not query_roles:
                continue
            diagnostics = _memory_diagnostics(memory)
            lifted = _candidate_lifted(diagnostics)
            score_signals = _mapping(diagnostics.get("score_signals"))
            typed_relation_hit_roles = _str_tuple(
                score_signals.get("benchmark_typed_relation_support_hit_roles")
            )
            bridge_query_hit = features.get("bridge_query_hit") is True
            answerability_score = _metric_value(features, "answerability_score")
            source_locality_score = _metric_value(features, "source_locality_score")
            for query_role in query_roles:
                query_role_families = _query_role_families(query_role)
                item_candidate_role_families.update(query_role_families)
                candidate_role_counts[query_role] += 1
                candidate_role_family_counts.update(query_role_families)
                candidate_answerability_scores[query_role].append(answerability_score)
                candidate_source_locality_scores[query_role].append(
                    source_locality_score
                )
                if lifted:
                    lifted_candidate_role_counts[query_role] += 1
                    lifted_candidate_role_family_counts.update(query_role_families)
                if bridge_query_hit:
                    bridge_query_hit_candidate_counts[query_role] += 1
                    bridge_query_hit_candidate_family_counts.update(
                        query_role_families
                    )
            for hit_role in typed_relation_hit_roles:
                typed_relation_hit_role_counts[hit_role] += 1
                if lifted:
                    typed_relation_lifted_hit_role_counts[hit_role] += 1

        bundle = _mapping(item.get("evidence_bundle"))
        required_roles = _required_evidence_roles(item)
        required_role_set = set(required_roles)
        missing_required_roles = _str_tuple(bundle.get("missing_required_roles"))
        missing_required_role_set = set(missing_required_roles)
        selected_query_role_families = _selected_query_role_families(item)
        for role in required_roles:
            required_evidence_role_counts[role] += 1
            required_family = _required_evidence_role_query_family(role)
            gap_reasons: list[str] = []
            if (
                required_family
                and required_family not in item_candidate_role_families
            ):
                missing_required_role_candidate_query_counts[role] += 1
                gap_reasons.append("candidate_query")
            required_selected_families = (
                _required_evidence_role_selected_query_families(role)
            )
            if (
                required_selected_families
                and selected_query_role_families
                and not selected_query_role_families.intersection(
                    required_selected_families
                )
            ):
                missing_required_role_selected_query_counts[role] += 1
                gap_reasons.append("selected_query")
            selected_evidence_query_families = (
                _selected_evidence_query_families_for_required_role(item, role)
            )
            if required_selected_families:
                if selected_evidence_query_families.intersection(
                    required_selected_families
                ):
                    required_role_selected_evidence_query_counts[role] += 1
                else:
                    missing_required_role_selected_evidence_query_counts[role] += 1
                    gap_reasons.append("selected_evidence_query")
            if role in missing_required_role_set:
                gap_reasons.append("missing_required_evidence")
            if gap_reasons:
                required_role_coverage_gap_count += 1
                required_role_coverage_gap_counts.update(gap_reasons)
                _append_required_role_coverage_gap_sample(
                    required_role_coverage_gap_samples,
                    item=item,
                    role=role,
                    gap_reasons=gap_reasons,
                    required_query_family=required_family,
                    required_selected_query_families=required_selected_families,
                    candidate_role_families=item_candidate_role_families,
                    selected_query_role_families=selected_query_role_families,
                    selected_evidence_query_families=selected_evidence_query_families,
                )
        for role in missing_required_roles:
            missing_required_evidence_role_counts[role] += 1
            if role not in required_role_set:
                required_role_coverage_gap_count += 1
                required_role_coverage_gap_counts["missing_required_evidence"] += 1
                _append_required_role_coverage_gap_sample(
                    required_role_coverage_gap_samples,
                    item=item,
                    role=role,
                    gap_reasons=["missing_required_evidence"],
                    required_query_family=_required_evidence_role_query_family(role),
                    required_selected_query_families=(
                        _required_evidence_role_selected_query_families(role)
                    ),
                    candidate_role_families=item_candidate_role_families,
                    selected_query_role_families=selected_query_role_families,
                    selected_evidence_query_families=(
                        _selected_evidence_query_families_for_required_role(item, role)
                    ),
                )

        for bundle_item in _bundle_items(bundle):
            query_roles = _str_tuple(bundle_item.get("query_roles"))
            if not query_roles:
                continue
            bundle_role = str(bundle_item.get("role") or "unknown").strip() or "unknown"
            bridge_query_hit = bundle_item.get("bridge_query_hit") is True
            has_answerability_score = "answerability_score" in bundle_item
            has_source_locality_score = "source_locality_score" in bundle_item
            answerability_score = _metric_value(bundle_item, "answerability_score")
            source_locality_score = _metric_value(bundle_item, "source_locality_score")
            selected_low_answerability = (
                has_answerability_score
                and _is_measured_low_answerability(answerability_score)
            )
            selected_weak_source_locality = (
                has_source_locality_score
                and _is_measured_weak_source_locality(source_locality_score)
            )
            for query_role in query_roles:
                query_role_families = _query_role_families(query_role)
                selected_item_role_counts[query_role] += 1
                selected_item_role_family_counts.update(query_role_families)
                selected_bundle_role_counts[query_role][bundle_role] += 1
                if selected_low_answerability:
                    selected_low_answerability_role_counts[query_role] += 1
                if selected_weak_source_locality:
                    selected_weak_source_locality_role_counts[query_role] += 1
                if has_answerability_score:
                    selected_answerability_scores[query_role].append(answerability_score)
                if has_source_locality_score:
                    selected_source_locality_scores[query_role].append(
                        source_locality_score
                    )
                if bridge_query_hit:
                    bridge_query_hit_selected_counts[query_role] += 1
                    bridge_query_hit_selected_family_counts.update(query_role_families)

    query_roles = sorted(
        set(candidate_role_counts)
        | set(selected_item_role_counts)
        | set(lifted_candidate_role_counts)
        | set(typed_relation_hit_role_counts)
    )
    role_stats = {
        query_role: _query_role_stat_payload(
            query_role,
            candidate_role_counts=candidate_role_counts,
            lifted_candidate_role_counts=lifted_candidate_role_counts,
            selected_item_role_counts=selected_item_role_counts,
            typed_relation_hit_role_counts=typed_relation_hit_role_counts,
            typed_relation_lifted_hit_role_counts=(
                typed_relation_lifted_hit_role_counts
            ),
            bridge_query_hit_candidate_counts=bridge_query_hit_candidate_counts,
            bridge_query_hit_selected_counts=bridge_query_hit_selected_counts,
            selected_bundle_role_counts=selected_bundle_role_counts,
            selected_low_answerability_role_counts=(
                selected_low_answerability_role_counts
            ),
            selected_weak_source_locality_role_counts=(
                selected_weak_source_locality_role_counts
            ),
            candidate_answerability_scores=candidate_answerability_scores,
            selected_answerability_scores=selected_answerability_scores,
            candidate_source_locality_scores=candidate_source_locality_scores,
            selected_source_locality_scores=selected_source_locality_scores,
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
        "selected_low_answerability_role_counts": dict(
            sorted(selected_low_answerability_role_counts.items())
        ),
        "selected_weak_source_locality_role_counts": dict(
            sorted(selected_weak_source_locality_role_counts.items())
        ),
        "typed_relation_hit_role_counts": dict(
            sorted(typed_relation_hit_role_counts.items())
        ),
        "typed_relation_lifted_hit_role_counts": dict(
            sorted(typed_relation_lifted_hit_role_counts.items())
        ),
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
        "bridge_query_hit_candidate_family_counts": dict(
            sorted(bridge_query_hit_candidate_family_counts.items())
        ),
        "bridge_query_hit_selected_family_counts": dict(
            sorted(bridge_query_hit_selected_family_counts.items())
        ),
        "required_evidence_role_counts": dict(
            sorted(required_evidence_role_counts.items())
        ),
        "required_role_selected_evidence_query_counts": dict(
            sorted(required_role_selected_evidence_query_counts.items())
        ),
        "missing_required_evidence_role_counts": dict(
            sorted(missing_required_evidence_role_counts.items())
        ),
        "missing_required_role_candidate_query_counts": dict(
            sorted(missing_required_role_candidate_query_counts.items())
        ),
        "missing_required_role_selected_query_counts": dict(
            sorted(missing_required_role_selected_query_counts.items())
        ),
        "missing_required_role_selected_evidence_query_counts": dict(
            sorted(missing_required_role_selected_evidence_query_counts.items())
        ),
        "required_role_coverage_gap_count": required_role_coverage_gap_count,
        "required_role_coverage_gap_counts": dict(
            sorted(required_role_coverage_gap_counts.items())
        ),
        "required_role_coverage_gap_samples": required_role_coverage_gap_samples,
        "required_roles_without_candidate_queries": [
            role
            for role in sorted(required_evidence_role_counts)
            if missing_required_role_candidate_query_counts[role] > 0
        ],
        "required_roles_without_selected_queries": [
            role
            for role in sorted(required_evidence_role_counts)
            if missing_required_role_selected_query_counts[role] > 0
        ],
        "required_roles_without_selected_evidence_queries": [
            role
            for role in sorted(required_evidence_role_counts)
            if missing_required_role_selected_evidence_query_counts[role] > 0
        ],
        "missing_required_evidence_roles": [
            role
            for role in sorted(missing_required_evidence_role_counts)
            if missing_required_evidence_role_counts[role] > 0
        ],
        "roles_without_selected_items": [
            query_role for query_role in query_roles if not selected_item_role_counts[query_role]
        ],
        "roles_without_lifted_candidates": [
            query_role
            for query_role in query_roles
            if not lifted_candidate_role_counts[query_role]
        ],
        "roles_without_typed_relation_hits": [
            query_role
            for query_role in query_roles
            if query_role in _TYPED_RELATION_SUPPORT_ROLES
            and not typed_relation_hit_role_counts[query_role]
        ],
        "role_stats": role_stats,
    }


def _query_role_families(query_role: str) -> tuple[str, ...]:
    role = str(query_role or "").strip()
    if role == "visual_temporal_support":
        return ("visual_support", "temporal_support")
    if role == "location_support":
        return ("relation_compact", "location_support")
    if role == "causal_support":
        return ("relation_compact", "causal_support")
    if role in {"favorite_support", "preference_support"}:
        return ("relation_compact", "preference_support")
    if role in {
        "temporal_support",
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
    } or role.endswith("_temporal_support"):
        return ("temporal_support",)
    if role.startswith("multi_hop_"):
        return ("multi_hop",)
    if role in {"original_question", "fallback_original"}:
        return ("base_query",)
    if role == "expanded_focus":
        return ("expanded_focus",)
    if role == "compact_relation":
        return ("relation_compact",)
    if role in {
        "communication_support",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "symbolic_meaning_support",
    }:
        return ("relation_compact",)
    if role in _PROFILE_SUPPORT_ROLES:
        return ("relation_compact",)
    if role == "contrast_support":
        return ("contrast_support",)
    return (role or "unknown",)


def _query_role_family(query_role: str) -> str:
    return _query_role_families(query_role)[0]


def _append_required_role_coverage_gap_sample(
    samples: list[dict[str, object]],
    *,
    item: Mapping[str, object],
    role: str,
    gap_reasons: Sequence[str],
    required_query_family: str,
    required_selected_query_families: Sequence[str],
    candidate_role_families: set[str],
    selected_query_role_families: set[str],
    selected_evidence_query_families: set[str],
) -> None:
    if len(samples) >= _REQUIRED_ROLE_COVERAGE_SAMPLE_LIMIT:
        return
    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "required_role": role,
        "gap_reasons": list(dict.fromkeys(gap_reasons)),
    }
    if required_query_family:
        sample["required_query_family"] = required_query_family
    if required_selected_query_families:
        sample["required_selected_query_families"] = _bounded_sorted_strings(
            required_selected_query_families
        )
    sample["candidate_query_role_families"] = _bounded_sorted_strings(
        candidate_role_families
    )
    sample["selected_query_role_families"] = _bounded_sorted_strings(
        selected_query_role_families
    )
    sample["selected_evidence_query_role_families"] = _bounded_sorted_strings(
        selected_evidence_query_families
    )
    samples.append(sample)


def _bounded_sorted_strings(values: Sequence[str] | set[str]) -> list[str]:
    return sorted(str(value) for value in values if str(value).strip())[
        :_REQUIRED_ROLE_FAMILY_SAMPLE_LIMIT
    ]


def _required_evidence_roles(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    roles: list[str] = [*_str_tuple(bundle.get("required_roles"))]
    metadata = _mapping(_mapping(item.get("retrieval")).get("metadata"))
    for key in ("query_decomposition", "query_expansion", "benchmark_rerank"):
        payload = _mapping(metadata.get(key))
        profile = _mapping(payload.get("query_profile"))
        intent = _mapping(payload.get("retrieval_intent"))
        roles.extend(_str_tuple(profile.get("bundle_evidence_roles")))
        roles.extend(_str_tuple(intent.get("bundle_evidence_roles")))
    return tuple(dict.fromkeys(role for role in roles if role.strip()))


def _selected_query_role_families(item: Mapping[str, object]) -> set[str]:
    metadata = _mapping(_mapping(item.get("retrieval")).get("metadata"))
    families: set[str] = set()
    for key in ("query_decomposition", "query_expansion", "benchmark_rerank"):
        payload = _mapping(metadata.get(key))
        query_plan = _mapping(payload.get("query_plan"))
        families.update(_str_tuple(query_plan.get("selected_role_families")))
    return families


def _selected_evidence_query_families_for_required_role(
    item: Mapping[str, object],
    role: str,
) -> set[str]:
    bundle = _mapping(item.get("evidence_bundle"))
    families: set[str] = set()
    for bundle_item in _bundle_items(bundle):
        bundle_role = str(bundle_item.get("role") or "").strip()
        if not _bundle_role_matches_required_role(bundle_role, role):
            continue
        for query_role in _str_tuple(bundle_item.get("query_roles")):
            families.update(_query_role_families(query_role))
    return families


def _bundle_role_matches_required_role(bundle_role: str, required_role: str) -> bool:
    role = str(required_role or "").strip()
    selected_role = str(bundle_role or "").strip()
    if not role or not selected_role:
        return False
    return selected_role in _required_evidence_role_aliases(role)


def _required_evidence_role_aliases(role: str) -> tuple[str, ...]:
    normalized = str(role or "").strip()
    if not normalized:
        return ()
    aliases = {
        "bridge": ("bridge", "multi_hop_bridge", "multi_hop_support"),
        "multi_hop_bridge": ("bridge", "multi_hop_bridge", "multi_hop_support"),
        "multi_hop_support": ("bridge", "multi_hop_bridge", "multi_hop_support"),
        "location": ("location", "location_support"),
        "location_support": ("location", "location_support"),
        "contrast": ("contrast", "contrast_support"),
        "contrast_support": ("contrast", "contrast_support"),
        "visual": ("visual", "visual_support"),
        "visual_support": ("visual", "visual_support"),
    }
    return aliases.get(normalized, (normalized,))


def _required_evidence_role_query_family(role: str) -> str:
    normalized = str(role or "").strip()
    if not normalized or normalized == "primary":
        return ""
    if normalized in {"bridge", "multi_hop_bridge", "multi_hop_support"}:
        return "multi_hop"
    if normalized in {"location", "location_support"}:
        return "location_support"
    if normalized in {"contrast", "contrast_support"}:
        return "contrast_support"
    if normalized in {"visual", "visual_support"}:
        return "visual_support"
    if normalized == "count_support":
        return "count_support"
    if (
        normalized == "temporal_support"
        or normalized == "visual_temporal_support"
        or normalized.endswith("_temporal_support")
        or normalized == "temporal_sequence_support"
    ):
        return "temporal_support"
    if normalized == "compact_relation" or normalized in _PROFILE_SUPPORT_ROLES:
        return "relation_compact"
    if normalized in {
        "causal_support",
        "communication_support",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "favorite_support",
        "inference_support",
        "preference_support",
        "symbolic_meaning_support",
    }:
        return "relation_compact"
    return _query_role_family(normalized)


def _required_evidence_role_selected_query_families(role: str) -> tuple[str, ...]:
    normalized = str(role or "").strip()
    if not normalized or normalized == "primary":
        return ()
    if normalized in _PROFILE_SUPPORT_ROLES:
        return ("relation_compact", "expanded_focus")
    return {
        "bridge": ("multi_hop", "relation_compact", "expanded_focus"),
        "multi_hop_bridge": ("multi_hop", "relation_compact", "expanded_focus"),
        "multi_hop_support": ("multi_hop", "relation_compact", "expanded_focus"),
        "location": ("location_support", "relation_compact", "expanded_focus"),
        "location_support": (
            "location_support",
            "relation_compact",
            "expanded_focus",
        ),
        "contrast": ("contrast_support", "relation_compact", "expanded_focus"),
        "contrast_support": (
            "contrast_support",
            "relation_compact",
            "expanded_focus",
        ),
        "visual": ("visual_support", "expanded_focus", "relation_compact"),
        "visual_support": (
            "visual_support",
            "expanded_focus",
            "relation_compact",
        ),
        "count_support": ("count_support", "expanded_focus"),
        "list_support": ("list_support", "expanded_focus"),
        "value_support": ("value_support", "expanded_focus"),
        "temporal_support": ("temporal_support", "expanded_focus"),
        "visual_temporal_support": ("temporal_support", "expanded_focus"),
        "temporal_sequence_support": ("temporal_support", "expanded_focus"),
        "compact_relation": ("relation_compact", "expanded_focus"),
        "causal_support": ("multi_hop", "relation_compact", "expanded_focus"),
        "communication_support": ("relation_compact", "expanded_focus"),
        "event_support": ("relation_compact", "expanded_focus"),
        "exchange_support": ("relation_compact", "expanded_focus"),
        "emotion_response_support": ("relation_compact", "expanded_focus"),
        "favorite_support": ("relation_compact", "expanded_focus"),
        "symbolic_meaning_support": ("relation_compact", "expanded_focus"),
        "inference_support": (
            "relation_compact",
            "expanded_focus",
            "base_query",
        ),
        "preference_support": (
            "relation_compact",
            "expanded_focus",
            "base_query",
        ),
    }.get(normalized, (_query_role_family(normalized),))


def _query_role_stat_payload(
    query_role: str,
    *,
    candidate_role_counts: Counter[str],
    lifted_candidate_role_counts: Counter[str],
    selected_item_role_counts: Counter[str],
    typed_relation_hit_role_counts: Counter[str],
    typed_relation_lifted_hit_role_counts: Counter[str],
    bridge_query_hit_candidate_counts: Counter[str],
    bridge_query_hit_selected_counts: Counter[str],
    selected_bundle_role_counts: Mapping[str, Counter[str]],
    selected_low_answerability_role_counts: Counter[str],
    selected_weak_source_locality_role_counts: Counter[str],
    candidate_answerability_scores: Mapping[str, Sequence[float]],
    selected_answerability_scores: Mapping[str, Sequence[float]],
    candidate_source_locality_scores: Mapping[str, Sequence[float]],
    selected_source_locality_scores: Mapping[str, Sequence[float]],
) -> dict[str, object]:
    candidate_count = candidate_role_counts[query_role]
    lifted_count = lifted_candidate_role_counts[query_role]
    selected_count = selected_item_role_counts[query_role]
    typed_relation_hit_count = typed_relation_hit_role_counts[query_role]
    typed_relation_lifted_hit_count = typed_relation_lifted_hit_role_counts[
        query_role
    ]
    candidate_scores = tuple(candidate_answerability_scores.get(query_role, ()))
    selected_scores = tuple(selected_answerability_scores.get(query_role, ()))
    measured_candidate_scores = tuple(score for score in candidate_scores if score > 0)
    measured_selected_scores = tuple(score for score in selected_scores if score > 0)
    candidate_locality_scores = tuple(
        candidate_source_locality_scores.get(query_role, ())
    )
    selected_locality_scores = tuple(
        selected_source_locality_scores.get(query_role, ())
    )
    measured_candidate_locality_scores = tuple(
        score for score in candidate_locality_scores if score > 0
    )
    measured_selected_locality_scores = tuple(
        score for score in selected_locality_scores if score > 0
    )
    return {
        "candidate_count": candidate_count,
        "lifted_candidate_count": lifted_count,
        "selected_item_count": selected_count,
        "typed_relation_hit_count": typed_relation_hit_count,
        "typed_relation_lifted_hit_count": typed_relation_lifted_hit_count,
        "selection_rate": _ratio(selected_count, candidate_count),
        "lifted_rate": _ratio(lifted_count, candidate_count),
        "typed_relation_hit_rate": _ratio(typed_relation_hit_count, candidate_count),
        "bridge_query_hit_candidate_count": bridge_query_hit_candidate_counts[
            query_role
        ],
        "bridge_query_hit_selected_count": bridge_query_hit_selected_counts[query_role],
        "selected_low_answerability_count": selected_low_answerability_role_counts[
            query_role
        ],
        "selected_weak_source_locality_count": (
            selected_weak_source_locality_role_counts[query_role]
        ),
        "avg_candidate_answerability_score": _avg(candidate_scores),
        "avg_measured_candidate_answerability_score": _avg(measured_candidate_scores),
        "candidate_unmeasured_answerability_count": sum(
            1 for score in candidate_scores if score <= 0
        ),
        "avg_candidate_source_locality_score": _avg(candidate_locality_scores),
        "avg_measured_candidate_source_locality_score": _avg(
            measured_candidate_locality_scores
        ),
        "candidate_unmeasured_source_locality_count": sum(
            1 for score in candidate_locality_scores if score <= 0
        ),
        "avg_selected_answerability_score": _avg(selected_scores),
        "avg_measured_selected_answerability_score": _avg(measured_selected_scores),
        "selected_unmeasured_answerability_count": sum(
            1 for score in selected_scores if score <= 0
        ),
        "avg_selected_source_locality_score": _avg(selected_locality_scores),
        "avg_measured_selected_source_locality_score": _avg(
            measured_selected_locality_scores
        ),
        "selected_unmeasured_source_locality_count": sum(
            1 for score in selected_locality_scores if score <= 0
        ),
        "selected_bundle_role_counts": dict(
            sorted(selected_bundle_role_counts.get(query_role, Counter()).items())
        ),
    }


def _candidate_lifted(diagnostics: Mapping[str, object]) -> bool:
    score_signals = _mapping(diagnostics.get("score_signals"))
    return (
        diagnostics.get("benchmark_rerank_boosted") is True
        or _positive_policy_score(diagnostics) > 0
        or bool(_positive_signal_names(score_signals))
    )


def _is_measured_low_answerability(score: float) -> bool:
    return 0 < score < 0.55


def _is_measured_weak_source_locality(score: float) -> bool:
    return 0 < score < 0.45
