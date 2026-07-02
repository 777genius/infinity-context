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


def query_role_effectiveness_table(
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
    candidate_source_locality_scores: dict[str, list[float]] = defaultdict(list)
    selected_source_locality_scores: dict[str, list[float]] = defaultdict(list)

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
            source_locality_score = _metric_value(features, "source_locality_score")
            for query_role in query_roles:
                query_role_family = _query_role_family(query_role)
                candidate_role_counts[query_role] += 1
                candidate_role_family_counts[query_role_family] += 1
                candidate_answerability_scores[query_role].append(answerability_score)
                candidate_source_locality_scores[query_role].append(
                    source_locality_score
                )
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
            has_source_locality_score = "source_locality_score" in bundle_item
            answerability_score = _metric_value(bundle_item, "answerability_score")
            source_locality_score = _metric_value(bundle_item, "source_locality_score")
            for query_role in query_roles:
                query_role_family = _query_role_family(query_role)
                selected_item_role_counts[query_role] += 1
                selected_item_role_family_counts[query_role_family] += 1
                selected_bundle_role_counts[query_role][bundle_role] += 1
                if has_answerability_score:
                    selected_answerability_scores[query_role].append(answerability_score)
                if has_source_locality_score:
                    selected_source_locality_scores[query_role].append(
                        source_locality_score
                    )
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
    if role in {"original_question", "fallback_original"}:
        return "base_query"
    if role == "expanded_focus":
        return "expanded_focus"
    if role == "compact_relation":
        return "relation_compact"
    if role in {
        "causal_support",
        "communication_support",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "preference_support",
        "symbolic_meaning_support",
    }:
        return "relation_compact"
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
    candidate_source_locality_scores: Mapping[str, Sequence[float]],
    selected_source_locality_scores: Mapping[str, Sequence[float]],
) -> dict[str, object]:
    candidate_count = candidate_role_counts[query_role]
    lifted_count = lifted_candidate_role_counts[query_role]
    selected_count = selected_item_role_counts[query_role]
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
        "selection_rate": _ratio(selected_count, candidate_count),
        "lifted_rate": _ratio(lifted_count, candidate_count),
        "bridge_query_hit_candidate_count": bridge_query_hit_candidate_counts[
            query_role
        ],
        "bridge_query_hit_selected_count": bridge_query_hit_selected_counts[query_role],
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
