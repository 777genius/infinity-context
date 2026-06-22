"""Deterministic decomposition of compound memory queries."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    build_query_anchor_intent,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_MAX_DECOMPOSITIONS = 6
_MAX_QUERY_CHARS = 220
_MAX_IDENTITY_TERMS = 4
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[;?!]+|,\s+|\s+\b(?:and|also|then|plus|и|также|потом|затем)\b\s+)",
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
    }
)
_EVENT_TERMS = frozenset(
    {
        "call",
        "chat",
        "conversation",
        "demo",
        "dm",
        "launch",
        "meeting",
        "message",
        "review",
        "sync",
        "workshop",
        "звонок",
        "созвон",
        "чат",
        "встреча",
        "демо",
        "переписка",
        "разговор",
        "ревью",
        "релиз",
        "созвона",
        "стендап",
    }
)
_ARTIFACT_TERMS = frozenset(
    {
        "audio",
        "document",
        "file",
        "image",
        "photo",
        "picture",
        "screenshot",
        "video",
        "аудио",
        "видео",
        "документ",
        "изображение",
        "картинка",
        "скриншот",
        "файл",
        "фото",
    }
)
_SOURCE_TERMS = frozenset(
    {
        "citation",
        "citations",
        "evidence",
        "file",
        "source",
        "sources",
        "доказательство",
        "источник",
        "источники",
        "файл",
    }
)


@dataclass(frozen=True)
class QueryDecomposition:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryDecompositionPlan:
    original_query: str
    decompositions: tuple[QueryDecomposition, ...]

    @property
    def empty(self) -> bool:
        return not self.decompositions

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_decomposition_status": "empty" if self.empty else "available",
            "query_decomposition_count": len(self.decompositions),
            "query_decomposition_reasons": [
                item.reason for item in self.decompositions
            ],
        }


def build_query_decomposition_plan(
    query: str,
    *,
    anchor_intent: QueryAnchorIntent | None = None,
    temporal_intent: TemporalQueryIntent | None = None,
) -> QueryDecompositionPlan:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return QueryDecompositionPlan(original_query=query, decompositions=())
    anchor_intent = anchor_intent or build_query_anchor_intent(query)
    temporal_intent = temporal_intent or build_temporal_query_intent(query)
    variants = _query_variant_set(query)
    identities = _identity_terms(query, anchor_intent)
    candidates: list[QueryDecomposition] = []
    _append_clause_decompositions(candidates, query=query, identities=identities)
    if _has_event_focus(anchor_intent, variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event conversation meeting call transcript notes discussed "
                    "decision action item follow up"
                ),
            ),
            reason="decomposition_event_context",
        )
    if temporal_intent.requests_change:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "changed updated current previous before after superseded "
                    "replaced difference decision"
                ),
            ),
            reason="decomposition_temporal_change",
        )
    if variants.intersection(_ARTIFACT_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "artifact file screenshot image video audio document ocr "
                    "transcript detected text keyframe source"
                ),
            ),
            reason="decomposition_artifact_evidence",
        )
    if variants.intersection(_SOURCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                "source citation evidence file artifact reference provenance",
            ),
            reason="decomposition_source_evidence",
        )
    return QueryDecompositionPlan(
        original_query=query,
        decompositions=tuple(candidates[:_MAX_DECOMPOSITIONS]),
    )


def _append_clause_decompositions(
    candidates: list[QueryDecomposition],
    *,
    query: str,
    identities: tuple[str, ...],
) -> None:
    normalized_query = _normalize_query(query).casefold()
    for raw_clause in _CLAUSE_SPLIT_RE.split(query):
        clause = _normalize_query(raw_clause)
        if not _is_useful_clause(clause):
            continue
        clause_query = _with_missing_identities(clause, identities)
        if clause_query.casefold() == normalized_query:
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
    key = normalized_query.casefold()
    if any(
        item.query.casefold() == key
        or (item.reason == reason and reason != "decomposition_clause")
        for item in candidates
    ):
        return
    candidates.append(
        QueryDecomposition(
            query=normalized_query[:_MAX_QUERY_CHARS].strip(),
            reason=reason,
        )
    )


def _has_event_focus(
    anchor_intent: QueryAnchorIntent,
    variants: frozenset[str],
) -> bool:
    return bool(
        variants.intersection(_EVENT_TERMS)
        or anchor_intent.keys_for_kind(MemoryAnchorKind.EVENT)
        or anchor_intent.event_type_keys()
    )


def _compose_query(
    identities: Sequence[str],
    tail: str,
) -> str:
    return _normalize_query(" ".join((*identities, tail)))


def _with_missing_identities(clause: str, identities: tuple[str, ...]) -> str:
    if not identities:
        return clause
    clause_key = clause.casefold()
    missing = tuple(
        identity
        for identity in identities[:2]
        if identity.casefold() not in clause_key
    )
    if not missing:
        return clause
    return _normalize_query(" ".join((*missing, clause)))


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
    token = _normalize_query(value).strip("@")
    if len(token) < 2 or token.casefold() in _QUESTION_STOPWORDS:
        return ""
    return token


def _is_useful_clause(clause: str) -> bool:
    if len(clause) < 8:
        return False
    terms = query_terms(clause, min_chars=2, max_terms=12)
    distinctive = [
        term
        for term in terms
        if not set(term.variants).intersection(_QUESTION_STOPWORDS)
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
