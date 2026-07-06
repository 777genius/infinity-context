"""Source-grounding signals for deterministic context reranking."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from infinity_context_core.domain.entities import SourceRef

_SOURCE_GROUNDING_QUERY_RE = re.compile(
    r"\b(?:which|what|where)\b.{0,80}\b"
    r"(?:dialog(?:ue)?|source|turn|evidence|citation|quote|support(?:s|ed)?)\b"
    r"|\b(?:dialog(?:ue)?|source|turn|conversation|evidence|citation|quote)\b"
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
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|none|n't|didn't|doesn't|don't|isn't|wasn't|weren't|"
    r"haven't|hasn't|hadn't|cannot|can't|won't|without)\b",
    re.IGNORECASE,
)
_DIALOGUE_SOURCE_QUERY_RE = re.compile(
    r"\b(?:dialog(?:ue)?|turn)\b|\bwho\b.{0,80}\b"
    r"(?:said|told|mentioned|recommended|suggested|asked|advised|invited|"
    r"called|texted|messaged|discussed|talked)\b",
    re.IGNORECASE | re.DOTALL,
)
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "according",
        "and",
        "came",
        "citation",
        "conversation",
        "dialog",
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
_SOURCE_GROUNDING_UNRELATED_QUOTE_PENALTY = 0.018


@dataclass(frozen=True)
class SourceGroundingSignal:
    """Bounded evidence signal for source/support attribution queries."""

    boost: float
    penalty: float
    reason: str
    grounded: bool
    quote_relevant: bool
    source_anchor: bool


def source_grounding_signal(
    *,
    query: str,
    text: str,
    source_refs: Sequence[SourceRef],
) -> tuple[float, float, str]:
    """Return a bounded signal for questions that ask for source attribution."""

    signal = source_grounding_evidence(
        query=query,
        text=text,
        source_refs=source_refs,
    )
    return signal.boost, signal.penalty, signal.reason


def source_grounding_evidence(
    *,
    query: str,
    text: str,
    source_refs: Sequence[SourceRef],
) -> SourceGroundingSignal:
    """Return source-grounding evidence including quote relevance diagnostics."""

    if not is_source_grounding_query(query):
        return SourceGroundingSignal(0.0, 0.0, "", False, False, False)
    if not _polarity_compatible(query=query, text=text):
        return SourceGroundingSignal(0.0, 0.0, "", False, False, False)
    content_hits = _query_content_hit_count(query=query, text=text)
    if content_hits < _required_content_hits(query):
        return SourceGroundingSignal(0.0, 0.0, "", False, False, False)
    direct_turn = _has_direct_dialogue_turn(text)
    quote_relevant = _has_relevant_source_quote(query=query, source_refs=source_refs)
    if (
        not direct_turn
        and _has_unrelated_source_quote(query=query, source_refs=source_refs)
    ):
        return SourceGroundingSignal(
            0.0,
            _SOURCE_GROUNDING_UNRELATED_QUOTE_PENALTY,
            "source_grounding_unrelated_quote",
            False,
            False,
            False,
        )
    source_anchor = (
        direct_turn
        or _has_turn_source_anchor(text, source_refs)
        or (quote_relevant and not _requires_dialogue_source_anchor(query))
    )
    if source_anchor:
        return SourceGroundingSignal(
            _SOURCE_GROUNDING_MATCH_BOOST
            if direct_turn
            else _SOURCE_GROUNDING_SOURCE_REF_BOOST,
            0.0,
            "source_grounding_match",
            True,
            quote_relevant,
            True,
        )
    return SourceGroundingSignal(
        0.0,
        _SOURCE_GROUNDING_MISSING_ANCHOR_PENALTY,
        "source_grounding_answer_without_source",
        False,
        quote_relevant,
        False,
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
    text_terms = {
        variant
        for text_term in _normalized_terms(text)
        for variant in _term_variants(text_term)
    }
    return sum(
        1
        for term in terms
        if any(variant in text_terms for variant in _term_variants(term))
    )


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
    terms: list[str] = []
    for match in _WORD_RE.finditer(text or ""):
        term = _normalize_term(match.group(0))
        if term:
            terms.append(term)
    return tuple(terms)


def _normalize_term(term: str) -> str:
    normalized = term.casefold().strip("'")
    if normalized.endswith("'s"):
        normalized = normalized[:-2]
    return normalized


def _term_variants(term: str) -> tuple[str, ...]:
    variants = [term]
    if len(term) > 4 and term.endswith("ed"):
        variants.append(term[:-1])
    if len(term) > 5 and term.endswith("ing"):
        variants.append(term[:-3])
    if len(term) > 4 and term.endswith("s"):
        variants.append(term[:-1])
    return tuple(dict.fromkeys(variant for variant in variants if variant))


def _has_direct_dialogue_turn(text: str) -> bool:
    return _DIRECT_DIALOGUE_TURN_RE.search(text or "") is not None


def _requires_dialogue_source_anchor(query: str) -> bool:
    return _DIALOGUE_SOURCE_QUERY_RE.search(query or "") is not None


def _has_turn_source_anchor(text: str, source_refs: Sequence[SourceRef]) -> bool:
    if _TURN_REF_RE.search(text or "") is not None:
        return True
    return any(
        _TURN_REF_RE.search(str(ref.source_id or "")) is not None
        or str(ref.source_id or "").casefold().endswith(":turn")
        or _TURN_REF_RE.search(str(ref.chunk_id or "")) is not None
        for ref in source_refs
    )


def _has_relevant_source_quote(*, query: str, source_refs: Sequence[SourceRef]) -> bool:
    required_hits = _required_content_hits(query)
    if required_hits <= 0:
        return False
    return any(
        _polarity_compatible(query=query, text=ref.quote_preview or "")
        and
        _query_content_hit_count(query=query, text=ref.quote_preview or "")
        >= required_hits
        for ref in source_refs
        if (ref.quote_preview or "").strip()
    )


def _polarity_compatible(*, query: str, text: str) -> bool:
    query_negated = _NEGATION_RE.search(query or "") is not None
    text_negated = _NEGATION_RE.search(text or "") is not None
    return query_negated == text_negated


def _has_unrelated_source_quote(*, query: str, source_refs: Sequence[SourceRef]) -> bool:
    quoted_refs = tuple(ref for ref in source_refs if (ref.quote_preview or "").strip())
    if not quoted_refs:
        return False
    return not _has_relevant_source_quote(query=query, source_refs=quoted_refs)
