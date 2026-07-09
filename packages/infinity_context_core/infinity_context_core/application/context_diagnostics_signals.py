"""Score signal and provenance normalization for context diagnostics."""

from __future__ import annotations

from infinity_context_core.application.context_diagnostics_primitives import (
    _MAX_DIAGNOSTIC_KEY_CHARS,
    _MAX_DIAGNOSTIC_LIST_ITEMS,
    _as_dict,
    _safe_optional_text,
    safe_diagnostic_mapping,
)

_CONTEXT_REQUIREMENT_SCORE_SIGNAL_KEYS = (
    "context_requirement_boost",
    "context_requirement_matched_anchor_kind_count",
    "context_requirement_matched_modality_count",
    "context_requirement_matched_feature_count",
)
_DETERMINISTIC_RERANK_SCORE_SIGNAL_KEYS = (
    "book_author_preference_world_evidence",
    "cause_awareness_answer_evidence",
    "choice_reason_answer_evidence",
    "future_plan_timing_answer_evidence",
    "item_purchase_object_evidence",
    "symbol_importance_visual_evidence",
    "friend_place_shelter_anchor_evidence",
    "deterministic_rerank_boost",
    "deterministic_rerank_penalty",
    "deterministic_rerank_net_adjustment",
    "deterministic_rerank_source_count",
    "deterministic_rerank_strong_source_count",
    "deterministic_rerank_requirement_coverage",
    "deterministic_rerank_query_reason",
    "source_quote_answer_support",
    "source_quote_answer_boost",
    "source_quote_answer_relevance",
    "source_quote_answer_distinctive_hits",
)
_SOURCE_SIBLING_SCORE_SIGNAL_KEYS = (
    "exact_source_repair",
    "exact_source_repair_date_anchor",
    "source_sibling_answer_evidence",
    "source_sibling_dialogue_visual_reference",
    "source_sibling_group_level_seed",
    "source_sibling_visual_continuation",
    "source_sibling_score_cap_applied",
    "source_sibling_group_boost",
    "source_sibling_after_seed",
    "source_sibling_closeness",
    "source_sibling_turn_distance",
    "source_sibling_group_priority",
)
_CONTEXT_REQUIREMENT_PROVENANCE_LIST_KEYS = (
    "context_requirement_matched_anchor_kinds",
    "context_requirement_matched_modalities",
    "context_requirement_matched_evidence_features",
)
_DETERMINISTIC_RERANK_PROVENANCE_LIST_KEYS = (
    "deterministic_rerank_reasons",
)
_SOURCE_SIBLING_PROVENANCE_BOOL_KEYS = (
    "source_sibling_answer_evidence",
    "source_sibling_dialogue_visual_reference",
    "source_sibling_group_level_seed",
    "source_sibling_visual_continuation",
    "source_sibling_score_cap_applied",
)
_SOURCE_SIBLING_PROVENANCE_NUMBER_KEYS = (
    "source_sibling_turn_delta",
    "source_sibling_turn_distance",
    "source_sibling_group_priority",
)

def safe_score_signals(value: object) -> dict[str, object]:
    safe = safe_diagnostic_mapping(value)
    signals = {
        key: item
        for key, item in safe.items()
        if isinstance(item, int | float | str | bool) or item is None
    }
    signals.update(_safe_context_requirement_score_signals(value))
    signals.update(_safe_deterministic_rerank_score_signals(value))
    signals.update(_safe_source_sibling_score_signals(value))
    raw = _as_dict(value)
    raw_same_script_boost = raw.get("same_script_query_boost")
    if isinstance(raw_same_script_boost, int | float) and not isinstance(
        raw_same_script_boost,
        bool,
    ):
        signals["same_script_query_boost"] = round(max(0.0, raw_same_script_boost), 4)
    return signals

def _safe_context_requirement_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _CONTEXT_REQUIREMENT_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = max(0, raw_value)
        elif isinstance(raw_value, float):
            signals[key] = round(max(0.0, raw_value), 4)
    return signals


def _safe_deterministic_rerank_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _DETERMINISTIC_RERANK_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if key == "deterministic_rerank_query_reason":
            reason = _safe_optional_text(raw_value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
            if reason:
                signals[key] = reason
            continue
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = (
                raw_value
                if key == "deterministic_rerank_net_adjustment"
                else max(0, raw_value)
            )
        elif isinstance(raw_value, float):
            numeric = round(raw_value, 4)
            signals[key] = (
                numeric
                if key == "deterministic_rerank_net_adjustment"
                else round(max(0.0, numeric), 4)
            )
    return signals


def _safe_source_sibling_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _SOURCE_SIBLING_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = max(0, raw_value)
        elif isinstance(raw_value, float):
            signals[key] = round(max(0.0, raw_value), 4)
    return signals


def _safe_context_requirement_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    if raw.get("context_requirement_boost_applied") is True:
        provenance["context_requirement_boost_applied"] = True
    for key in _CONTEXT_REQUIREMENT_PROVENANCE_LIST_KEYS:
        safe_values = [
            safe_value
            for item in _safe_context_requirement_list(raw.get(key))
            if (safe_value := _safe_optional_text(item, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values or key in raw:
            provenance[key] = safe_values[:_MAX_DIAGNOSTIC_LIST_ITEMS]
    return provenance


def _safe_deterministic_rerank_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    if raw.get("deterministic_rerank_applied") is True:
        provenance["deterministic_rerank_applied"] = True
    if raw.get("deterministic_rerank_anchor_conflict") is True:
        provenance["deterministic_rerank_anchor_conflict"] = True
    for key in _DETERMINISTIC_RERANK_PROVENANCE_LIST_KEYS:
        safe_values = [
            safe_value
            for item in _safe_context_requirement_list(raw.get(key))
            if (safe_value := _safe_optional_text(item, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values or key in raw:
            provenance[key] = safe_values[:_MAX_DIAGNOSTIC_LIST_ITEMS]
    return provenance


def _safe_source_sibling_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    for key in _SOURCE_SIBLING_PROVENANCE_BOOL_KEYS:
        if raw.get(key) is True:
            provenance[key] = True
    for key in _SOURCE_SIBLING_PROVENANCE_NUMBER_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            provenance[key] = raw_value
        elif isinstance(raw_value, float):
            provenance[key] = round(raw_value, 4)
    return provenance


def _safe_context_requirement_list(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple):
        return tuple(value[:_MAX_DIAGNOSTIC_LIST_ITEMS])
    return ()
