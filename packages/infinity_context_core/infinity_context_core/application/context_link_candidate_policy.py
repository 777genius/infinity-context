"""Candidate scoring and metadata policy for context-link suggestions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from math import log

from infinity_context_core.application.context_temporal_hints import (
    TemporalHint,
    temporal_hint_windows,
)
from infinity_context_core.application.dto import (
    ContextLinkCandidate,
    SuggestContextLinksCommand,
)
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.application.semantic_dedupe import semantic_memory_terms
from infinity_context_core.application.sensitive_text import (
    contains_sensitive_text,
    redact_sensitive_text,
)
from infinity_context_core.domain.entities import MemoryChunk, SourceRef

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_MAX_CANDIDATE_PREVIEW = 220
_MAX_EVIDENCE_REFS = 5
_MAX_EVIDENCE_SOURCE_ID_CHARS = 160
_MAX_EVIDENCE_SOURCE_TYPE_CHARS = 80
_MAX_QUERY_TERMS = 64
_MAX_QUERY_TERM_CHARS = 80
_MAX_PROMPT_INJECTION_SIGNAL_CODES = 8
_MAX_TEXT_MATCH_SCORE = 125.0
_EXCLUSIVE_ANCHOR_MISMATCH_PENALTY = 32.0
_LINK_STOP_TERMS = {
    "about",
    "after",
    "again",
    "ago",
    "and",
    "api",
    "authorization",
    "above",
    "bearer",
    "credential",
    "credentials",
    "days",
    "developer",
    "earlier",
    "evening",
    "from",
    "hour",
    "hours",
    "ignore",
    "instruction",
    "instructions",
    "key",
    "last",
    "morning",
    "note",
    "password",
    "previous",
    "print",
    "prompt",
    "prior",
    "redacted",
    "reveal",
    "secret",
    "secrets",
    "screenshot",
    "system",
    "that",
    "the",
    "this",
    "today",
    "with",
    "week",
    "weeks",
    "what",
    "when",
    "where",
    "which",
    "afternoon",
    "yesterday",
    "вчера",
    "день",
    "дней",
    "дня",
    "игнорируй",
    "инструкции",
    "инструкций",
    "вечером",
    "днем",
    "днём",
    "ключ",
    "ключи",
    "когда",
    "назад",
    "неделю",
    "недели",
    "неделе",
    "прошлой",
    "прошлую",
    "про",
    "ранее",
    "скриншот",
    "секрет",
    "секреты",
    "системный",
    "сегодня",
    "токен",
    "токены",
    "что",
    "час",
    "часа",
    "часов",
    "утром",
}
_PROMPT_INJECTION_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?"
            r"(?:previous|prior|above|earlier|system|developer)?\s*instructions?\b|"
            r"\bигнорируй\s+(?:все\s+)?(?:предыдущие|прошлые|вышеуказанные|системные)?"
            r"\s*инструкци[июй]\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_disclosure",
        re.compile(
            r"\b(?:system|developer|hidden|internal)\s+(?:prompt|message|instructions?)\b|"
            r"\b(?:системн(?:ый|ые)|скрыт(?:ый|ые)|внутренн(?:ий|ие))\s+"
            r"(?:промпт|сообщени[ея]|инструкци[ия])\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"\b(?:reveal|print|show|dump|leak|exfiltrate|send)\b.{0,80}"
            r"\b(?:secret|secrets|api\s*key|token|password|credential)s?\b|"
            r"\b(?:покажи|выведи|раскрой|отправь)\b.{0,80}"
            r"\b(?:секрет|секреты|ключ|ключи|токен|токены|парол[ьи])\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_override",
        re.compile(
            r"\b(?:call|run|execute|use)\b.{0,80}\b(?:tool|function|shell|terminal)\b|"
            r"\b(?:вызови|запусти|используй)\b.{0,80}\b(?:tool|функци[юя]|терминал)\b",
            re.IGNORECASE,
        ),
    ),
)


def terms(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for raw in _TERM_PATTERN.findall(redact_sensitive_text(text).lower()):
        if len(seen) >= _MAX_QUERY_TERMS:
            break
        _add_term(seen, raw.strip("._-:/#"))
    for term in sorted(semantic_memory_terms(text)):
        if len(seen) >= _MAX_QUERY_TERMS:
            break
        _add_term(seen, term)
    return tuple(seen)


def excluded_terms(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    lowered = redact_sensitive_text(text).lower()
    for match in re.finditer(r"\b(?:not|exclude|excluding|не)\s+(?P<term>[\w.@:/#-]+)", lowered):
        raw = match.group("term")
        term = raw.strip("._-:/#")[:_MAX_QUERY_TERM_CHARS]
        if len(term) >= 3 and term not in _LINK_STOP_TERMS and term not in seen:
            seen[term] = None
            if len(seen) >= 12:
                break
    return tuple(seen)


def excluded_term_hits(
    candidate: ContextLinkCandidate,
    excluded_query_terms: tuple[str, ...],
) -> tuple[str, ...]:
    if not excluded_query_terms:
        return ()
    lowered = f"{candidate.label} {candidate.preview}".lower()
    return tuple(term for term in excluded_query_terms if term in lowered)


def temporal_hints(text: str) -> tuple[TemporalHint, ...]:
    return temporal_hint_windows(text)


def score_text_candidate(
    *,
    query_terms: tuple[str, ...],
    temporal_hints: tuple[TemporalHint, ...],
    target_text: str,
    updated_at: datetime,
    now: datetime,
    base: float,
) -> tuple[float, list[str], tuple[str, ...]]:
    score = base
    reasons: list[str] = []
    lowered = target_text.lower()
    target_terms = set(terms(target_text))
    raw_hits = tuple(
        term
        for term in query_terms
        if _is_raw_link_term(term) and (term in target_terms or _term_matches_text(term, lowered))
    )
    semantic_hits = tuple(
        term for term in query_terms if _is_semantic_link_term(term) and term in target_terms
    )
    hits = (*raw_hits, *semantic_hits)
    if hits:
        score += min(48.0, 8.0 * len(raw_hits))
        if semantic_hits and not raw_hits:
            score += min(14.0, 3.5 * len(semantic_hits))
        reasons.append("matching text")
    if _exclusive_anchor_mismatch(query_terms=query_terms, target_terms=target_terms):
        score -= _EXCLUSIVE_ANCHOR_MISMATCH_PENALTY
        reasons.append("different anchor identity")
    relative_age_hours = _relative_age_hours(updated_at, now)
    if _matches_temporal_hint(temporal_hints, relative_age_hours):
        score += 6 if hits else 22
        reasons.append("temporal intent match")
    age_hours = max(relative_age_hours, 0.0)
    if age_hours <= 1:
        score += 18
        reasons.append("recent activity")
    elif age_hours <= 24:
        score += 12
        reasons.append("recent activity")
    elif age_hours <= 24 * 7:
        score += max(2.0, 10.0 - log(age_hours + 1))
        reasons.append("near in time")
    if not reasons:
        reasons.append("recent context")
    return max(0.0, min(score, _MAX_TEXT_MATCH_SCORE)), reasons, hits


def _add_term(seen: dict[str, None], value: str) -> None:
    term = value.strip("._-:/#")[:_MAX_QUERY_TERM_CHARS]
    if len(term) >= 3 and term not in _LINK_STOP_TERMS and term not in seen:
        seen[term] = None


def _term_matches_text(term: str, lowered_text: str) -> bool:
    return _is_raw_link_term(term) and term in lowered_text


def _is_raw_link_term(term: str) -> bool:
    return ":" not in term


def _is_semantic_link_term(term: str) -> bool:
    return ":" in term


def _exclusive_anchor_mismatch(
    *,
    query_terms: tuple[str, ...],
    target_terms: set[str],
) -> bool:
    query_set = set(query_terms)
    for prefix in ("project:",):
        query_identities = _specific_anchor_identity_terms(query_set, prefix)
        target_identities = _specific_anchor_identity_terms(target_terms, prefix)
        if (
            query_identities
            and target_identities
            and not _anchor_identity_sets_overlap(query_identities, target_identities, prefix)
        ):
            return True
    return False


def _specific_anchor_identity_terms(values: set[str], prefix: str) -> set[str]:
    return {value for value in values if value.startswith(prefix)}


def _anchor_identity_sets_overlap(
    query_identities: set[str],
    target_identities: set[str],
    prefix: str,
) -> bool:
    query_values = {value.removeprefix(prefix).strip() for value in query_identities}
    target_values = {value.removeprefix(prefix).strip() for value in target_identities}
    query_multiword = {value for value in query_values if len(value.split()) > 1}
    target_multiword = {value for value in target_values if len(value.split()) > 1}
    if query_multiword and target_multiword:
        return any(
            _anchor_identity_value_contains(query_value, target_value)
            for query_value in query_multiword
            for target_value in target_values
        ) or any(
            _anchor_identity_value_contains(query_value, target_value)
            for query_value in query_values
            for target_value in target_multiword
        )
    if query_identities & target_identities:
        return True
    return any(
        _anchor_identity_value_contains(query_value, target_value)
        for query_value in query_values
        for target_value in target_values
    )


def _anchor_identity_value_contains(left: str, right: str) -> bool:
    left_terms = tuple(term for term in left.split() if term)
    right_terms = tuple(term for term in right.split() if term)
    if not left_terms or not right_terms:
        return False
    if left_terms == right_terms:
        return True
    if len(left_terms) == 1 and len(right_terms) > 1:
        return left_terms[0] == right_terms[0]
    if len(right_terms) == 1 and len(left_terms) > 1:
        return right_terms[0] == left_terms[0]
    return _ordered_subsequence(left_terms, right_terms) or _ordered_subsequence(
        right_terms,
        left_terms,
    )


def _ordered_subsequence(needle: tuple[str, ...], haystack: tuple[str, ...]) -> bool:
    if len(needle) > len(haystack):
        return False
    for start in range(0, len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def has_link_signal(*, matched_terms: tuple[str, ...], reasons: list[str]) -> bool:
    if matched_terms:
        return True
    return any(
        reason
        in {
            "same thread",
            "explicit project reference",
            "known project/tool reference",
            "event phrase",
            "person name",
            "temporal intent match",
        }
        for reason in reasons
    )


def prompt_injection_signal_codes(text: str) -> tuple[str, ...]:
    codes: list[str] = []
    if contains_sensitive_text(text):
        codes.append("credential_literal")
    for code, pattern in _PROMPT_INJECTION_SIGNAL_PATTERNS:
        if pattern.search(text) and code not in codes:
            codes.append(code)
        if len(codes) >= _MAX_PROMPT_INJECTION_SIGNAL_CODES:
            break
    return tuple(codes[:_MAX_PROMPT_INJECTION_SIGNAL_CODES])


def source_text_risk_metadata(text: str) -> dict[str, object]:
    signal_codes = prompt_injection_signal_codes(text)
    if not signal_codes:
        return {}
    return {
        "source_text_policy": "untrusted_evidence",
        "prompt_injection_signals_detected": True,
        "prompt_injection_signal_count": len(signal_codes),
        "prompt_injection_signal_codes": list(signal_codes),
        "review_gate_reason": "prompt_injection_evidence",
    }


def source_text_risk_metadata_from_mapping(metadata: Mapping[str, object]) -> dict[str, object]:
    if metadata.get("prompt_injection_signals_detected") is not True:
        return {}
    signal_codes = _safe_prompt_injection_signal_codes(
        metadata.get("prompt_injection_signal_codes")
    )
    signal_count = (
        len(signal_codes)
        if signal_codes
        else _safe_prompt_injection_signal_count(
            metadata.get("prompt_injection_signal_count"),
            fallback=0,
        )
    )
    result: dict[str, object] = {
        "source_text_policy": "untrusted_evidence",
        "prompt_injection_signals_detected": True,
        "prompt_injection_signal_count": signal_count,
        "review_gate_reason": "prompt_injection_evidence",
    }
    if signal_codes:
        result["prompt_injection_signal_codes"] = signal_codes
    return result


def candidate(
    *,
    target_type: str,
    target_id: str,
    label: str,
    preview: str,
    score: float,
    reasons: list[str],
    metadata: dict[str, object],
) -> ContextLinkCandidate:
    unique_reasons = tuple(dict.fromkeys(reasons))
    safe_metadata = dict(metadata)
    safe_metadata["reason_codes"] = _reason_codes(unique_reasons)
    return ContextLinkCandidate(
        target_type=target_type,
        target_id=target_id,
        label=label[:120],
        preview=preview[:_MAX_CANDIDATE_PREVIEW],
        score=round(score, 2),
        tier=_tier(score),
        reasons=unique_reasons,
        metadata=safe_metadata,
    )


def candidate_reason(candidate: ContextLinkCandidate) -> str:
    reason = "; ".join(candidate.reasons)
    return reason[:320] if reason else "related memory candidate"


def chunk_label(chunk: MemoryChunk) -> str:
    sequence = chunk.sequence
    kind = chunk.kind.value
    source = chunk.source_external_id.strip()
    suffix = f" - {source}" if source else ""
    if isinstance(sequence, int):
        return f"{kind} #{sequence}{suffix}"
    return f"{kind}{suffix}"


def episode_label(episode: object) -> str:
    source = str(getattr(episode, "source_external_id", "")).strip()
    source_type = str(getattr(episode, "source_type", "")).strip()
    return " - ".join(part for part in (source_type, source) if part) or "episode"


def confidence_for_candidate(candidate: ContextLinkCandidate) -> str:
    if candidate.tier == "likely":
        return "high"
    if candidate.tier == "possible":
        return "medium"
    return "low"


def evidence_summary(source_refs: tuple[SourceRef, ...]) -> dict[str, object]:
    refs = _unique_evidence_refs(source_refs)
    if not refs:
        return {}
    returned = refs[:_MAX_EVIDENCE_REFS]
    return {
        "evidence_source_ref_count": len(refs),
        "evidence_source_refs_returned": len(returned),
        "evidence_source_refs_truncated": len(refs) > len(returned),
        "evidence_source_types": _evidence_source_types(refs),
        "evidence_modalities": _evidence_modalities(refs),
        "evidence_has_page_ref": any(ref.page_number is not None for ref in refs),
        "evidence_has_bbox_ref": any(ref.bbox is not None for ref in refs),
        "evidence_has_time_range_ref": any(
            ref.time_start_ms is not None or ref.time_end_ms is not None for ref in refs
        ),
        "evidence_refs": [_evidence_ref_payload(ref) for ref in returned],
    }


def chunk_multimodal_evidence_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    refs = _metadata_source_refs(metadata)
    normalized_content_type = _safe_metadata_text_value(
        metadata.get("normalized_content_type"),
        limit=120,
    )
    evidence_kinds = _metadata_evidence_kinds(refs)
    modalities = _metadata_evidence_modalities(
        normalized_content_type=normalized_content_type,
        evidence_kinds=evidence_kinds,
        refs=refs,
    )
    if not normalized_content_type and not evidence_kinds and not modalities:
        return {}

    result: dict[str, object] = {}
    asset_id = _safe_metadata_text_value(metadata.get("asset_id"), limit=160)
    extraction_job_id = _safe_metadata_text_value(
        metadata.get("extraction_job_id"),
        limit=160,
    )
    parser_name = _safe_metadata_text_value(metadata.get("parser_name"), limit=120)
    if asset_id:
        result["evidence_asset_id"] = asset_id
    if extraction_job_id:
        result["evidence_extraction_job_id"] = extraction_job_id
    if normalized_content_type:
        result["evidence_normalized_content_type"] = normalized_content_type
    if parser_name:
        result["evidence_parser_name"] = parser_name
    if evidence_kinds:
        result["evidence_kinds"] = evidence_kinds
    if modalities:
        result["evidence_modalities"] = modalities
    if any(_metadata_ref_has_key(ref, "page_number") for ref in refs):
        result["evidence_has_page_ref"] = True
    if any(_metadata_ref_has_key(ref, "bbox") for ref in refs):
        result["evidence_has_bbox_ref"] = True
    if any(
        _metadata_ref_has_key(ref, "time_start_ms") or _metadata_ref_has_key(ref, "time_end_ms")
        for ref in refs
    ):
        result["evidence_has_time_range_ref"] = True
    return result


def multimodal_reason_hints(
    *,
    metadata: Mapping[str, object],
    matched_terms: tuple[str, ...],
) -> list[str]:
    if not matched_terms:
        return []
    refs = _metadata_source_refs(metadata)
    normalized_content_type = _safe_metadata_text_value(
        metadata.get("normalized_content_type"),
        limit=120,
    )
    evidence_kinds = _metadata_evidence_kinds(refs)
    modalities = set(
        _metadata_evidence_modalities(
            normalized_content_type=normalized_content_type,
            evidence_kinds=evidence_kinds,
            refs=refs,
        )
    )
    hints: list[str] = []
    if "transcript_segment" in evidence_kinds:
        hints.append("transcript match")
    if any(kind in evidence_kinds for kind in ("ocr_text", "image_metadata", "vision_region")):
        hints.append("visual text match")
    if any(kind in evidence_kinds for kind in ("video_keyframe", "video_frame_timeline")):
        hints.append("keyframe match")
    if "video" in modalities and "keyframe match" not in hints:
        hints.append("video evidence match")
    if "audio" in modalities and "transcript match" not in hints:
        hints.append("audio evidence match")
    return hints


def candidate_metadata(
    candidate: ContextLinkCandidate,
    diagnostics: dict[str, object],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "target_label": candidate.label,
        "target_preview": candidate.preview,
        "target_tier": candidate.tier,
        "resolver_version": str(diagnostics.get("resolver_version", "unknown")),
        "reason_codes": _reason_codes(candidate.reasons),
    }
    for key, value in (candidate.metadata or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[str(key)] = value
        elif isinstance(value, (list, tuple)):
            cleaned = _safe_metadata_list(str(key), value)
            if cleaned:
                metadata[str(key)] = cleaned
    return metadata


def is_same_source(
    key: tuple[str, str],
    command: SuggestContextLinksCommand,
) -> bool:
    return key[0] == command.source_type and key[1] == command.source_id


def _matches_temporal_hint(hints: tuple[TemporalHint, ...], age_hours: float) -> bool:
    return any(hint.min_hours <= age_hours <= hint.max_hours for hint in hints)


def _unique_evidence_refs(source_refs: tuple[SourceRef, ...]) -> tuple[SourceRef, ...]:
    refs: list[SourceRef] = []
    seen: set[tuple[object, ...]] = set()
    for ref in source_refs:
        key = (
            ref.source_type,
            ref.source_id,
            ref.chunk_id,
            ref.char_start,
            ref.char_end,
            ref.page_number,
            ref.time_start_ms,
            ref.time_end_ms,
            ref.bbox,
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return tuple(refs)


def _evidence_source_types(refs: tuple[SourceRef, ...]) -> list[str]:
    return sorted(
        {
            _safe_evidence_text(ref.source_type, limit=_MAX_EVIDENCE_SOURCE_TYPE_CHARS)
            for ref in refs
            if ref.source_type.strip()
        }
    )


def _evidence_modalities(refs: tuple[SourceRef, ...]) -> list[str]:
    modalities: set[str] = set()
    for ref in refs:
        lowered = f"{ref.source_type} {ref.source_id}".lower()
        if ref.page_number is not None or "document" in lowered or "pdf" in lowered:
            modalities.add("document")
        if ref.bbox is not None or any(
            marker in lowered
            for marker in ("image", "screenshot", ".png", ".jpg", ".jpeg", ".webp")
        ):
            modalities.add("image")
        if ref.time_start_ms is not None or ref.time_end_ms is not None:
            modalities.add("time_range")
        if "audio" in lowered or any(marker in lowered for marker in (".mp3", ".wav", ".m4a")):
            modalities.add("audio")
        if "video" in lowered or any(marker in lowered for marker in (".mp4", ".mov", ".webm")):
            modalities.add("video")
        if not modalities:
            modalities.add("text")
    return sorted(modalities)


def _evidence_ref_payload(ref: SourceRef) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_type": _safe_evidence_text(
            ref.source_type,
            limit=_MAX_EVIDENCE_SOURCE_TYPE_CHARS,
        ),
        "source_id": _safe_evidence_text(ref.source_id, limit=_MAX_EVIDENCE_SOURCE_ID_CHARS),
    }
    if ref.chunk_id:
        payload["chunk_id"] = _safe_evidence_text(ref.chunk_id, limit=160)
    if ref.char_start is not None:
        payload["char_start"] = ref.char_start
    if ref.char_end is not None:
        payload["char_end"] = ref.char_end
    if ref.page_number is not None:
        payload["page_number"] = ref.page_number
    if ref.time_start_ms is not None:
        payload["time_start_ms"] = ref.time_start_ms
    if ref.time_end_ms is not None:
        payload["time_end_ms"] = ref.time_end_ms
    if ref.bbox is not None:
        payload["bbox"] = [float(value) for value in ref.bbox]
    return payload


def _safe_metadata_list(key: str, value: object) -> list[object]:
    items = list(value)[: _MAX_EVIDENCE_REFS if key == "evidence_refs" else 50]
    if key == "evidence_refs":
        return [
            {
                str(item_key): item_value
                for item_key, item_value in item.items()
                if isinstance(item_value, (str, int, float, bool, list)) or item_value is None
            }
            for item in items
            if isinstance(item, dict)
        ]
    return [item for item in items if isinstance(item, (str, int, float, bool)) or item is None]


def _safe_evidence_text(value: str, *, limit: int) -> str:
    return redact_sensitive_text(value)[:limit]


def _metadata_source_refs(metadata: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    refs = metadata.get("source_refs")
    if not isinstance(refs, (list, tuple)):
        return ()
    return tuple(item for item in refs if isinstance(item, Mapping))


def _metadata_evidence_kinds(refs: tuple[Mapping[str, object], ...]) -> list[str]:
    kinds: list[str] = []
    for ref in refs:
        kind = _safe_metadata_text_value(ref.get("kind"), limit=80).lower().replace("-", "_")
        if kind and kind not in kinds:
            kinds.append(kind)
        if len(kinds) >= 40:
            break
    return kinds


def _metadata_evidence_modalities(
    *,
    normalized_content_type: str,
    evidence_kinds: list[str],
    refs: tuple[Mapping[str, object], ...],
) -> list[str]:
    modalities: set[str] = set()
    if normalized_content_type.startswith("image/"):
        modalities.add("image")
    elif normalized_content_type.startswith("audio/"):
        modalities.add("audio")
    elif normalized_content_type.startswith("video/"):
        modalities.add("video")
    elif normalized_content_type in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
    }:
        modalities.add("document")
    elif normalized_content_type.startswith("text/"):
        modalities.add("text")

    for kind in evidence_kinds:
        if kind in {"ocr_text", "image_metadata", "image_region", "vision_region"}:
            modalities.add("image")
        if kind in {"transcript", "transcript_segment", "speech_segment", "word"}:
            modalities.add("audio")
        if kind in {"video_keyframe", "video_frame", "video_frame_timeline"}:
            modalities.add("video")
    if any(_metadata_ref_has_key(ref, "page_number") for ref in refs):
        modalities.add("document")
    if any(_metadata_ref_has_key(ref, "bbox") for ref in refs):
        modalities.add("image")
    if any(
        _metadata_ref_has_key(ref, "time_start_ms") or _metadata_ref_has_key(ref, "time_end_ms")
        for ref in refs
    ):
        modalities.add("time_range")

    order = ("text", "document", "image", "audio", "video", "time_range")
    return [modality for modality in order if modality in modalities]


def _metadata_ref_has_key(ref: Mapping[str, object], key: str) -> bool:
    value = ref.get(key)
    return value is not None and value != ""


def _safe_metadata_text_value(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    return safe_metadata_text(str(value), limit=limit).strip()


def _reason_codes(reasons: tuple[str, ...]) -> list[str]:
    codes: list[str] = []
    for reason in reasons:
        if reason == "matching text":
            codes.append("text_match")
        elif reason == "recent activity":
            codes.append("recent_activity")
        elif reason == "near in time":
            codes.append("temporal_proximity")
        elif reason == "temporal intent match":
            codes.append("temporal_intent_match")
        elif reason == "same thread":
            codes.append("same_thread")
        elif reason.startswith("category:"):
            codes.append("shared_category")
        elif reason == "explicit project reference":
            codes.append("explicit_project_reference")
        elif reason == "known project/tool reference":
            codes.append("known_project_tool_reference")
        elif reason == "event phrase":
            codes.append("event_phrase")
        elif reason == "person name":
            codes.append("person_name")
        elif reason == "organization reference":
            codes.append("organization_reference")
        elif reason == "visual text match":
            codes.append("visual_text_match")
        elif reason == "transcript match":
            codes.append("transcript_match")
        elif reason == "keyframe match":
            codes.append("keyframe_match")
        elif reason == "video evidence match":
            codes.append("video_evidence_match")
        elif reason == "audio evidence match":
            codes.append("audio_evidence_match")
        elif reason == "exact duplicate":
            codes.append("exact_duplicate")
        elif reason == "equivalent text":
            codes.append("equivalent_text")
        elif reason == "semantic duplicate":
            codes.append("semantic_duplicate")
        elif reason == "different anchor identity":
            codes.append("exclusive_anchor_mismatch")
        elif reason == "excluded query term":
            codes.append("excluded_term_penalty")
        elif reason == "recent context":
            codes.append("recent_context")
        else:
            codes.append("rule_signal")
    return list(dict.fromkeys(codes))


def _safe_prompt_injection_signal_codes(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    codes: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        code = raw.strip().lower()
        if (
            1 <= len(code) <= _MAX_QUERY_TERM_CHARS
            and re.fullmatch(r"[a-z0-9_:-]+", code)
            and code not in codes
        ):
            codes.append(code)
        if len(codes) >= _MAX_PROMPT_INJECTION_SIGNAL_CODES:
            break
    return codes


def _safe_prompt_injection_signal_count(value: object, *, fallback: int) -> int:
    if isinstance(value, int) and value >= 0:
        return min(value, _MAX_PROMPT_INJECTION_SIGNAL_CODES)
    return min(max(fallback, 0), _MAX_PROMPT_INJECTION_SIGNAL_CODES)


def _tier(score: float) -> str:
    if score >= 75:
        return "likely"
    if score >= 55:
        return "possible"
    return "weak"


def _relative_age_hours(value: datetime, now: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - value).total_seconds() / 3600
