"""Payload access helpers for memory-comparison quality diagnostics."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_candidate_risks import (
    payload_candidate_features,
)

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")


def retrieval_results(
    items: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        result
        for item in items
        for result in sequence(mapping(item.get("retrieval")).get("results"))
        if isinstance(result, Mapping)
    )


def candidate_features(memory: Mapping[str, object]) -> Mapping[str, object]:
    return payload_candidate_features(memory)


def source_refs_from_memory(memory: Mapping[str, object]) -> tuple[str, ...]:
    direct_refs = direct_source_refs_from_memory(memory)
    return tuple(
        dict.fromkeys(
            (
                *direct_refs,
                *fusion_source_refs(memory),
                *_source_identity_refs_from_dedupe_key(
                    candidate_features(memory).get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_text(
                    str(memory.get("text") or memory.get("memory") or ""),
                    source_refs=direct_refs,
                ),
            )
        )
    )


def direct_source_refs_from_memory(memory: Mapping[str, object]) -> tuple[str, ...]:
    return str_tuple(memory.get("source_refs"))


def fusion_source_refs(memory: Mapping[str, object]) -> tuple[str, ...]:
    fusion = mapping(memory_diagnostics(memory).get("benchmark_candidate_fusion"))
    return str_tuple(fusion.get("source_refs"))


def source_refs_from_bundle_item(item: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *str_tuple(item.get("source_refs")),
                *_source_identity_refs_from_dedupe_key(item.get("source_ref_dedupe_key")),
                *_source_identity_refs_from_dedupe_key(item.get("dedupe_key")),
            )
        )
    )


def memory_diagnostics(memory: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(mapping(memory.get("metadata")).get("diagnostics"))


def positive_policy_score(diagnostics: Mapping[str, object]) -> float:
    policy = mapping(diagnostics.get("benchmark_rerank_policy"))
    total = 0.0
    for contribution in sequence(policy.get("contributions")):
        score = metric_value(mapping(contribution), "score")
        if score > 0:
            total += score
    return round(total, 6)


def active_policy_reasons(
    diagnostics: Mapping[str, object],
) -> dict[str, tuple[str, ...]]:
    policy_reasons: dict[str, tuple[str, ...]] = {}
    policy = mapping(diagnostics.get("benchmark_rerank_policy"))
    for contribution in sequence(policy.get("contributions")):
        payload = mapping(contribution)
        score = metric_value(payload, "score")
        reasons = str_tuple(payload.get("reason_codes"))
        if score <= 0 and not reasons:
            continue
        name = str(payload.get("policy") or "unknown")
        policy_reasons[name] = reasons
    return policy_reasons


def positive_signal_names(score_signals: Mapping[str, object]) -> tuple[str, ...]:
    names: list[str] = []
    for name, value in score_signals.items():
        if isinstance(value, bool):
            if value:
                names.append(str(name))
            continue
        if metric_value(score_signals, str(name)) > 0:
            names.append(str(name))
    return tuple(names)


def top_signal_values(score_signals: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    for name in positive_signal_names(score_signals):
        value = score_signals.get(name)
        if isinstance(value, bool):
            values[name] = value
        else:
            values[name] = round(metric_value(score_signals, name), 6)
    return dict(sorted(values.items(), key=lambda pair: str(pair[0]))[:8])


def memory_id(memory: Mapping[str, object]) -> str:
    return str(memory.get("id") or memory.get("item_id") or "")


def selected_source_locality_score(item: Mapping[str, object]) -> float:
    planner = bundle_planner(item)
    if "average_selected_source_locality_score" in planner:
        return metric_value(planner, "average_selected_source_locality_score")
    items = bundle_items(mapping(item.get("evidence_bundle")))
    locality_scores = [
        metric_value(bundle_item, "source_locality_score")
        for bundle_item in items
        if "source_locality_score" in bundle_item
    ]
    return avg(locality_scores)


def bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in sequence(bundle.get("items")) if isinstance(item, Mapping))


def bundle_quality(item: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(bundle_planner(item).get("bundle_quality"))


def bundle_planner(item: Mapping[str, object]) -> Mapping[str, object]:
    bundle = mapping(item.get("evidence_bundle"))
    return mapping(bundle.get("bundle_planner"))


def retrieval_metadata(item: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(mapping(item.get("retrieval")).get("metadata"))


def query_integrity(item: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(retrieval_metadata(item).get("query_integrity"))


def query_plan(item: Mapping[str, object]) -> Mapping[str, object]:
    metadata = retrieval_metadata(item)
    for key in ("query_decomposition", "query_expansion", "benchmark_rerank"):
        query_plan_payload = mapping(mapping(metadata.get(key)).get("query_plan"))
        if query_plan_payload:
            return query_plan_payload
    return {}


def query_overlap_count(item: Mapping[str, object]) -> int:
    integrity = query_integrity(item)
    return (
        (positive_int(integrity.get("expected_answer_query_overlap_count")) or 0)
        + (
            positive_int(integrity.get("expected_answer_query_profile_overlap_count"))
            or 0
        )
        + (
            positive_int(
                integrity.get("expected_answer_retrieval_intent_overlap_count")
            )
            or 0
        )
    )


def only_broad_bundle_evidence(item: Mapping[str, object]) -> bool:
    items = bundle_items(mapping(item.get("evidence_bundle")))
    if not items:
        return False
    return all(metric_value(bundle_item, "focused_evidence_score") <= 0 for bundle_item in items)


def bundle_complete(item: Mapping[str, object]) -> bool:
    return bool(mapping(item.get("evidence_bundle")).get("bundle_complete"))


def has_evidence_recall(item: Mapping[str, object]) -> bool:
    return "evidence_term_recall" in mapping(item.get("retrieval_quality"))


def expected_recall(item: Mapping[str, object]) -> float:
    return metric_value(mapping(item.get("retrieval_quality")), "expected_term_recall")


def evidence_recall(item: Mapping[str, object]) -> float:
    return metric_value(mapping(item.get("retrieval_quality")), "evidence_term_recall")


def judgment_score(item: Mapping[str, object]) -> float:
    return metric_value(mapping(item.get("judgment")), "score")


def mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    return tuple(str(item) for item in sequence(value) if str(item).strip())


def _source_identity_refs_from_dedupe_key(value: object) -> tuple[str, ...]:
    key = str(value or "").strip()
    if key.startswith(("source_refs:", "source_turn_refs:", "refs:")):
        return (key,)
    return ()


def _source_identity_refs_from_text(
    text: str,
    *,
    source_refs: Sequence[str],
) -> tuple[str, ...]:
    if source_refs:
        return ()
    turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(text or "")))
    if not 0 < len(turn_refs) <= 3:
        return ()
    return ("source_turn_refs:" + "|".join(sorted(turn_refs)),)


def count_mapping(value: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, raw_count in mapping(value).items():
        role = str(key).strip()
        if not role:
            continue
        counts[role] = positive_int(raw_count) or 0
    return dict(sorted(counts.items()))


def positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def top_counts(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(
        sorted(
            counter.most_common(limit),
            key=lambda pair: (-pair[1], pair[0]),
        )
    )


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def avg(values: Sequence[float] | object) -> float:
    sequence_value = tuple(float(value) for value in values)  # type: ignore[arg-type]
    return round(sum(sequence_value) / len(sequence_value), 4) if sequence_value else 0.0
