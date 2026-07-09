"""Compact report sampling and redaction helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from math import isfinite

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_benchmark_config import (
    _COMPACT_RAW_PAYLOAD_KEYS,
    _COMPACT_REDACTED_TEXT,
    _COMPACT_UNSAFE_TEXT_MARKERS,
    _COMPACT_UNSAFE_TEXT_PREFIXES,
    _MAX_COMPACT_FAILURE_TEXT_CHARS,
    _MAX_COMPACT_SAMPLE_TEXT_CHARS,
    _MAX_COMPACT_SOURCE_REF_TEXT_CHARS,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _avg,
    _mapping,
    _metric_value,
    _positive_int,
    _positive_ints,
    _ratio,
    _str_tuple,
)
from infinity_context_server.memory_comparison_compact_gap_report import (
    compact_evidence_ref_list as _compact_evidence_ref_list,
)
from infinity_context_server.memory_comparison_compact_gap_report import (
    compact_text_list as _compact_text_list,
)
from infinity_context_server.memory_comparison_source_identity import (
    looks_like_raw_source_ref as _looks_like_raw_source_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_identity_ref as _safe_source_identity_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_turn_ref as _safe_exact_turn_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)


def _compact_actionable_gaps(
    value: object,
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    gaps: list[dict[str, object]] = []
    for raw_gap in value:
        gap = _mapping(raw_gap)
        if not gap:
            continue
        compact: dict[str, object] = {}
        for key in ("rank", "impact_count"):
            count = _positive_int(gap.get(key))
            if count is not None:
                compact[key] = count
        impact_rate = gap.get("impact_rate")
        if isinstance(impact_rate, (int, float)) and not isinstance(impact_rate, bool):
            compact["impact_rate"] = round(float(impact_rate), 6)
        for key in ("severity", "category", "gap", "failed_gate", "source_metric"):
            value_text = _compact_sample_text(gap.get(key))
            if value_text:
                compact[key] = value_text
        action = _compact_actionable_gap_action(gap.get("action"))
        if action:
            compact["action"] = action
        sample_case_ids = _compact_sample_values(
            gap.get("sample_case_ids"),
            limit=3,
        )
        if sample_case_ids:
            compact["sample_case_ids"] = sample_case_ids
        if compact:
            gaps.append(compact)
        if len(gaps) >= limit:
            break
    return gaps


def _compact_actionable_gap_action(value: object, *, limit: int = 180) -> str:
    return _compact_sample_text(value, limit=limit)


def _compact_sample_text(
    value: object,
    *,
    limit: int = _MAX_COMPACT_SAMPLE_TEXT_CHARS,
) -> str:
    return _compact_safe_text(value, limit=limit)


def _compact_failure_text(
    value: object,
    *,
    limit: int = _MAX_COMPACT_FAILURE_TEXT_CHARS,
) -> str:
    return _compact_safe_text(value, limit=limit, normalize_whitespace=True)


def _compact_safe_text(
    value: object,
    *,
    limit: int,
    normalize_whitespace: bool = False,
) -> str:
    text = str(value or "").strip()
    if normalize_whitespace:
        text = " ".join(text.split())
    text = redact_sensitive_text(text)
    if normalize_whitespace:
        text = " ".join(text.split())
    if not text:
        return ""
    if _looks_like_unsafe_compact_text(text):
        return _COMPACT_REDACTED_TEXT
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _looks_like_unsafe_compact_text(value: object) -> bool:
    raw_text = str(value or "").strip()
    if not raw_text:
        return False
    if _looks_like_raw_source_ref(raw_text):
        return True
    text = raw_text.lower()
    if any(text.startswith(prefix) for prefix in _COMPACT_UNSAFE_TEXT_PREFIXES):
        return True
    return any(marker in text for marker in _COMPACT_UNSAFE_TEXT_MARKERS)


def _compact_key_name(value: object) -> str:
    return str(value or "").strip().casefold()


def _compact_should_omit_key(key: str) -> bool:
    return key in _COMPACT_RAW_PAYLOAD_KEYS or key.endswith("_payload")


def _compact_source_refs_key(key: str) -> bool:
    return key in {"raw_source_refs", "source_refs"}


def _compact_source_ref_key(key: str) -> bool:
    return key in {"ref", "source_ref"} or key.endswith("_turn_ref")


def _compact_source_id_key(key: str) -> bool:
    return key == "source_id" or key.endswith("_source_id")


def _compact_item_ids_key(key: str) -> bool:
    return key in {"item_ids", "selected_item_ids"}


def _compact_item_id_key(key: str) -> bool:
    return key in {"id", "item_id", "memory_id"}


def _compact_item_id(value: object, *, limit: int = 128) -> str | None:
    text = str(value or "").strip()
    if not text or _looks_like_unsafe_compact_text(text):
        return None
    return _compact_safe_text(text, limit=limit)


def _compact_item_ids(value: object, *, limit: int) -> list[str]:
    values: list[str] = []
    for raw_value in _str_tuple(value):
        text = _compact_item_id(raw_value)
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _compact_source_ref_text(value: object) -> str:
    refs = _compact_diagnostic_source_refs((str(value or ""),), limit=1)
    if refs:
        return refs[0]
    if _looks_like_unsafe_compact_text(value):
        return ""
    return _compact_safe_text(value, limit=_MAX_COMPACT_SOURCE_REF_TEXT_CHARS)


def _compact_source_id_text(value: object) -> str:
    ref = _compact_source_ref_text(value)
    if ref:
        return _source_id_from_compact_ref(ref)
    if _looks_like_unsafe_compact_text(value):
        return ""
    return _compact_safe_text(value, limit=_MAX_COMPACT_SOURCE_REF_TEXT_CHARS)


def _source_id_from_compact_ref(ref: str) -> str:
    parts = str(ref or "").split(":")
    if len(parts) <= 1:
        return ref
    return ":".join(parts[:-1])


def _compact_sample_scalar(value: object) -> object | None:
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, str):
        return _compact_sample_text(value) or None
    return None


def _compact_sample_values(
    value: object,
    *,
    limit: int,
    text_limit: int = _MAX_COMPACT_SAMPLE_TEXT_CHARS,
) -> list[str]:
    values: list[str] = []
    for raw_value in _str_tuple(value):
        text = _compact_sample_text(raw_value, limit=text_limit)
        if text:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _compact_answerability_gap_samples(
    value: object,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    scalar_keys = {
        "answerability_reason_count",
        "answerability_score",
        "case_id",
        "group",
        "lifted",
        "memory_id",
        "positive_policy_score",
        "rank",
        "source_locality_score",
    }
    sequence_keys = {
        "answerability_reason_codes",
        "query_roles",
        "reasons",
        "relation_categories",
        "relation_category_hits",
    }
    for raw_sample in value:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in sorted(scalar_keys):
            if key in sample:
                compact_value = (
                    _compact_item_id(sample[key])
                    if key == "memory_id"
                    else _compact_sample_scalar(sample[key])
                )
                if compact_value is not None:
                    compact[key] = compact_value
        for key in sorted(sequence_keys):
            if key in sample:
                values = _compact_sample_values(sample.get(key), limit=6)
                if values:
                    compact[key] = values
        source_identity_refs = _compact_source_identity_refs(
            sample.get("source_identity_refs")
        )
        if source_identity_refs:
            compact["source_identity_refs"] = list(source_identity_refs)
        if compact:
            samples.append(compact)
        if len(samples) >= limit:
            break
    return samples


def _compact_answer_context_support_gap_samples(
    value: object,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    scalar_keys = (
        "case_id",
        "group",
        "cutoff",
        "source",
        "memory_count",
        "source_ref_item_count",
        "source_refless_item_count",
        "source_identity_ref_count",
        "source_identity_item_count",
        "backfilled_retrieval_item_count",
        "skipped_redundant_risky_backfill_count",
        "skipped_redundant_source_backfill_count",
        "skipped_redundant_role_backfill_count",
        "skipped_target_limit_backfill_count",
        "avg_measured_answerability_score",
        "avg_measured_source_locality_score",
        "fallback_reason",
    )
    list_keys = (
        "gap_reasons",
        "missing_required_roles",
        "risk_reason_codes",
        "item_ids",
    )
    for raw_sample in value[:limit]:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in scalar_keys:
            if key not in sample:
                continue
            compact_value = _compact_sample_scalar(sample[key])
            if compact_value is not None:
                compact[key] = compact_value
        for key in list_keys:
            values = (
                _compact_item_ids(sample.get(key), limit=8)
                if key == "item_ids"
                else _compact_sample_values(sample.get(key), limit=8)
            )
            if values:
                compact[key] = values
        source_identity_refs = _compact_source_identity_refs(
            sample.get("source_identity_refs")
        )
        if source_identity_refs:
            compact["source_identity_refs"] = list(source_identity_refs)
        source_identity_items = _compact_answer_context_source_identity_items(
            sample.get("source_identity_items")
        )
        if source_identity_items:
            compact["source_identity_items"] = list(source_identity_items)
        retrieval_orders = _positive_ints(sample.get("retrieval_orders"))[:8]
        if retrieval_orders:
            compact["retrieval_orders"] = list(retrieval_orders)
        if compact:
            samples.append(compact)
    return samples


def _compact_answer_context_source_identity_items(
    value: object,
    *,
    limit: int = 5,
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    compact_items: list[dict[str, object]] = []
    for raw_item in value:
        item = _mapping(raw_item)
        if not item:
            continue
        compact: dict[str, object] = {}
        source_identity_refs = _compact_source_identity_refs(
            item.get("source_identity_refs"),
            limit=5,
        )
        if source_identity_refs:
            compact["source_identity_refs"] = list(source_identity_refs)
        item_id = _compact_item_id(item.get("item_id"))
        if item_id:
            compact["item_id"] = item_id
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is not None:
            compact["retrieval_order"] = retrieval_order
        if compact:
            compact_items.append(compact)
        if len(compact_items) >= limit:
            break
    return tuple(compact_items)


def _compact_source_identity_refs(value: object, *, limit: int = 8) -> tuple[str, ...]:
    return _compact_diagnostic_source_refs(value, limit=limit)


def _compact_temporal_grounding_issue_samples(
    value: object,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    scalar_keys = ("case_id", "group", "item_id", "role")
    list_keys = (
        "query_roles",
        "issue_reasons",
        "source_identity_gap_codes",
    )
    for raw_sample in value[:limit]:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in scalar_keys:
            raw_value = sample.get(key)
            if key == "item_id":
                item_id = _compact_item_id(raw_value, limit=128)
                if item_id:
                    compact[key] = item_id
            elif isinstance(raw_value, str):
                text = _compact_sample_text(raw_value, limit=128)
                if text:
                    compact[key] = text
            elif isinstance(raw_value, int | float | bool):
                compact[key] = raw_value
        for key in list_keys:
            values = _compact_sample_values(sample.get(key), limit=6)
            if values:
                compact[key] = values
        raw_source_refs = _str_tuple(sample.get("source_refs"))
        source_refs = _compact_temporal_grounding_source_refs(raw_source_refs)
        if source_refs:
            compact["source_refs"] = list(source_refs)
        source_ref_count = _positive_int(sample.get("source_ref_count"))
        if source_ref_count is None:
            source_ref_count = _sanitized_source_ref_count(
                raw_source_refs,
                safe_source_refs=source_refs,
            )
        if source_ref_count is not None:
            compact["source_ref_count"] = source_ref_count
        signals = _mapping(sample.get("grounding_signals"))
        signal_payload = {
            key: bool(signals.get(key))
            for key in (
                "source_window",
                "session_boundary",
                "date_or_range",
                "relative_date",
                "bounded_window",
                "temporal_order",
            )
            if key in signals
        }
        if signal_payload:
            compact["grounding_signals"] = signal_payload
        if compact:
            samples.append(compact)
    return samples


def _compact_temporal_grounding_source_refs(
    value: object,
    *,
    limit: int = 6,
) -> tuple[str, ...]:
    return _compact_diagnostic_source_refs(value, limit=limit)


def _compact_diagnostic_source_refs(
    value: object,
    *,
    limit: int,
) -> tuple[str, ...]:
    raw_refs = _str_tuple(value)
    has_explicit_identity_ref = any(_safe_source_identity_ref(raw_ref) for raw_ref in raw_refs)
    refs: list[str] = []
    for raw_ref in raw_refs:
        raw_safe_ref = _safe_source_identity_ref(raw_ref)
        for ref in _safe_diagnostic_source_refs_for_value(raw_ref):
            if (
                has_explicit_identity_ref
                and raw_safe_ref is None
                and ref.startswith("source_turn_refs:")
            ):
                continue
            if ref and ref not in refs:
                refs.append(ref)
            if len(refs) >= limit:
                return tuple(refs)
    return tuple(refs)


def _safe_diagnostic_source_refs_for_value(value: object) -> tuple[str, ...]:
    safe_ref = _safe_source_identity_ref(value)
    if safe_ref:
        return (safe_ref,)
    turn_ref = _safe_turn_ref(value)
    if turn_ref:
        return (turn_ref,)
    return tuple(
        safe_ref
        for raw_ref in _source_identity_refs_from_source_refs((str(value or ""),))
        for safe_ref in (_safe_source_identity_ref(raw_ref),)
        if safe_ref
    )


def _safe_turn_ref(value: object) -> str:
    return _safe_exact_turn_ref(value) or ""


def _sanitized_source_ref_count(
    raw_source_refs: Sequence[str],
    *,
    safe_source_refs: Sequence[str],
) -> int | None:
    if raw_source_refs and tuple(raw_source_refs) != tuple(safe_source_refs):
        return len(tuple(dict.fromkeys(raw_source_refs)))
    return None


def _compact_rerank_signal_gap_samples(
    rerank_signal_gaps: Mapping[str, object],
    *,
    limit: int = 3,
) -> dict[str, object]:
    return {
        "positive_unselected_samples": _compact_rerank_gap_samples(
            rerank_signal_gaps.get("positive_unselected_samples"),
            limit=limit,
        ),
        "selected_without_positive_samples": _compact_rerank_gap_samples(
            rerank_signal_gaps.get("selected_without_positive_samples"),
            limit=limit,
        ),
        "selection_conflict_samples": _compact_rerank_selection_conflict_samples(
            rerank_signal_gaps.get("selection_conflict_samples"),
            limit=limit,
        ),
    }


def _compact_rerank_gap_samples(
    value: object,
    *,
    limit: int,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    for raw_sample in value:
        sample = _compact_rerank_gap_sample(_mapping(raw_sample))
        if not sample:
            continue
        samples.append(sample)
        if len(samples) >= limit:
            break
    return samples


def _compact_rerank_selection_conflict_samples(
    value: object,
    *,
    limit: int,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    for raw_sample in value:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in (
            "case_id",
            "group",
            "positive_unselected_candidate_count",
            "selected_without_positive_rerank_count",
        ):
            if key in sample:
                compact_value = _compact_sample_scalar(sample[key])
                if compact_value is not None:
                    compact[key] = compact_value
        signal_counts = _compact_count_mapping(
            sample.get("positive_unselected_signal_counts"),
            limit=6,
        )
        if signal_counts:
            compact["positive_unselected_signal_counts"] = signal_counts
        compact["positive_unselected_candidates"] = _compact_rerank_gap_samples(
            sample.get("positive_unselected_candidates"),
            limit=2,
        )
        compact["selected_without_positive_items"] = _compact_rerank_gap_samples(
            sample.get("selected_without_positive_items"),
            limit=2,
        )
        samples.append(compact)
        if len(samples) >= limit:
            break
    return samples


def _compact_rerank_gap_sample(sample: Mapping[str, object]) -> dict[str, object]:
    if not sample:
        return {}
    compact: dict[str, object] = {}
    scalar_keys = {
        "answerability_score",
        "benchmark_rerank_boosted",
        "case_id",
        "group",
        "item_id",
        "matched_retrieval_candidate",
        "positive_policy_score",
        "rank",
        "reason",
        "retrieval_order",
        "role",
        "score",
        "source_locality_score",
        "source_type",
    }
    sequence_keys = {
        "planner_reason_codes",
        "query_roles",
        "relation_category_hits",
        "selected_item_ids",
        "source_identity_refs",
    }
    mapping_keys = {
        "cap_signals",
        "penalty_signals",
        "policy_reasons",
        "top_signals",
    }
    for key in sorted(scalar_keys):
        if key in sample:
            compact_value = (
                _compact_item_id(sample[key])
                if key == "item_id"
                else _compact_sample_scalar(sample[key])
            )
            if compact_value is not None:
                compact[key] = compact_value
    for key in sorted(sequence_keys):
        if key not in sample:
            continue
        if key == "selected_item_ids":
            values = _compact_item_ids(sample.get(key), limit=6)
        elif key == "source_identity_refs":
            values = list(_compact_source_identity_refs(sample.get(key), limit=6))
        else:
            values = _compact_sample_values(sample.get(key), limit=6)
        if values:
            compact[key] = values
    for key in sorted(mapping_keys):
        payload = _compact_scalar_mapping(sample.get(key), limit=6)
        if payload:
            compact[key] = payload
    return compact


def _compact_scalar_mapping(value: object, *, limit: int = 6) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    compact: dict[str, object] = {}
    for key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
        if len(compact) >= limit:
            break
        if _compact_should_omit_key(_compact_key_name(key)):
            continue
        compact_key = _compact_sample_text(key)
        if not compact_key:
            continue
        if isinstance(raw_value, bool | int | float | str):
            compact_value = _compact_sample_scalar(raw_value)
            if compact_value is not None:
                compact[compact_key] = compact_value
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, str | bytes):
            values = _compact_sample_values(raw_value, limit=6)
            if values:
                compact[compact_key] = values
    return compact


def _compact_selected_evidence_weakness_samples(
    value: object,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    allowed_scalar_keys = {
        "case_id",
        "group",
        "item_id",
        "role",
        "query_role_count",
        "retrieval_order",
        "answerability_score",
        "source_locality_score",
        "broad_summary",
        "conflict_or_stale",
        "risk_reason_count",
        "planner_reason_count",
        "answerability_reason_count",
        "source_locality_reason_count",
        "retrieval_source_count",
        "source_type_count",
        "relation_category_count",
        "relation_category_hit_count",
        "source_type",
        "stale_reason",
        "conflict_reason",
    }
    allowed_sequence_keys = {
        "query_roles",
        "reasons",
        "source_refs",
        "risk_reason_codes",
        "planner_reason_codes",
        "answerability_reason_codes",
        "source_locality_reason_codes",
        "retrieval_sources",
        "source_types",
        "relation_categories",
        "relation_category_hits",
    }
    for raw_sample in value:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in sorted(allowed_scalar_keys):
            if key in sample:
                compact_value = (
                    _compact_item_id(sample[key])
                    if key == "item_id"
                    else _compact_sample_scalar(sample[key])
                )
                if compact_value is not None:
                    compact[key] = compact_value
        for key in sorted(allowed_sequence_keys):
            if key not in sample:
                continue
            if key == "source_refs":
                values = list(_compact_diagnostic_source_refs(sample.get(key), limit=6))
            else:
                values = _compact_sample_values(sample.get(key), limit=6)
            if values:
                compact[key] = values
        raw_source_refs = _str_tuple(sample.get("source_refs"))
        source_refs = tuple(compact.get("source_refs", ()))
        source_ref_count = _positive_int(sample.get("source_ref_count"))
        if (source_ref_count is None or source_ref_count == 0) and raw_source_refs:
            sanitized_source_ref_count = _sanitized_source_ref_count(
                raw_source_refs,
                safe_source_refs=source_refs,
            )
            if sanitized_source_ref_count is not None:
                source_ref_count = sanitized_source_ref_count
        if source_refs and source_ref_count is not None:
            compact["source_refs"] = list(source_refs)
        if source_ref_count is not None:
            compact["source_ref_count"] = source_ref_count
        if compact:
            samples.append(compact)
        if len(samples) >= limit:
            break
    return samples


def _compact_evidence_bundle_coverage(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    bundles = [
        _mapping(item.get("evidence_bundle"))
        for item in items
        if _mapping(item.get("evidence_bundle"))
    ]
    complete_count = sum(1 for bundle in bundles if bundle.get("bundle_complete") is True)
    missing_required_role_counts: dict[str, int] = defaultdict(int)
    for bundle in bundles:
        for role in _str_tuple(bundle.get("missing_required_roles")):
            missing_required_role_counts[role] += 1
    evidence_term_count = sum(
        _positive_int(bundle.get("evidence_term_count")) or 0 for bundle in bundles
    )
    covered_evidence_term_count = sum(
        len(_str_tuple(bundle.get("covered_evidence_terms"))) for bundle in bundles
    )
    incomplete_samples: list[dict[str, object]] = []
    for item in items:
        bundle = _mapping(item.get("evidence_bundle"))
        if not bundle or bundle.get("bundle_complete") is True:
            continue
        if len(incomplete_samples) >= 5:
            break
        quality = _mapping(item.get("retrieval_quality"))
        covered_evidence_refs = tuple(
            _compact_evidence_ref_list(
                quality.get("covered_evidence_terms"),
                item_limit=8,
            )
        ) or tuple(
            _compact_evidence_ref_list(
                bundle.get("covered_evidence_terms"),
                item_limit=8,
            )
        )
        missing_evidence_refs = tuple(
            _compact_evidence_ref_list(
                quality.get("missing_evidence_terms"),
                item_limit=8,
            )
        )
        evidence_refs = tuple(
            dict.fromkeys((*covered_evidence_refs, *missing_evidence_refs))
        )
        sample: dict[str, object] = {
            "case_id": _compact_sample_text(item.get("case_id")),
            "group": _compact_sample_text(item.get("group")),
            "item_count": _positive_int(bundle.get("item_count")) or 0,
            "evidence_term_recall": round(
                _metric_value(bundle, "evidence_term_recall"),
                4,
            ),
            "missing_evidence_terms": list(missing_evidence_refs),
            "missing_expected_terms": list(
                _compact_text_list(quality.get("missing_terms"), item_limit=8)
            ),
        }
        if evidence_refs:
            sample["evidence_refs"] = list(evidence_refs[:8])
        if covered_evidence_refs:
            sample["covered_evidence_refs"] = list(covered_evidence_refs)
        if missing_evidence_refs:
            sample["missing_evidence_refs"] = list(missing_evidence_refs)
        incomplete_samples.append(sample)
    return {
        "schema_version": "compact_evidence_bundle_coverage.v1",
        "bundle_count": len(bundles),
        "bundle_complete_count": complete_count,
        "bundle_incomplete_count": len(bundles) - complete_count,
        "bundle_completion_rate": _ratio(complete_count, len(bundles)),
        "avg_bundle_item_count": _avg(
            _metric_value(bundle, "item_count") for bundle in bundles
        ),
        "avg_evidence_term_recall": _avg(
            _metric_value(bundle, "evidence_term_recall") for bundle in bundles
        ),
        "avg_supporting_evidence_count": _avg(
            _metric_value(bundle, "supporting_evidence_count") for bundle in bundles
        ),
        "avg_query_support_term_recall": _avg(
            _metric_value(bundle, "query_support_term_recall") for bundle in bundles
        ),
        "evidence_term_count": evidence_term_count,
        "covered_evidence_term_count": covered_evidence_term_count,
        "missing_required_role_counts": _compact_count_mapping(
            missing_required_role_counts
        ),
        "incomplete_samples": incomplete_samples,
    }


def _numeric_summary(values: Iterable[float]) -> dict[str, object]:
    sequence = [float(value) for value in values]
    if not sequence:
        return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(sequence),
        "avg": round(sum(sequence) / len(sequence), 4),
        "min": round(min(sequence), 4),
        "max": round(max(sequence), 4),
    }


def _retrieval_source_counts(
    items: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        for result in _retrieval_results(item):
            for source in _result_retrieval_sources(result):
                counts[source] += 1
    return dict(sorted(counts.items()))


def _compact_count_mapping(value: object, *, limit: int = 12) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(value, Mapping):
        return counts
    for key, raw_count in value.items():
        count = _positive_int(raw_count)
        if count is None:
            continue
        counts[_compact_failure_text(key)] = count
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return dict(ranked[:limit])


def _retrieval_results(item: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    retrieval = _mapping(item.get("retrieval"))
    results = retrieval.get("results", ())
    if not isinstance(results, Sequence) or isinstance(results, str | bytes):
        return ()
    return tuple(result for result in results if isinstance(result, Mapping))


def _result_retrieval_sources(result: Mapping[str, object]) -> tuple[str, ...]:
    metadata = _mapping(result.get("metadata"))
    diagnostics = _mapping(metadata.get("diagnostics"))
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, str | bytes):
        return tuple(_compact_retrieval_source(source) for source in sources)
    return (_compact_retrieval_source(diagnostics.get("retrieval_source")),)


def _compact_retrieval_source(value: object) -> str:
    return _compact_sample_text(value or "unknown", limit=80) or "unknown"
