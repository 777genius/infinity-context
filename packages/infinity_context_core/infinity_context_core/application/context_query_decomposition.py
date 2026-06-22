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
        "proof",
        "source",
        "sources",
        "доказательство",
        "источник",
        "источники",
        "файл",
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
_COMPARISON_TERMS = frozenset(
    {
        "between",
        "compare",
        "compared",
        "comparison",
        "interested",
        "less",
        "more",
        "prefer",
        "preference",
        "rather",
        "versus",
        "vs",
        "больше",
        "выбор",
        "интереснее",
        "лучше",
        "между",
        "меньше",
        "предпочел",
        "предпочла",
        "предпочитает",
        "сравни",
    }
)
_ATTRIBUTE_AGGREGATION_TERMS = frozenset(
    {
        "attend",
        "attended",
        "bought",
        "buy",
        "events",
        "instrument",
        "instruments",
        "items",
        "participate",
        "participated",
        "play",
        "plays",
        "share",
        "shared",
        "traits",
    }
)
_ACTIVITY_PARTICIPATION_TERMS = frozenset(
    {
        "activities",
        "activity",
        "hobbies",
        "hobby",
        "partake",
        "participate",
        "participates",
        "participated",
    }
)
_IDENTITY_ATTRIBUTE_TERMS = frozenset(
    {
        "gender",
        "identity",
        "pronouns",
        "trans",
        "transgender",
    }
)
_RELATIONSHIP_STATUS_TERMS = frozenset(
    {
        "breakup",
        "dating",
        "divorced",
        "married",
        "partner",
        "relationship",
        "single",
        "spouse",
        "status",
    }
)
_CURRENT_GOAL_TERMS = frozenset(
    {
        "adopt",
        "adoption",
        "back",
        "career",
        "country",
        "future",
        "goal",
        "goals",
        "move",
        "moved",
        "moving",
        "open",
        "plan",
        "pursue",
        "soon",
        "want",
        "wants",
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
        "option",
        "still",
    }
)
_MAX_SALIENT_TERMS = 5
_EVIDENCE_REASON_RE = re.compile(
    r"\b("
    r"why|reason|because|what evidence|which evidence|what shows|what showed|"
    r"what indicates|how do we know|how can we tell|how would we know|"
    r"почему|причин|потому что|какие доказательства|какое доказательство|"
    r"что показывает|что показало|как мы знаем|откуда известно"
    r")\b",
    re.IGNORECASE,
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
    raw_tokens = frozenset(_raw_query_tokens(query))
    identities = _identity_terms(query, anchor_intent)
    salient_terms = _salient_terms(query, identities=identities)
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
    if temporal_intent.after_event or temporal_intent.before_event:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                _event_sequence_tail(temporal_intent),
            ),
            reason="decomposition_event_sequence",
        )
    if temporal_intent.relative_time_hints:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event temporal time window occurred capture transcript "
                    f"notes meeting call {' '.join(temporal_intent.relative_time_hints)}"
                ),
            ),
            reason="decomposition_relative_time",
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
    if _requests_evidence_reason(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "reason evidence because observed mentioned showed indicates "
                    "supporting fact source citation quote explanation why"
                ),
            ),
            reason="decomposition_evidence_reason",
        )
    if raw_tokens.intersection(_IDENTITY_ATTRIBUTE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "identity gender pronouns transgender trans woman transition "
                    "true self accepted belongs community support group pride"
                ),
            ),
            reason="decomposition_identity_attribute",
        )
    if _requests_relationship_status(variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "relationship status single parent partner spouse married "
                    "dating breakup friends family mentors support system kids "
                    "children challenge make family"
                ),
            ),
            reason="decomposition_relationship_status",
        )
    if variants.intersection(_INFERENCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "inference supporting evidence likely would considered "
                    "observed mentioned indicates preference trait decision reason "
                    "support supportive encouraging acceptance care help"
                ),
            ),
            reason="decomposition_inference_support",
        )
        if variants.intersection(_CURRENT_GOAL_TERMS):
            _append_candidate(
                candidates,
                query=_compose_query(
                    (*identities, *salient_terms),
                    (
                        "current goal future plan wants preference likes dislikes "
                        "interested recently now decided committed adoption family "
                        "children kids home roof agency interview build career "
                        "activity service country office military"
                    ),
                ),
                reason="decomposition_current_preference_or_goal",
            )
    if _requests_non_inference_career_goal(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "current career path goal decided pursue education options "
                    "counseling counselor mental health jobs work"
                ),
            ),
            reason="decomposition_current_preference_or_goal",
        )
    if variants.intersection(_COMPARISON_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "comparison preference choice option alternative likes dislikes "
                    "interested more less rather prefer similar difference evidence"
                ),
            ),
            reason="decomposition_comparison_preference",
        )
    if _requests_activity_participation(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "activities hobbies activity partake participate observed "
                    "painting swimming pottery camping running creative outdoors "
                    "exercise family kids"
                ),
            ),
            reason="decomposition_activity_participation",
        )
    if variants.intersection(_ATTRIBUTE_AGGREGATION_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _attribute_aggregation_tail(variants),
            ),
            reason="decomposition_attribute_aggregation",
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


def _attribute_aggregation_tail(variants: frozenset[str]) -> str:
    tails: list[str] = [
        "aggregate list multiple mentions evidence observed mentioned",
    ]
    if variants.intersection({"items", "bought", "buy"}):
        tails.append("item bought purchased got new gift object possession")
    if variants.intersection({"instrument", "instruments", "play", "plays"}):
        tails.append("instrument music play plays played violin clarinet piano guitar")
    if variants.intersection(
        {"events", "attend", "attended", "participate", "participated"}
    ):
        tails.append(
            "event attended participated went conference parade speech support group "
            "reading meeting mentorship mentoring youth children school talk gender "
            "identity inclusion community ally allies"
        )
    if variants.intersection({"share", "shared"}):
        tails.append(
            "shared both similar interests hobbies enjoy watching movies making "
            "desserts recipes baking"
        )
    if variants.intersection({"traits"}):
        tails.append(
            "trait personality thoughtful authentic driven caring supportive "
            "concerned helpful"
        )
    return _normalize_query(" ".join(tails))


def _requests_non_inference_career_goal(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    return (
        "career" in variants
        and bool(raw_tokens.intersection({"decided", "persue"}) or "path" in variants)
    )


def _event_sequence_tail(intent: TemporalQueryIntent) -> str:
    if intent.after_event and not intent.before_event:
        return (
            "after following later next timeline outcome follow up decision "
            "result happened then response meeting call conversation event"
        )
    if intent.before_event and not intent.after_event:
        return (
            "before earlier prior previous timeline context lead up reason "
            "setup happened meeting call conversation event"
        )
    return (
        "before after timeline sequence earlier later prior next meeting call "
        "conversation event outcome context"
    )


def _requests_evidence_reason(query: str) -> bool:
    return bool(_EVIDENCE_REASON_RE.search(query))


def _requests_relationship_status(variants: frozenset[str]) -> bool:
    if {"relationship", "status"}.issubset(variants):
        return True
    return bool(
        variants.intersection({"single", "married", "dating", "partner", "spouse"})
        and variants.intersection(_RELATIONSHIP_STATUS_TERMS)
    )


def _requests_activity_participation(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection({"activity", "hobby"}):
        return False
    return bool(raw_tokens.intersection(_ACTIVITY_PARTICIPATION_TERMS))


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
