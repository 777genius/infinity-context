"""Shared lexical helpers for deterministic query decomposition."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_decomposition_contracts import (
    QueryDecomposition,
)
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.domain.entities import MemoryAnchorKind

_MAX_QUERY_CHARS = 220

_MAX_IDENTITY_TERMS = 4

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[;?!]+|,\s+|"
    r"\s+\b(?:and|also|then|plus)\b\s+"
    r"(?=(?:what|when|where|who|why|how|which|did|does|do|is|are|was|were|"
    r"can|could|should|would|will)\b)|"
    r"\s+\b(?:и|также|потом|затем)\b\s+"
    r"(?=(?:что|когда|где|кто|почему|как|какая|какие|какой|куда|откуда)\b))",
    re.IGNORECASE,
)

_QUESTION_STOPWORDS = frozenset(
    {
        "are",
        "can",
        "could",
        "did",
        "does",
        "how",
        "is",
        "may",
        "might",
        "should",
        "the",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "would",
        "где",
        "зачем",
        "как",
        "какая",
        "какие",
        "какой",
        "когда",
        "кто",
        "почему",
        "что",
        "куда",
        "откуда",
    }
)

_INFERENCE_TERMS = frozenset(
    {
        "considered",
        "could",
        "infer",
        "inference",
        "likely",
        "might",
        "probably",
        "would",
        "вероятно",
        "вывод",
        "может",
        "мог",
        "могла",
        "похоже",
        "считается",
        "скорее",
    }
)

_SALIENT_DROP_VARIANTS = frozenset(
    {
        *_QUESTION_STOPWORDS,
        *_INFERENCE_TERMS,
        "career",
        "consider",
        "considered",
        "does",
        "focus",
        "kind",
        "kinds",
        "option",
        "still",
        "topic",
        "type",
        "types",
    }
)

_MAX_SALIENT_TERMS = 5

def _append_clause_decompositions(
    candidates: list[QueryDecomposition],
    *,
    query: str,
    identities: tuple[str, ...],
) -> None:
    normalized_query_key = _query_dedupe_key(query)
    for raw_clause in _CLAUSE_SPLIT_RE.split(query):
        clause = _clean_clause_query(raw_clause)
        if not _is_useful_clause(clause):
            continue
        clause_query = _with_missing_identities(clause, identities)
        if _query_dedupe_key(clause_query) == normalized_query_key:
            continue
        _append_candidate(
            candidates,
            query=clause_query,
            reason="decomposition_clause",
        )

def _append_candidate(
    candidates: list[QueryDecomposition],
    *,
    query: str,
    reason: str,
) -> None:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return
    key = _query_dedupe_key(normalized_query)
    if any(
        _query_dedupe_key(item.query) == key
        or (item.reason == reason and reason != "decomposition_clause")
        for item in candidates
    ):
        return
    candidates.append(
        QueryDecomposition(
            query=_truncate_query(normalized_query),
            reason=reason,
        )
    )

def _compose_query(
    identities: Sequence[str],
    tail: str,
) -> str:
    return _normalize_query(" ".join((*identities, tail)))

def _salient_terms(query: str, *, identities: tuple[str, ...]) -> tuple[str, ...]:
    identity_keys = {identity.casefold() for identity in identities}
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_terms(query, min_chars=3, max_terms=18):
        variants = frozenset(term.variants)
        raw = _normalize_identity_term(term.raw)
        if not raw:
            continue
        key = raw.casefold()
        if key in seen or key in identity_keys:
            continue
        if variants.intersection(_SALIENT_DROP_VARIANTS):
            continue
        terms.append(raw)
        seen.add(key)
        if len(terms) >= _MAX_SALIENT_TERMS:
            break
    return tuple(terms)

def _with_missing_identities(clause: str, identities: tuple[str, ...]) -> str:
    if not identities:
        return clause
    clause_key = clause.casefold()
    if _clause_contains_identity(clause_key, identities):
        return clause
    missing = tuple(
        identity for identity in identities[:2] if identity.casefold() not in clause_key
    )
    if not missing:
        return clause
    return _normalize_query(" ".join((*missing, clause)))

def _clause_contains_identity(clause_key: str, identities: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(identity.casefold())}(?!\w)", clause_key)
        for identity in identities
        if identity
    )

def _identity_terms(
    query: str,
    anchor_intent: QueryAnchorIntent,
) -> tuple[str, ...]:
    labels = [
        hint.label
        for hint in anchor_intent.hints
        if hint.kind
        in {
            MemoryAnchorKind.PERSON,
            MemoryAnchorKind.PROJECT,
            MemoryAnchorKind.ORGANIZATION,
        }
    ]
    labels.extend(_capitalized_identity_terms(query))
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        term = _normalize_identity_term(label)
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
        if len(deduped) >= _MAX_IDENTITY_TERMS:
            break
    return tuple(deduped)

def _capitalized_identity_terms(query: str) -> Iterable[str]:
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).strip("_")
        if len(token) < 2 or token.casefold() in _QUESTION_STOPWORDS:
            continue
        if token[:1].isupper():
            yield token

def _normalize_identity_term(value: str) -> str:
    tokens = _normalize_query(value).strip("@").split()
    while tokens and tokens[0].casefold() in _QUESTION_STOPWORDS:
        tokens = tokens[1:]
    while tokens and tokens[-1].casefold() in _QUESTION_STOPWORDS:
        tokens = tokens[:-1]
    token = _normalize_query(" ".join(tokens)).strip("@")
    if len(token) < 2 or token.casefold() in _QUESTION_STOPWORDS:
        return ""
    return token

def _is_useful_clause(clause: str) -> bool:
    if len(clause) < 8:
        return False
    terms = query_terms(clause, min_chars=2, max_terms=12)
    distinctive = [
        term for term in terms if not set(term.variants).intersection(_QUESTION_STOPWORDS)
    ]
    return len(distinctive) >= 2

def _query_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=32):
        variants.update(term.variants)
    variants.update(_raw_query_tokens(query))
    return frozenset(variants)

def _raw_query_tokens(query: str) -> Iterable[str]:
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            yield token

def _normalize_query(query: str) -> str:
    return " ".join(query.split())

def _clean_clause_query(query: str) -> str:
    normalized = _normalize_query(query)
    return re.sub(
        r"^(?:and|also|then|plus|и|также|потом|затем)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )

def _query_dedupe_key(query: str) -> str:
    return _normalize_query(query).strip(" \t\r\n.,;:!?").casefold()

def _truncate_query(query: str) -> str:
    if len(query) <= _MAX_QUERY_CHARS:
        return query.strip()
    candidate = query[:_MAX_QUERY_CHARS].rstrip()
    if not candidate:
        return ""
    boundary = candidate.rfind(" ")
    if boundary >= max(0, _MAX_QUERY_CHARS - 32):
        candidate = candidate[:boundary]
    return candidate.strip(" \t\r\n.,;:!?")
