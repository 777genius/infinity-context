"""Temporal grounding diagnostics for memory-comparison benchmark reports."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_candidate_risks import (
    payload_has_broad_summary,
    payload_has_conflict_or_stale,
)
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
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_identity_ref as _safe_source_identity_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_turn_ref as _safe_turn_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_audit_gap_codes as _source_identity_audit_gap_codes,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)

_MAX_SAMPLES = 10
_MAX_SAMPLE_REFS = 5
_MAX_SOURCE_IDENTITY_GAP_CODES = 5
_SOURCE_IDENTITY_MISMATCH_GAP_CODES = frozenset(
    {
        "cross_session_source_identity",
        "cross_session_text_identity",
        "source_text_session_turn_mismatch",
        "source_text_turn_mismatch",
    }
)
_SESSION_RE = re.compile(r"\bsession[_ -]?\d+\b", re.IGNORECASE)
_TURN_RE = re.compile(r"\bD\d+:\d+\b")
_SOURCE_WINDOW_REF_RE = re.compile(
    r"(?:^|:)session_\d+:D\d+:\d+\b|^source_(?:session_)?turn_refs:",
    re.IGNORECASE,
)
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
_RELATIVE_DATE_TEXT_RE = re.compile(
    r"\b(?:today|tonight|yesterday|tomorrow|"
    r"this\s+(?:morning|afternoon|evening|weekend|week|month|quarter|year)|"
    r"(?:earlier|later)\s+(?:today|tonight|this\s+"
    r"(?:morning|afternoon|evening|weekend|week|month|quarter|year))|"
    r"(?:last|next|previous)\s+(?:morning|afternoon|evening|night|weekend|week|month|"
    r"quarter|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)|"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s+(?:minutes?|hours?|days?|weeks?|weekends?|months?|quarters?|years?)\s+ago"
    r")\b",
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
    retrieval_relative_date_count = 0
    retrieval_range_count = 0
    retrieval_order_count = 0
    selected_session_boundary_count = 0
    selected_date_count = 0
    selected_relative_date_count = 0
    selected_range_count = 0
    selected_order_count = 0
    selected_ungrounded_count = 0
    selected_source_window_item_count = 0
    selected_missing_source_window_count = 0
    gap_case_ids: set[str] = set()
    source_window_gap_case_ids: set[str] = set()
    issue_case_ids: set[str] = set()
    issue_reason_counts: Counter[str] = Counter()
    issue_item_count = 0
    missing_issue_count = 0
    weak_issue_count = 0
    conflict_issue_count = 0
    strong_grounding_count = 0
    samples: list[dict[str, object]] = []
    source_window_samples: list[dict[str, object]] = []
    issue_samples: list[dict[str, object]] = []

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
            retrieval_relative_date_count += int(signals["relative_date"])
            retrieval_range_count += int(signals["range"])
            retrieval_order_count += int(signals["temporal_order"])

        for bundle_item in _bundle_items(_mapping(item.get("evidence_bundle"))):
            selected_item_count += 1
            source_refs = _source_refs_from_bundle_item(bundle_item)
            has_source_window = _has_source_window_ref(source_refs)
            source_identity_gap_codes = _source_identity_gap_codes(bundle_item)
            selected_source_window_item_count += int(has_source_window)
            if not has_source_window:
                selected_missing_source_window_count += 1
                if case_id:
                    source_window_gap_case_ids.add(case_id)
                if len(source_window_samples) < _MAX_SAMPLES:
                    source_window_samples.append(
                        _source_window_gap_sample(item, bundle_item, source_refs)
                    )
            signals = _bundle_item_grounding_signals(bundle_item)
            selected_session_boundary_count += int(signals["session_boundary"])
            selected_date_count += int(signals["date"])
            selected_relative_date_count += int(signals["relative_date"])
            selected_range_count += int(signals["range"])
            selected_order_count += int(signals["temporal_order"])
            issue_reasons = _temporal_grounding_issue_reasons(
                bundle_item,
                signals=signals,
                has_source_window=has_source_window,
                source_identity_gap_codes=source_identity_gap_codes,
            )
            if issue_reasons:
                issue_item_count += 1
                issue_reason_counts.update(issue_reasons)
                missing_issue_count += int(
                    any(reason.startswith("missing_") for reason in issue_reasons)
                )
                weak_issue_count += int(
                    any(reason.startswith("weak_") for reason in issue_reasons)
                )
                conflict_issue_count += int(
                    "conflicting_or_stale" in issue_reasons
                )
                if case_id:
                    issue_case_ids.add(case_id)
                if len(issue_samples) < _MAX_SAMPLES:
                    issue_samples.append(
                        _temporal_grounding_issue_sample(
                            item,
                            bundle_item,
                            source_refs,
                            signals=signals,
                            has_source_window=has_source_window,
                            source_identity_gap_codes=source_identity_gap_codes,
                            reasons=issue_reasons,
                        )
                    )
            else:
                strong_grounding_count += 1
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
        "retrieval_relative_date_grounded_candidate_count": (
            retrieval_relative_date_count
        ),
        "retrieval_range_grounded_candidate_count": retrieval_range_count,
        "retrieval_temporal_order_candidate_count": retrieval_order_count,
        "selected_item_count": selected_item_count,
        "selected_session_boundary_item_count": selected_session_boundary_count,
        "selected_date_grounded_item_count": selected_date_count,
        "selected_relative_date_grounded_item_count": selected_relative_date_count,
        "selected_range_grounded_item_count": selected_range_count,
        "selected_temporal_order_item_count": selected_order_count,
        "selected_ungrounded_temporal_item_count": selected_ungrounded_count,
        "selected_grounding_gap_case_count": len(gap_case_ids),
        "selected_grounding_gap_samples": samples,
        "selected_source_window_item_count": selected_source_window_item_count,
        "selected_missing_source_window_item_count": selected_missing_source_window_count,
        "selected_source_window_gap_case_count": len(source_window_gap_case_ids),
        "selected_source_window_gap_samples": source_window_samples,
        "selected_strong_temporal_grounding_item_count": strong_grounding_count,
        "selected_temporal_grounding_issue_item_count": issue_item_count,
        "selected_temporal_grounding_issue_case_count": len(issue_case_ids),
        "selected_missing_temporal_grounding_issue_item_count": missing_issue_count,
        "selected_weak_temporal_grounding_issue_item_count": weak_issue_count,
        "selected_conflicting_temporal_grounding_issue_item_count": conflict_issue_count,
        "selected_temporal_grounding_issue_reason_counts": dict(
            sorted(issue_reason_counts.items())
        ),
        "selected_temporal_grounding_issue_sample_limit": _MAX_SAMPLES,
        "selected_temporal_grounding_issue_sample_count": len(issue_samples),
        "selected_temporal_grounding_issue_sample_omitted_count": max(
            0,
            issue_item_count - len(issue_samples),
        ),
        "selected_temporal_grounding_issue_samples": issue_samples,
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
    relative_date = _has_relative_date_text(text)
    range_grounded = (
        _has_any_field(diagnostics, _RANGE_FIELD_KEYS)
        or _has_range_text(text)
        or relative_date
        or any(features.get(key) is True for key in ("has_duration_surface",))
    )
    return _grounding_signal_payload(
        text,
        date=date,
        relative_date=relative_date,
        range_grounded=range_grounded,
    )


def _bundle_item_grounding_signals(item: Mapping[str, object]) -> dict[str, bool]:
    values = _grounding_values(item)
    refs = _source_refs_from_bundle_item(item)
    text = " ".join((*values, *refs))
    date = _has_any_field(item, _DATE_FIELD_KEYS) or _has_date_text(text)
    relative_date = _has_relative_date_text(text)
    range_grounded = (
        _has_any_field(item, _RANGE_FIELD_KEYS)
        or _has_range_text(text)
        or relative_date
    )
    return _grounding_signal_payload(
        text,
        date=date,
        relative_date=relative_date,
        range_grounded=range_grounded,
    )


def _temporal_grounding_issue_reasons(
    item: Mapping[str, object],
    *,
    signals: Mapping[str, bool],
    has_source_window: bool,
    source_identity_gap_codes: Sequence[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    has_session_boundary = bool(signals.get("session_boundary"))
    has_date_or_range = bool(signals.get("date") or signals.get("range"))
    if _has_source_identity_mismatch(source_identity_gap_codes):
        reasons.append("source_identity_mismatch")
    if not has_source_window:
        reasons.append("missing_source_window")
    if not has_session_boundary:
        reasons.append("missing_session_boundary")
    if not has_date_or_range:
        reasons.append("missing_date_or_range")
    if not has_session_boundary and not has_date_or_range:
        reasons.append("missing_temporal_grounding")
    if has_source_window and not has_date_or_range:
        reasons.append("weak_source_window_without_date_or_range")
    if has_session_boundary and not has_date_or_range:
        reasons.append("weak_session_boundary_without_date_or_range")
    if has_date_or_range and not has_session_boundary:
        reasons.append("weak_date_or_range_without_session_boundary")
    if _bundle_item_has_conflict_or_stale(item):
        reasons.append("conflicting_or_stale")
    if _bundle_item_has_broad_summary(item):
        reasons.append("weak_broad_summary")
    return tuple(reasons)


def _bundle_item_has_conflict_or_stale(item: Mapping[str, object]) -> bool:
    features = _candidate_features(item)
    diagnostics = _memory_diagnostics(item)
    reason_codes = (
        *_str_tuple(item.get("reason_codes")),
        *_str_tuple(item.get("answerability_reason_codes")),
        *_str_tuple(item.get("source_locality_reason_codes")),
        *_str_tuple(diagnostics.get("reason_codes")),
    )
    return (
        item.get("conflict_or_stale") is True
        or payload_has_conflict_or_stale(item, features)
        or bool(item.get("stale_reason"))
        or bool(_positive_int(item.get("conflict_count")))
        or any(
            "conflict_or_stale" in reason or "stale" in reason
            for reason in reason_codes
        )
    )


def _bundle_item_has_broad_summary(item: Mapping[str, object]) -> bool:
    features = _candidate_features(item)
    reason_codes = (
        *_str_tuple(item.get("reason_codes")),
        *_str_tuple(item.get("source_locality_reason_codes")),
    )
    return (
        item.get("broad_summary") is True
        or payload_has_broad_summary(item, features)
        or any("broad_summary" in reason for reason in reason_codes)
    )


def _source_identity_gap_codes(item: Mapping[str, object]) -> tuple[str, ...]:
    source_refs = _str_tuple(item.get("source_refs"))
    if not source_refs:
        source_refs = _source_refs_from_bundle_item(item)
    return _source_identity_audit_gap_codes(
        source_refs=source_refs,
        text=_bundle_item_identity_text(item),
    )


def _bundle_item_identity_text(item: Mapping[str, object]) -> str:
    return " ".join(
        value
        for key in ("memory", "text", "content")
        for value in _string_values(item.get(key))
    )


def _has_source_identity_mismatch(gap_codes: Sequence[str]) -> bool:
    return any(code in _SOURCE_IDENTITY_MISMATCH_GAP_CODES for code in gap_codes)


def _grounding_signal_payload(
    text: str,
    *,
    date: bool,
    relative_date: bool,
    range_grounded: bool,
) -> dict[str, bool]:
    session_boundary = bool(_SESSION_RE.search(text) or _TURN_RE.search(text))
    return {
        "session_boundary": session_boundary,
        "date": date,
        "relative_date": relative_date,
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


def _has_relative_date_text(text: str) -> bool:
    return bool(_RELATIVE_DATE_TEXT_RE.search(text))


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _grounding_gap_sample(
    item: Mapping[str, object],
    bundle_item: Mapping[str, object],
) -> dict[str, object]:
    source_refs = _source_refs_from_bundle_item(bundle_item)
    safe_source_refs = _safe_sample_source_refs(source_refs)
    sample = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": str(
            bundle_item.get("id")
            or bundle_item.get("item_id")
            or _memory_id(bundle_item)
        ),
        "role": str(bundle_item.get("role") or ""),
        "query_roles": list(_str_tuple(bundle_item.get("query_roles"))),
        "source_refs": list(safe_source_refs),
        "missing_grounding": ["session_boundary", "date_or_range"],
    }
    _add_source_ref_count_when_sanitized(
        sample,
        source_refs=source_refs,
        safe_source_refs=safe_source_refs,
    )
    return sample


def _has_source_window_ref(source_refs: Sequence[str]) -> bool:
    return any(
        _safe_turn_ref(ref) is not None
        or _SOURCE_WINDOW_REF_RE.search(ref)
        or _source_identity_refs_from_source_refs(
            (ref,),
            include_exact_turn_refs=True,
        )
        for ref in source_refs
    )


def _source_window_gap_sample(
    item: Mapping[str, object],
    bundle_item: Mapping[str, object],
    source_refs: Sequence[str],
) -> dict[str, object]:
    sample = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": str(
            bundle_item.get("id")
            or bundle_item.get("item_id")
            or _memory_id(bundle_item)
        ),
        "role": str(bundle_item.get("role") or ""),
        "query_roles": list(_str_tuple(bundle_item.get("query_roles"))),
        "source_refs": list(_safe_sample_source_refs(source_refs)),
        "missing_source_window": True,
    }
    if source_refs and not sample["source_refs"]:
        sample["source_ref_count"] = len(source_refs)
    else:
        _add_source_ref_count_when_sanitized(
            sample,
            source_refs=source_refs,
            safe_source_refs=tuple(sample["source_refs"]),
        )
    return sample


def _temporal_grounding_issue_sample(
    item: Mapping[str, object],
    bundle_item: Mapping[str, object],
    source_refs: Sequence[str],
    *,
    signals: Mapping[str, bool],
    has_source_window: bool,
    source_identity_gap_codes: Sequence[str],
    reasons: Sequence[str],
) -> dict[str, object]:
    safe_source_refs = _safe_sample_source_refs(source_refs)
    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": str(
            bundle_item.get("id")
            or bundle_item.get("item_id")
            or _memory_id(bundle_item)
        ),
        "role": str(bundle_item.get("role") or ""),
        "query_roles": list(_str_tuple(bundle_item.get("query_roles"))),
        "source_refs": list(safe_source_refs),
        "issue_reasons": list(reasons),
        "grounding_signals": {
            "source_window": has_source_window,
            "session_boundary": bool(signals.get("session_boundary")),
            "date_or_range": bool(signals.get("date") or signals.get("range")),
            "temporal_order": bool(signals.get("temporal_order")),
        },
    }
    _add_source_ref_count_when_sanitized(
        sample,
        source_refs=source_refs,
        safe_source_refs=safe_source_refs,
    )
    if signals.get("relative_date"):
        sample["grounding_signals"]["relative_date"] = True
    if _has_source_identity_mismatch(source_identity_gap_codes):
        sample["source_identity_gap_codes"] = list(
            source_identity_gap_codes[:_MAX_SOURCE_IDENTITY_GAP_CODES]
        )
    return sample


def _safe_sample_source_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in source_refs:
        for ref in _safe_sample_source_refs_for_value(raw_ref):
            if ref not in refs:
                refs.append(ref)
            if len(refs) >= _MAX_SAMPLE_REFS:
                return tuple(refs)
    return tuple(refs)


def _safe_sample_source_refs_for_value(value: object) -> tuple[str, ...]:
    safe_ref = _safe_source_identity_ref(value)
    if safe_ref:
        return (safe_ref,)
    ref = str(value or "").strip()
    if not ref:
        return ()
    turn_ref = _safe_turn_ref(ref)
    if turn_ref:
        return (turn_ref,)
    return tuple(
        safe_ref
        for raw_ref in _source_identity_refs_from_source_refs((ref,))
        for safe_ref in (_safe_source_identity_ref(raw_ref),)
        if safe_ref
    )


def _add_source_ref_count_when_sanitized(
    sample: dict[str, object],
    *,
    source_refs: Sequence[str],
    safe_source_refs: Sequence[str],
) -> None:
    if source_refs and tuple(source_refs) != tuple(safe_source_refs):
        sample["source_ref_count"] = len(source_refs)
