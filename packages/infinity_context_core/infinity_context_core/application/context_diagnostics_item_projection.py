"""Item-level context diagnostics projection and merge policy."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from infinity_context_core.application.context_diagnostics_primitives import (
    _MAX_DIAGNOSTIC_KEY_CHARS,
    _MAX_DIAGNOSTIC_LIST_ITEMS,
    _MAX_DIAGNOSTIC_STRING_CHARS,
    _MAX_RANKING_REASON_CHARS,
    _MAX_RETRIEVAL_SOURCE_CANDIDATES,
    _MAX_RETRIEVAL_SOURCES,
    _as_dict,
    _optional_non_negative_int,
    _ordered_unique,
    _safe_optional_text,
    _safe_retrieval_source,
    safe_diagnostic_mapping,
)
from infinity_context_core.application.context_diagnostics_signals import (
    _safe_context_requirement_provenance,
    _safe_deterministic_rerank_provenance,
    safe_score_signals,
)
from infinity_context_core.application.context_diagnostics_sources import (
    _prioritized_retrieval_sources,
    diagnostic_retrieval_sources,
    ranking_reason_for,
)
from infinity_context_core.application.context_item_evidence import (
    with_context_item_evidence_diagnostics,
)
from infinity_context_core.application.dto import ContextItem

_SAFE_RECALL_DIAGNOSTIC_KEYS = (
    "provider",
    "adapter_name",
    "projection_version",
    "collection",
    "dataset_id",
)
_SAFE_CONTEXT_LINK_DIAGNOSTIC_KEYS = (
    "context_link_id",
    "context_link_relation_type",
    "context_link_confidence",
)
_SAFE_REVIEW_TEXT_DIAGNOSTIC_KEYS = (
    "review_recommended_action",
    "review_recommended_resolution_action",
    "review_default_resolution",
    "review_risk",
    "review_recommendation_confidence",
    "review_policy_version",
)
_SAFE_REVIEW_BOOL_DIAGNOSTIC_KEYS = (
    "review_requires_review",
    "review_auto_merge_eligible",
)
_SAFE_REVIEW_LIST_DIAGNOSTIC_KEYS = (
    "review_recommendation_reason_codes",
)
_SAFE_ANCHOR_TEXT_DIAGNOSTIC_KEYS = (
    "anchor_kind",
    "normalized_key",
    "identity_scope",
    "identity_key",
    "canonical_key",
    "person_canonical_key",
    "project_canonical_key",
    "organization_canonical_key",
    "event_type",
    "event_type_canonical",
    "event_participant_label",
    "event_participant_relation",
    "event_participant_canonical_key",
    "event_project_label",
    "event_project_relation",
    "event_project_canonical_key",
    "event_temporal_phrase",
    "event_temporal_hint_code",
    "event_temporal_quantity",
    "event_temporal_unit",
)
_SAFE_ANCHOR_LIST_DIAGNOSTIC_KEYS = (
    "event_identity_terms",
    "alias_identity_terms",
)

def normalize_context_item_diagnostics(item: ContextItem) -> ContextItem:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    return replace(
        item,
        diagnostics=with_context_item_evidence_diagnostics(item, diagnostics),
    )


def normalize_context_diagnostics(diagnostics: object) -> dict[str, object]:
    raw = _as_dict(diagnostics)
    listed_retrieval_sources = diagnostic_retrieval_sources(
        raw,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    selected_source = _safe_retrieval_source(raw.get("retrieval_source"))
    all_retrieval_sources = (
        _ordered_unique(
            (selected_source, *listed_retrieval_sources),
            limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
        )
        if selected_source
        else listed_retrieval_sources
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized = safe_diagnostic_mapping(raw)
    normalized.update(_safe_query_snippet_diagnostics(raw))
    normalized.update(_safe_recall_diagnostics(raw))
    normalized.update(_safe_context_link_diagnostics(raw))
    normalized.update(_safe_review_diagnostics(raw))
    normalized.update(_safe_anchor_diagnostics(raw))
    normalized["retrieval_sources"] = list(retrieval_sources)
    normalized["retrieval_sources_total"] = len(all_retrieval_sources)
    normalized["retrieval_sources_returned"] = len(retrieval_sources)
    normalized["retrieval_sources_truncated"] = len(all_retrieval_sources) > len(retrieval_sources)
    if retrieval_sources and not selected_source:
        selected_source = retrieval_sources[0]
    if selected_source:
        normalized["retrieval_source"] = selected_source
    else:
        normalized.pop("retrieval_source", None)
    ranking_reason = _safe_optional_text(raw.get("ranking_reason"), limit=_MAX_RANKING_REASON_CHARS)
    normalized["ranking_reason"] = ranking_reason or ranking_reason_for(retrieval_sources)
    normalized["score_signals"] = safe_score_signals(raw.get("score_signals"))
    provenance = safe_diagnostic_mapping(raw.get("provenance"))
    provenance.update(_safe_context_requirement_provenance(raw.get("provenance")))
    provenance.update(_safe_deterministic_rerank_provenance(raw.get("provenance")))
    if retrieval_sources:
        provenance["retrieval_sources"] = list(retrieval_sources)
    normalized["provenance"] = provenance
    return normalized

def merge_context_diagnostics(
    *,
    primary: object,
    secondary: object,
    retrieval_sources: tuple[str, ...],
    source_ref_count: int,
    primary_score: float,
    secondary_score: float,
    hybrid_boost: float,
) -> dict[str, object]:
    primary_raw = _as_dict(primary)
    secondary_raw = _as_dict(secondary)
    merged = safe_diagnostic_mapping({**secondary_raw, **primary_raw})
    merged.update(_safe_recall_diagnostics(secondary_raw))
    merged.update(_safe_recall_diagnostics(primary_raw))
    merged.update(_safe_context_link_diagnostics(secondary_raw))
    merged.update(_safe_context_link_diagnostics(primary_raw))
    prioritized_sources = _prioritized_retrieval_sources(retrieval_sources)
    selected_source = prioritized_sources[0] if prioritized_sources else None
    if selected_source:
        merged["retrieval_source"] = selected_source
    merged["retrieval_sources"] = list(prioritized_sources)
    merged["merged_candidate_count"] = _candidate_count(primary_raw) + _candidate_count(
        secondary_raw
    )
    merged["ranking_reason"] = ranking_reason_for(prioritized_sources)
    primary_score_signals = safe_score_signals(primary_raw.get("score_signals"))
    secondary_score_signals = safe_score_signals(secondary_raw.get("score_signals"))
    merged["score_signals"] = {
        "dedupe_primary_score": round(primary_score, 4),
        "dedupe_secondary_score": round(secondary_score, 4),
        "hybrid_source_count": len(prioritized_sources),
        "hybrid_boost": round(hybrid_boost, 4),
        "source_ref_count": source_ref_count,
        **secondary_score_signals,
        **primary_score_signals,
    }
    _preserve_positive_score_signals(
        merged["score_signals"],
        primary_score_signals,
        secondary_score_signals,
        keys=(
            "source_sibling_dialogue_visual_reference",
            "source_sibling_group_level_seed",
            "source_sibling_visual_continuation",
        ),
    )
    primary_provenance = safe_diagnostic_mapping(primary_raw.get("provenance"))
    secondary_provenance = safe_diagnostic_mapping(secondary_raw.get("provenance"))
    merged["provenance"] = {
        **secondary_provenance,
        **primary_provenance,
        "retrieval_sources": list(prioritized_sources),
        "source_ref_count": source_ref_count,
        "selected_retrieval_source": selected_source or "unknown",
    }
    _preserve_positive_provenance_flags(
        merged["provenance"],
        primary_provenance,
        secondary_provenance,
        keys=(
            "source_sibling_dialogue_visual_reference",
            "source_sibling_group_level_seed",
            "source_sibling_visual_continuation",
        ),
    )
    return normalize_context_diagnostics(merged)

def _preserve_positive_score_signals(
    merged: dict[str, object],
    primary: dict[str, object],
    secondary: dict[str, object],
    *,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if _positive_numeric_signal(primary.get(key)) or _positive_numeric_signal(
            secondary.get(key)
        ):
            merged[key] = 1


def _preserve_positive_provenance_flags(
    merged: dict[str, object],
    primary: dict[str, object],
    secondary: dict[str, object],
    *,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if primary.get(key) is True or secondary.get(key) is True:
            merged[key] = True


def _positive_numeric_signal(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return value > 0
    return False

def _safe_query_snippet_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    snippet = _safe_optional_text(
        raw.get("query_snippet"),
        limit=_MAX_DIAGNOSTIC_STRING_CHARS,
    )
    if not snippet:
        return {}
    diagnostics: dict[str, object] = {"query_snippet": snippet}
    for key in ("query_snippet_char_start", "query_snippet_char_end"):
        value = _optional_non_negative_int(raw.get(key))
        if value is not None:
            diagnostics[key] = value
    unique_hits = _optional_non_negative_int(raw.get("query_snippet_unique_term_hits"))
    if unique_hits is not None:
        diagnostics["query_snippet_unique_term_hits"] = unique_hits
    terms = raw.get("query_snippet_matched_terms")
    if isinstance(terms, list | tuple):
        diagnostics["query_snippet_matched_terms"] = [
            term
            for raw_term in terms[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (term := _safe_optional_text(raw_term, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
    return diagnostics


def _safe_recall_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_RECALL_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    return diagnostics


def _safe_context_link_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_CONTEXT_LINK_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    return diagnostics


def _safe_review_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_REVIEW_TEXT_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    for key in _SAFE_REVIEW_BOOL_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            diagnostics[key] = value
    for key in _SAFE_REVIEW_LIST_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    options = raw.get("review_resolution_options")
    if isinstance(options, list | tuple):
        safe_options: list[dict[str, str]] = []
        for option in options[:_MAX_DIAGNOSTIC_LIST_ITEMS]:
            if not isinstance(option, dict):
                continue
            safe_option = {
                key: value
                for key, value in (
                    ("id", _safe_optional_text(option.get("id"), limit=_MAX_DIAGNOSTIC_KEY_CHARS)),
                    (
                        "review_action",
                        _safe_optional_text(
                            option.get("review_action"),
                            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
                        ),
                    ),
                    (
                        "effect",
                        _safe_optional_text(
                            option.get("effect"),
                            limit=_MAX_DIAGNOSTIC_STRING_CHARS,
                        ),
                    ),
                    (
                        "availability",
                        _safe_optional_text(
                            option.get("availability"),
                            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
                        ),
                    ),
                )
                if value
            }
            if safe_option:
                safe_options.append(safe_option)
        if safe_options:
            diagnostics["review_resolution_options"] = safe_options
    return diagnostics


def _safe_anchor_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_ANCHOR_TEXT_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    for key in _SAFE_ANCHOR_LIST_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    profile = safe_diagnostic_mapping(raw.get("anchor_identity_profile"))
    if profile:
        diagnostics["anchor_identity_profile"] = profile
    identity_metadata = safe_diagnostic_mapping(raw.get("identity_metadata"))
    if identity_metadata:
        diagnostics["identity_metadata"] = identity_metadata
    return diagnostics

def _candidate_count(diagnostics: dict[str, Any]) -> int:
    value = diagnostics.get("merged_candidate_count")
    return value if isinstance(value, int) and value > 0 else 1
