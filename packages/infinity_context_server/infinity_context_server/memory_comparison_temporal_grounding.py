"""Temporal grounding diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

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
    memory_id as _memory_id,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    retrieval_metadata as _retrieval_metadata,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    retrieval_results as _retrieval_results,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_bundle_item as _source_refs_from_bundle_item,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_memory as _source_refs_from_memory,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)

_MAX_SAMPLES = 10
_MAX_SAMPLE_REFS = 5
_SESSION_RE = re.compile(r"\bsession[_ -]?\d+\b", re.IGNORECASE)
_TURN_RE = re.compile(r"\bD\d+:\d+\b")
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*,?\s+\d{4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_DATE_LABEL_RE = re.compile(r"\b(?:date|source_timestamp|observed_at):", re.IGNORECASE)
_RANGE_TEXT_RE = re.compile(
    r"\b(?:between|from|until|through|during|last|next|previous)\b",
    re.IGNORECASE,
)
_TEMPORAL_TEXT_KEYS = (
    "memory",
    "text",
    "content",
    "source_id",
    "source_external_id",
    "source_ref",
    "source_refs",
    "dedupe_key",
    "source_ref_dedupe_key",
)
_DATE_FIELD_KEYS = (
    "source_timestamp",
    "timestamp",
    "observed_at",
    "created_at",
    "updated_at",
    "source_date",
    "date",
    "event_time",
    "time",
)
_RANGE_FIELD_KEYS = (
    "time_start_ms",
    "time_end_ms",
    "valid_from",
    "valid_to",
    "date_range",
    "temporal_range",
    "start_at",
    "end_at",
    "starts_at",
    "ends_at",
)
_TEMPORAL_SURFACE_KEYS = (
    "has_duration_surface",
    "has_relative_time_surface",
    "has_explicit_time_surface",
    "has_explicit_time_content_surface",
    "has_temporal_sequence_surface",
)
_TEMPORAL_VALUE_TOKENS = {
    "duration",
    "explicit_time",
    "relative_time",
    "temporal_lookup",
    "temporal_sequence",
    "visual_temporal",
}


def temporal_grounding_table(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    temporal_cases = 0
    temporal_scored_cases = 0
    retrieval_candidate_count = 0
    selected_item_count = 0
    retrieval_session_boundary_count = 0
    retrieval_date_count = 0
    retrieval_range_count = 0
    retrieval_order_count = 0
    selected_session_boundary_count = 0
    selected_date_count = 0
    selected_range_count = 0
    selected_order_count = 0
    selected_ungrounded_count = 0
    gap_case_ids: set[str] = set()
    samples: list[dict[str, object]] = []

    for item in items:
        if not _has_temporal_intent(item):
            continue
        temporal_cases += 1
        if item.get("scored") is True:
            temporal_scored_cases += 1
        case_id = str(item.get("case_id") or "")

        for memory in _retrieval_results((item,)):
            retrieval_candidate_count += 1
            signals = _memory_grounding_signals(memory)
            retrieval_session_boundary_count += int(signals["session_boundary"])
            retrieval_date_count += int(signals["date"])
            retrieval_range_count += int(signals["range"])
            retrieval_order_count += int(signals["temporal_order"])

        for bundle_item in _bundle_items(_mapping(item.get("evidence_bundle"))):
            selected_item_count += 1
            signals = _bundle_item_grounding_signals(bundle_item)
            selected_session_boundary_count += int(signals["session_boundary"])
            selected_date_count += int(signals["date"])
            selected_range_count += int(signals["range"])
            selected_order_count += int(signals["temporal_order"])
            if signals["session_boundary"] or signals["date"] or signals["range"]:
                continue
            selected_ungrounded_count += 1
            if case_id:
                gap_case_ids.add(case_id)
            if len(samples) < _MAX_SAMPLES:
                samples.append(_grounding_gap_sample(item, bundle_item))

    return {
        "schema_version": "temporal_grounding.v1",
        "temporal_case_count": temporal_cases,
        "temporal_scored_case_count": temporal_scored_cases,
        "retrieval_candidate_count": retrieval_candidate_count,
        "retrieval_session_boundary_candidate_count": retrieval_session_boundary_count,
        "retrieval_date_grounded_candidate_count": retrieval_date_count,
        "retrieval_range_grounded_candidate_count": retrieval_range_count,
        "retrieval_temporal_order_candidate_count": retrieval_order_count,
        "selected_item_count": selected_item_count,
        "selected_session_boundary_item_count": selected_session_boundary_count,
        "selected_date_grounded_item_count": selected_date_count,
        "selected_range_grounded_item_count": selected_range_count,
        "selected_temporal_order_item_count": selected_order_count,
        "selected_ungrounded_temporal_item_count": selected_ungrounded_count,
        "selected_grounding_gap_case_count": len(gap_case_ids),
        "selected_grounding_gap_samples": samples,
    }


def _has_temporal_intent(item: Mapping[str, object]) -> bool:
    metadata = _retrieval_metadata(item)
    payloads = (
        _mapping(metadata.get("query_decomposition")),
        _mapping(metadata.get("query_expansion")),
        _mapping(metadata.get("benchmark_rerank")),
    )
    for payload in payloads:
        if _payload_has_temporal_intent(payload):
            return True
    for memory in _retrieval_results((item,)):
        if _candidate_has_temporal_features(_candidate_features(memory)):
            return True
    for bundle_item in _bundle_items(_mapping(item.get("evidence_bundle"))):
        if _values_have_temporal_text(
            (
                *_str_tuple(bundle_item.get("role")),
                *_str_tuple(bundle_item.get("roles")),
                *_str_tuple(bundle_item.get("query_roles")),
            )
        ):
            return True
    return False


def _payload_has_temporal_intent(payload: Mapping[str, object]) -> bool:
    query_profile = _mapping(payload.get("query_profile"))
    retrieval_intent = _mapping(payload.get("retrieval_intent"))
    query_plan = _mapping(payload.get("query_plan"))
    values = (
        *_str_tuple(query_profile.get("evidence_need")),
        *_str_tuple(query_profile.get("bundle_evidence_roles")),
        *_str_tuple(query_profile.get("relation_categories")),
        *_str_tuple(retrieval_intent.get("evidence_need")),
        *_str_tuple(retrieval_intent.get("bundle_evidence_roles")),
        *_relation_categories(retrieval_intent),
        *_str_tuple(query_plan.get("selected_roles")),
        *_str_tuple(query_plan.get("recommended_role_families")),
    )
    if _values_have_temporal_text(values):
        return True
    time_intent = _mapping(retrieval_intent.get("time_intent"))
    time_kind = str(time_intent.get("kind") or "").strip()
    return bool(time_kind and time_kind != "none")


def _relation_categories(intent: Mapping[str, object]) -> tuple[str, ...]:
    relations = _mapping(intent.get("relations"))
    return tuple(
        category
        for relation_intent in _sequence(relations.get("intents"))
        if (category := str(_mapping(relation_intent).get("category") or "").strip())
    )


def _candidate_has_temporal_features(features: Mapping[str, object]) -> bool:
    values = (
        *_str_tuple(features.get("query_roles")),
        *_str_tuple(features.get("relation_categories")),
        *_str_tuple(features.get("relation_category_hits")),
        str(features.get("time_intent_kind") or ""),
    )
    return _values_have_temporal_text(values) or any(
        features.get(key) is True for key in _TEMPORAL_SURFACE_KEYS
    )


def _values_have_temporal_text(values: Sequence[str]) -> bool:
    return any(
        "temporal" in (normalized := value.lower())
        or normalized in _TEMPORAL_VALUE_TOKENS
        for value in values
    )


def _memory_grounding_signals(memory: Mapping[str, object]) -> dict[str, bool]:
    diagnostics = _memory_diagnostics(memory)
    features = _candidate_features(memory)
    values = _grounding_values(memory, diagnostics, features)
    refs = _source_refs_from_memory(memory)
    text = " ".join((*values, *refs))
    date = _has_any_field(diagnostics, _DATE_FIELD_KEYS) or _has_date_text(text)
    range_grounded = (
        _has_any_field(diagnostics, _RANGE_FIELD_KEYS)
        or _has_range_text(text)
        or any(features.get(key) is True for key in ("has_duration_surface",))
    )
    return _grounding_signal_payload(text, date=date, range_grounded=range_grounded)


def _bundle_item_grounding_signals(item: Mapping[str, object]) -> dict[str, bool]:
    values = _grounding_values(item)
    refs = _source_refs_from_bundle_item(item)
    text = " ".join((*values, *refs))
    date = _has_any_field(item, _DATE_FIELD_KEYS) or _has_date_text(text)
    range_grounded = _has_any_field(item, _RANGE_FIELD_KEYS) or _has_range_text(text)
    return _grounding_signal_payload(text, date=date, range_grounded=range_grounded)


def _grounding_signal_payload(
    text: str,
    *,
    date: bool,
    range_grounded: bool,
) -> dict[str, bool]:
    session_boundary = bool(_SESSION_RE.search(text) or _TURN_RE.search(text))
    return {
        "session_boundary": session_boundary,
        "date": date,
        "range": range_grounded,
        "temporal_order": session_boundary,
    }


def _grounding_values(*payloads: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for payload in payloads:
        for key in (*_TEMPORAL_TEXT_KEYS, *_DATE_FIELD_KEYS, *_RANGE_FIELD_KEYS):
            value = payload.get(key)
            values.extend(_string_values(value))
    return tuple(values)


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Mapping):
        return tuple(
            str(nested).strip()
            for nested in value.values()
            if str(nested).strip()
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ()
    return (str(value).strip(),)


def _has_any_field(payload: Mapping[str, object], keys: Sequence[str]) -> bool:
    return any(bool(_string_values(payload.get(key))) for key in keys)


def _has_date_text(text: str) -> bool:
    return bool(_DATE_RE.search(text) or _DATE_LABEL_RE.search(text))


def _has_range_text(text: str) -> bool:
    return bool(_RANGE_TEXT_RE.search(text))


def _grounding_gap_sample(
    item: Mapping[str, object],
    bundle_item: Mapping[str, object],
) -> dict[str, object]:
    return {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": str(
            bundle_item.get("id")
            or bundle_item.get("item_id")
            or _memory_id(bundle_item)
        ),
        "role": str(bundle_item.get("role") or ""),
        "query_roles": list(_str_tuple(bundle_item.get("query_roles"))),
        "source_refs": list(_source_refs_from_bundle_item(bundle_item)[:_MAX_SAMPLE_REFS]),
        "missing_grounding": ["session_boundary", "date_or_range"],
    }
