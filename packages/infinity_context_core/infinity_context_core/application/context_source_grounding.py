"""Source-grounding signals for deterministic context reranking."""

from __future__ import annotations

import re
from collections.abc import Sequence

from infinity_context_core.domain.entities import SourceRef

_SOURCE_GROUNDING_QUERY_RE = re.compile(
    r"\b(?:which|what|where)\b.{0,80}\b"
    r"(?:dialogue|source|turn|conversation|evidence|citation|quote|support(?:s|ed)?)\b"
    r"|\b(?:dialogue|source|turn|conversation|evidence|citation|quote)\b"
    r".{0,80}\b(?:support(?:s|ed)?|show(?:s|ed)?|prove(?:s|d)?|say|said|told|mentioned)\b"
    r"|\bwhere\b.{0,80}\b(?:came|come)\s+from\b"
    r"|\bwho\b.{0,80}\b"
    r"(?:said|told|mentioned|recommended|suggested|asked|advised|invited|"
    r"called|texted|messaged|discussed|talked)\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_SOURCE_GROUNDING_QUERY_RE = re.compile(
    r"\bwho\b.{0,80}\b"
    r"(?:said|told|mentioned|recommended|suggested|asked|advised|invited|"
    r"called|texted|messaged|discussed|talked)\b",
    re.IGNORECASE | re.DOTALL,
)
_DIRECT_DIALOGUE_TURN_RE = re.compile(
    r"\bD\d+:\d+\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,40}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,40}){0,2}\s*:"
)
_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9'-]*")
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "according",
        "and",
        "came",
        "citation",
        "conversation",
        "dialogue",
        "did",
        "does",
        "evidence",
        "from",
        "quote",
        "said",
        "say",
        "source",
        "support",
        "supported",
        "supports",
        "that",
        "the",
        "this",
        "told",
        "turn",
        "what",
        "where",
        "which",
        "who",
    }
)
_SOURCE_GROUNDING_MATCH_BOOST = 0.026
_SOURCE_GROUNDING_SOURCE_REF_BOOST = 0.016
_SOURCE_GROUNDING_MISSING_ANCHOR_PENALTY = 0.034


def source_grounding_signal(
    *,
    query: str,
    text: str,
    source_refs: Sequence[SourceRef],
) -> tuple[float, float, str]:
    """Return a bounded signal for questions that ask for source attribution."""

    if not is_source_grounding_query(query):
        return 0.0, 0.0, ""
    content_hits = _query_content_hit_count(query=query, text=text)
    if content_hits < _required_content_hits(query):
        return 0.0, 0.0, ""
    direct_turn = _has_direct_dialogue_turn(text)
    source_anchor = direct_turn or _has_turn_source_anchor(text, source_refs)
    if source_anchor:
        return (
            _SOURCE_GROUNDING_MATCH_BOOST
            if direct_turn
            else _SOURCE_GROUNDING_SOURCE_REF_BOOST,
            0.0,
            "source_grounding_match",
        )
    return (
        0.0,
        _SOURCE_GROUNDING_MISSING_ANCHOR_PENALTY,
        "source_grounding_answer_without_source",
    )


def is_source_grounding_query(query: str) -> bool:
    """Return whether a query asks for a source/speaker/dialogue anchor."""

    normalized = " ".join(str(query or "").casefold().split())
    return bool(normalized and _SOURCE_GROUNDING_QUERY_RE.search(normalized))


def _required_content_hits(query: str) -> int:
    terms = _query_content_terms(query)
    if _WHO_SOURCE_GROUNDING_QUERY_RE.search(query):
        return 1
    return min(2, len(terms)) if terms else 0


def _query_content_hit_count(*, query: str, text: str) -> int:
    terms = _query_content_terms(query)
    if not terms:
        return 0
    text_terms = set(_normalized_terms(text))
    return sum(1 for term in terms if term in text_terms)


def _query_content_terms(query: str) -> tuple[str, ...]:
    terms = tuple(
        dict.fromkeys(
            term
            for term in _normalized_terms(query)
            if term not in _QUERY_STOPWORDS and len(term) > 2
        )
    )
    return terms


def _normalized_terms(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _WORD_RE.finditer(text or ""))


def _has_direct_dialogue_turn(text: str) -> bool:
    return _DIRECT_DIALOGUE_TURN_RE.search(text or "") is not None


def _has_turn_source_anchor(text: str, source_refs: Sequence[SourceRef]) -> bool:
    if _TURN_REF_RE.search(text or "") is not None:
        return True
    return any(
        _TURN_REF_RE.search(str(ref.source_id or "")) is not None
        or str(ref.source_id or "").casefold().endswith(":turn")
        or _TURN_REF_RE.search(str(ref.chunk_id or "")) is not None
        for ref in source_refs
    )
