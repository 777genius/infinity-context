"""Object-attribute grounding signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9'_-]*\b")
_CAPITALIZED_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z'_-]{1,40}\b")
_POSSESSIVE_PERSON_RE = re.compile(r"\b([A-Z][A-Za-z'_-]{1,40})'s\b")
_DIALOGUE_SPEAKER_RE = re.compile(r"\bD\d+:\d+\s+([A-Z][A-Za-z'_-]{1,40}):")
_ATTRIBUTE_WINDOW = 90

_ATTRIBUTE_ALIASES = {
    "brand": "brand",
    "brands": "brand",
    "make": "brand",
    "maker": "brand",
    "company": "brand",
    "model": "model",
    "models": "model",
    "type": "model",
    "kind": "model",
    "name": "name",
    "named": "name",
    "called": "name",
    "title": "name",
    "color": "color",
    "colour": "color",
    "colors": "color",
    "colours": "color",
    "price": "price",
    "cost": "price",
    "costs": "price",
    "paid": "price",
    "worth": "price",
    "expensive": "price",
    "cheap": "price",
    "size": "size",
    "sized": "size",
    "small": "size",
    "large": "size",
    "medium": "size",
    "status": "status",
    "state": "status",
    "condition": "status",
    "current": "status",
}
_ATTRIBUTE_QUERY_RE = re.compile(
    r"\b(?:brand|make|maker|model|type|kind|name|named|called|title|"
    r"colou?rs?|price|costs?|paid|worth|expensive|cheap|size|sized|"
    r"status|state|condition|current)\b|"
    r"\bhow\s+much\b",
    re.IGNORECASE,
)
_OBJECT_STOPWORDS = frozenset(
    {
        "about",
        "also",
        "and",
        "any",
        "are",
        "because",
        "been",
        "being",
        "both",
        "can",
        "current",
        "currently",
        "did",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "her",
        "hers",
        "him",
        "his",
        "how",
        "into",
        "its",
        "latest",
        "much",
        "now",
        "own",
        "owned",
        "person",
        "she",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "with",
        "would",
        "your",
    }
)
_ATTRIBUTE_WORDS = frozenset(_ATTRIBUTE_ALIASES) | frozenset(
    {
        "colours",
        "colors",
    }
)
_COLOR_VALUE_RE = re.compile(
    r"\b(?:black|white|red|blue|green|yellow|orange|purple|pink|brown|gray|grey|"
    r"silver|gold|golden|tan|beige|cream|navy|teal|turquoise|maroon|violet|"
    r"indigo|lavender|plaid|striped|patterned|floral|dark|light|bright)\b",
    re.IGNORECASE,
)
_PRICE_VALUE_RE = re.compile(
    r"(?:[$\u20ac\u00a3]\s?\d+(?:[.,]\d{2})?|\b\d+(?:[.,]\d{2})?\s?"
    r"(?:dollars?|bucks?|usd|eur|euros?|pounds?)\b)",
    re.IGNORECASE,
)
_SIZE_VALUE_RE = re.compile(
    r"\b(?:xxs|xs|small|medium|large|xl|xxl|tiny|huge|big|little|compact|"
    r"oversized|full[-\s]?size|queen|king|twin|size\s+\d+|"
    r"\d+\s?(?:cm|mm|in|inch|inches|ft|feet))\b",
    re.IGNORECASE,
)
_STATUS_VALUE_RE = re.compile(
    r"\b(?:active|inactive|available|unavailable|sold|lost|missing|broken|fixed|"
    r"working|repaired|ready|pending|approved|rejected|new|old|current|latest|"
    r"retired|cancelled|canceled|delayed|done|finished|open|closed)\b",
    re.IGNORECASE,
)
_NAME_VALUE_RE = re.compile(
    r"\b(?:named|called|goes\s+by|name\s+is|title\s+is)\b",
    re.IGNORECASE,
)
_BRAND_MODEL_VALUE_RE = re.compile(
    r"\b(?:brand|make|model|type|kind|from|by|is\s+a|it's\s+a|it\s+is\s+a)\b",
    re.IGNORECASE,
)


def object_attribute_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    del query_reason
    intent = _object_attribute_query_intent(query)
    if not intent:
        return DomainRerankSignal()
    text = item.text
    object_hits = _object_hits(intent.object_terms, text)
    if object_hits and _has_local_attribute_evidence(
        attribute_kinds=intent.attribute_kinds,
        object_terms=object_hits,
        text=text,
    ):
        return DomainRerankSignal(
            boost=0.066,
            reason="object_attribute_local_evidence",
            rank_signal_key="object_attribute_local_evidence",
            rank_signal=3.0,
        )
    if object_hits and _has_attribute_evidence(intent.attribute_kinds, text):
        return DomainRerankSignal(
            boost=0.026,
            reason="object_attribute_broad_evidence",
            rank_signal_key="object_attribute_local_evidence",
            rank_signal=1.0,
        )
    if _is_person_attribute_noise(intent.person_terms, text):
        return DomainRerankSignal(
            penalty=0.13,
            reason="object_attribute_person_attribute_noise",
        )
    if object_hits and relevance.distinctive_term_hits < 3:
        return DomainRerankSignal(
            penalty=0.045,
            reason="object_attribute_weak_evidence",
        )
    return DomainRerankSignal()


@dataclass(frozen=True)
class _ObjectAttributeIntent:
    attribute_kinds: tuple[str, ...]
    object_terms: tuple[str, ...]
    person_terms: tuple[str, ...]


def _object_attribute_query_intent(query: str) -> _ObjectAttributeIntent | None:
    if _ATTRIBUTE_QUERY_RE.search(query) is None:
        return None
    attribute_kinds = _query_attribute_kinds(query)
    object_terms = _query_object_terms(query)
    if not attribute_kinds or not object_terms:
        return None
    return _ObjectAttributeIntent(
        attribute_kinds=attribute_kinds,
        object_terms=object_terms,
        person_terms=_query_person_terms(query),
    )


def _query_attribute_kinds(query: str) -> tuple[str, ...]:
    kinds: list[str] = []
    normalized = query.casefold()
    if "how much" in normalized:
        kinds.append("price")
    for token in _TOKEN_RE.findall(query):
        kind = _ATTRIBUTE_ALIASES.get(token.casefold())
        if kind and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)


def _query_object_terms(query: str) -> tuple[str, ...]:
    people = set(_query_person_terms(query))
    terms: list[str] = []
    for token in _TOKEN_RE.findall(query):
        normalized = token.casefold().strip("'")
        if (
            len(normalized) < 3
            or normalized in people
            or normalized in _OBJECT_STOPWORDS
            or normalized in _ATTRIBUTE_WORDS
        ):
            continue
        if token[:1].isupper() and normalized not in _likely_named_object_terms(query):
            continue
        if normalized not in terms:
            terms.append(normalized)
    return tuple(terms[:4])


def _query_person_terms(query: str) -> tuple[str, ...]:
    people: list[str] = []
    for match in _POSSESSIVE_PERSON_RE.finditer(query):
        people.append(match.group(1).casefold())
    if not people:
        for token in _CAPITALIZED_TOKEN_RE.findall(query):
            normalized = token.casefold()
            if normalized not in {"what", "which", "when", "where", "who", "how"}:
                people.append(normalized)
    return tuple(dict.fromkeys(people))


def _likely_named_object_terms(query: str) -> frozenset[str]:
    named: set[str] = set()
    for match in re.finditer(
        r"\b(?:called|named|name(?:d)?\s+(?:of|for)|model)\s+"
        r"([A-Z][A-Za-z0-9'_-]{1,40})\b",
        query,
    ):
        named.add(match.group(1).casefold())
    return frozenset(named)


def _object_hits(object_terms: tuple[str, ...], text: str) -> tuple[str, ...]:
    return tuple(term for term in object_terms if _term_matches_text(term, text))


def _term_matches_text(term: str, text: str) -> bool:
    forms = {term}
    if term.endswith("ies") and len(term) > 4:
        forms.add(f"{term[:-3]}y")
    if term.endswith("s") and len(term) > 4:
        forms.add(term[:-1])
    return any(
        re.search(rf"\b{re.escape(form)}(?:s|es)?\b", text, re.IGNORECASE)
        for form in forms
    )


def _has_local_attribute_evidence(
    *,
    attribute_kinds: tuple[str, ...],
    object_terms: tuple[str, ...],
    text: str,
) -> bool:
    for term in object_terms:
        pattern = rf"\b{re.escape(term)}(?:s|es)?\b"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - _ATTRIBUTE_WINDOW)
            end = match.end() + _ATTRIBUTE_WINDOW
            window = text[
                start:end
            ]
            if _has_attribute_evidence(attribute_kinds, window):
                return True
    return False


def _has_attribute_evidence(attribute_kinds: tuple[str, ...], text: str) -> bool:
    return any(_has_attribute_kind_evidence(kind, text) for kind in attribute_kinds)


def _has_attribute_kind_evidence(kind: str, text: str) -> bool:
    if kind == "color":
        return _COLOR_VALUE_RE.search(text) is not None or re.search(
            r"\bcolou?rs?\b",
            text,
            re.IGNORECASE,
        )
    if kind == "price":
        return _PRICE_VALUE_RE.search(text) is not None or re.search(
            r"\b(?:price|costs?|paid|worth|expensive|cheap)\b",
            text,
            re.IGNORECASE,
        )
    if kind == "size":
        return _SIZE_VALUE_RE.search(text) is not None or re.search(
            r"\bsize\b",
            text,
            re.IGNORECASE,
        )
    if kind == "status":
        return _STATUS_VALUE_RE.search(text) is not None or re.search(
            r"\b(?:status|state|condition)\b",
            text,
            re.IGNORECASE,
        )
    if kind == "name":
        return _NAME_VALUE_RE.search(text) is not None
    if kind in {"brand", "model"}:
        return _BRAND_MODEL_VALUE_RE.search(text) is not None
    return False


def _is_person_attribute_noise(person_terms: tuple[str, ...], text: str) -> bool:
    if not person_terms or not _has_any_attribute_surface(text):
        return False
    speaker = _speaker_term(text)
    return speaker in person_terms or any(
        _term_matches_text(term, text) for term in person_terms
    )


def _speaker_term(text: str) -> str:
    match = _DIALOGUE_SPEAKER_RE.search(text)
    return match.group(1).casefold() if match else ""


def _has_any_attribute_surface(text: str) -> bool:
    return (
        _ATTRIBUTE_QUERY_RE.search(text) is not None
        or _COLOR_VALUE_RE.search(text) is not None
        or _PRICE_VALUE_RE.search(text) is not None
        or _SIZE_VALUE_RE.search(text) is not None
        or _STATUS_VALUE_RE.search(text) is not None
        or _NAME_VALUE_RE.search(text) is not None
    )
