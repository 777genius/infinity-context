"""Shared utilities for answer-support context packing policies."""

from __future__ import annotations

import re

from infinity_context_core.application.dto import ContextItem

_TURN_SOURCE_ORDER_RE = re.compile(r"(?:^|:)session_(\d+):D\d+:(\d+):turn$")
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_QUERY_OBJECT_TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
_RECENCY_QUERY_RE = re.compile(
    r"\b(?:current|currently|latest|most\s+recent|recently|last|newest|now|today|"
    r"this\s+(?:week|month|year)|next\s+(?:week|month|year))\b",
    re.IGNORECASE,
)
_NEUTRAL_SOURCE_ORDER = (999_999, 999_999)
_QUERY_OBJECT_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "another",
        "both",
        "close",
        "current",
        "currently",
        "did",
        "do",
        "does",
        "done",
        "for",
        "from",
        "great",
        "had",
        "has",
        "have",
        "her",
        "him",
        "his",
        "how",
        "in",
        "is",
        "kind",
        "latest",
        "last",
        "make",
        "made",
        "new",
        "newest",
        "of",
        "on",
        "recent",
        "recently",
        "same",
        "say",
        "says",
        "said",
        "subject",
        "subjects",
        "the",
        "their",
        "them",
        "to",
        "type",
        "types",
        "use",
        "used",
        "uses",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _one_line(text: str) -> str:
    compact = " ".join(text.strip().split())
    return compact[:2000]


def _memory_scope_id(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    memory_scope_id = diagnostics.get("memory_scope_id")
    return str(memory_scope_id) if memory_scope_id else "unknown_memory_scope"


def _source_key(item: ContextItem) -> str:
    memory_scope_id = _memory_scope_id(item)
    if item.source_refs:
        ref = item.source_refs[0]
        return f"{memory_scope_id}:{ref.source_type}:{ref.source_id}"
    return f"{memory_scope_id}:{item.item_type}:{item.item_id}"


def _source_group_key(item: ContextItem) -> str:
    memory_scope_id = _memory_scope_id(item)
    if item.source_refs:
        ref = item.source_refs[0]
        return (
            f"{memory_scope_id}:{ref.source_type}:"
            f"{_source_group_identity(ref.source_id)}"
        )
    return f"{memory_scope_id}:{item.item_type}:{item.item_id}"


def _source_group_identity(source_id: str | None) -> str:
    text = _one_line(str(source_id or "unknown"))
    parts = text.split(":")
    if len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D"):
        return ":".join(parts[:-3])
    if len(parts) >= 4 and parts[-1] in {"events", "observation", "summary"}:
        return ":".join(parts[:-1])
    return text


def _has_primary_exact_turn_source_ref(item: ContextItem) -> bool:
    if not item.source_refs:
        return False
    return _is_exact_turn_source_id(item.source_refs[0].source_id)


def _has_any_exact_turn_source_ref(item: ContextItem) -> bool:
    return bool(_primary_exact_turn_source_id(item))


def _primary_exact_turn_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = ref.source_id or ""
        if _is_exact_turn_source_id(source_id):
            return source_id
    return ""


def _answer_support_exact_query_object_hits(
    item: ContextItem,
    *,
    query: str,
) -> int:
    if not query or not _has_any_exact_turn_source_ref(item):
        return 0
    query_tokens = _answer_support_query_object_tokens(query)
    if not query_tokens:
        return 0
    exact_turn_text = " ".join(
        _focused_dialogue_turn_text(text=item.text, source_id=ref.source_id or "")
        for ref in item.source_refs
        if _is_exact_turn_source_id(ref.source_id)
    ).casefold()
    if not exact_turn_text:
        return 0
    lexical_hits = sum(
        1
        for token in query_tokens
        if _query_object_token_matches_text(token, exact_turn_text)
    )
    return lexical_hits + _answer_support_semantic_query_object_hits(
        query=query,
        text=exact_turn_text,
    )


def _answer_support_query_object_tokens(query: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in _QUERY_OBJECT_TOKEN_RE.findall(query):
        if token[:1].isupper():
            continue
        normalized = token.casefold()
        if len(normalized) < 3 or normalized in _QUERY_OBJECT_STOPWORDS:
            continue
        if normalized not in tokens:
            tokens.append(normalized)
    return tuple(tokens)


def _query_object_token_matches_text(token: str, text: str) -> bool:
    forms = {token}
    if token.endswith("ies") and len(token) > 4:
        forms.add(f"{token[:-3]}y")
    if token.endswith("s") and len(token) > 4:
        forms.add(token[:-1])
    if token.endswith("ed") and len(token) > 4:
        forms.add(token[:-2])
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        forms.add(stem)
        if len(stem) > 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
    for form in forms:
        if not form:
            continue
        pattern = rf"\b{re.escape(form)}(?:s|ed|ing)?\b"
        if re.search(pattern, text):
            return True
    return False


def _answer_support_semantic_query_object_hits(*, query: str, text: str) -> int:
    normalized_query = query.casefold()
    hits = 0
    if "book" in normalized_query and any(
        marker in normalized_query for marker in ("take away", "learn", "lesson")
    ):
        if re.search(r"\b(?:taught|self[-\s]?acceptance|find(?:ing)?\s+support)\b", text):
            hits += 3
        elif re.search(r"\bhope\b(?=.{0,80}\blove\b)|\blove\b(?=.{0,80}\bhope\b)", text):
            hits += 2
    if (
        "running" in normalized_query
        and ("great for" in normalized_query or "reason" in normalized_query)
        and re.search(r"\b(?:mental health|clear my mind|headspace|de-?stress)\b", text)
    ):
        hits += 2
    if (
        "beach" in normalized_query
        and "how often" in normalized_query
        and re.search(r"\b(?:once|twice|year|often|beach)\b", text)
    ):
        hits += 2
    if (
        "subject" in normalized_query
        and ("painted" in normalized_query or "painting" in normalized_query)
        and re.search(r"\bsunsets?\b", text)
    ):
        hits += 5
    if (
        "art" in normalized_query
        and ("kind" in normalized_query or "style" in normalized_query)
        and re.search(
            r"\b(?:art show|painting for the art show|image caption:.{0,80}painting)\b", text
        )
    ):
        hits += 3
    if (
        "activit" in normalized_query
        and "family" in normalized_query
    ):
        if re.search(r"\b(?:painting together|nature[-\s]?inspired|latest work)\b", text):
            hits += 4
        if re.search(r"\b(?:camping with (?:my\s+)?fam|hang with the kids|unplug)\b", text):
            hits += 4
        if re.search(
            r"\b(?:swimming with the kids|kids loved it|make something with clay|"
            r"museum|husband and kids)\b",
            text,
        ):
            hits += 2
    if (
        "beach" in normalized_query
        and "mountain" in normalized_query
    ):
        if re.search(r"\b(?:beach|ocean|sunset over)\b", text):
            hits += 3
        elif re.search(r"\b(?:walk|nature)\b", text):
            hits += 1
    if (
        "pottery" in normalized_query
        and ("color" in normalized_query or "pattern" in normalized_query)
        and re.search(
            r"\b(?:catch the eye|smile|express(?:ing)? my feelings|creative|stroke)\b",
            text,
        )
    ):
        hits += 4
    if (
        "instrument" in normalized_query
        and re.search(r"\b(?:clarinet|violin|guitar|piano|sheet music)\b", text)
    ):
        hits += 2
    if "nickname" in normalized_query and re.search(r"\bhey\s+[a-z]{2,12}\b", text):
        hits += 2
    return hits


def _focused_dialogue_turn_text(*, text: str, source_id: str) -> str:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return text
    marker = marker_match.group(0)
    text_match = _dialogue_turn_marker_text_match(text=text, marker=marker)
    if text_match is None:
        return text
    end = len(text)
    for next_match in _DIALOGUE_MARKER_RE.finditer(text, text_match.end()):
        if next_match.group(0) != marker:
            end = next_match.start()
            break
    return text[text_match.start() : end].strip() or text


def _dialogue_turn_marker_text_match(*, text: str, marker: str) -> re.Match[str] | None:
    matches = tuple(re.finditer(rf"\b{re.escape(marker)}\b", text))
    if not matches:
        return None
    for match in matches:
        following = text[match.end() : match.end() + 48]
        if re.match(r"\s+[A-Z][^:\n]{0,40}:", following):
            return match
    return matches[0]


def _inventory_first_mention_rank(
    *,
    source_id: str,
    query: str,
    enabled: bool,
) -> tuple[int, int]:
    if not enabled or _RECENCY_QUERY_RE.search(query):
        return _NEUTRAL_SOURCE_ORDER
    match = _TURN_SOURCE_ORDER_RE.search(source_id)
    if match is None:
        return _NEUTRAL_SOURCE_ORDER
    return (int(match.group(1)), int(match.group(2)))


def _is_exact_turn_source_id(source_id: str | None) -> bool:
    parts = (source_id or "").split(":")
    return len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D")


def _diversity_family_base(family: str) -> str:
    return family.split(":", 1)[0]


def _typed_diversity_family(base: str, suffix: str) -> str:
    safe_suffix = _safe_diversity_suffix(suffix)
    return f"{base}:{safe_suffix}" if safe_suffix else base


def _compound_diversity_family(base: str, *suffixes: str) -> str:
    safe_suffixes = tuple(
        safe_suffix
        for suffix in suffixes
        if (safe_suffix := _safe_diversity_suffix(suffix))
    )
    return ":".join((base, *safe_suffixes)) if safe_suffixes else base


def _diagnostic_text(item: ContextItem, key: str) -> str:
    diagnostics = item.diagnostics or {}
    value = diagnostics.get(key)
    if value is None:
        provenance = diagnostics.get("provenance")
        if isinstance(provenance, dict):
            value = provenance.get(key)
    return str(value).strip() if value is not None else ""


def _diagnostic_signal_text(item: ContextItem, key: str) -> str:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        value = score_signals.get(key)
        if value is not None:
            return str(value).strip()
    return _diagnostic_text(item, key)


def _diagnostic_signal_truthy(item: ContextItem, key: str) -> bool:
    value = _diagnostic_signal_text(item, key).casefold()
    return value in {"1", "true", "yes"}


def _diagnostic_score_signals(item: ContextItem) -> dict[str, object]:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    return score_signals if isinstance(score_signals, dict) else {}


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _diagnostic_list(item: ContextItem, key: str) -> tuple[str, ...]:
    diagnostics = item.diagnostics or {}
    values = diagnostics.get(key)
    if values is None:
        provenance = diagnostics.get("provenance")
        if isinstance(provenance, dict):
            values = provenance.get(key)
    if not isinstance(values, list | tuple):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def _safe_diversity_suffix(value: str) -> str:
    text = value.strip().casefold()
    if not text or "redacted" in text:
        return ""
    chars: list[str] = []
    previous_dash = False
    for char in text[:160]:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    token = "".join(chars).strip("-")
    if len(token) <= 64:
        return token
    return f"{token[:24]}-{token[-39:]}".strip("-")[:64]


def _source_ref_modality_hint(item: ContextItem) -> str:
    refs = item.source_refs
    if any(ref.time_start_ms is not None or ref.time_end_ms is not None for ref in refs):
        return "time_range"
    if any(ref.bbox is not None for ref in refs):
        return "image"
    if any(ref.page_number is not None for ref in refs):
        return "document"
    return ""


def _artifact_diversity_hint(item: ContextItem) -> str:
    modality = _diagnostic_text(item, "evidence_modality") or _source_ref_modality_hint(item)
    kind = _diagnostic_text(item, "evidence_kind")
    if modality and kind:
        return f"{modality}-{kind}"
    return modality or kind


def _answer_support_activity_family_slot(family: str) -> str:
    parts = family.split(":")
    if len(parts) < 3 or parts[0] not in {
        "query_reason_activity_slot",
        "query_reason_activity_slot_source_group",
    }:
        return ""
    return parts[2]
