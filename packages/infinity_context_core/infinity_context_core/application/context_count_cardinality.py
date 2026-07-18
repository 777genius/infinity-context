"""Count/cardinality evidence helpers for context ranking."""

from __future__ import annotations

import re

from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.domain.aggregation_admission import AggregationIntent

_CARDINALITY_VALUE = (
    r"(?<![:\w])\d{1,3}(?![:\w])|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|couple|once|twice)\b"
)
_COUNT_OBJECT_VALUE = (
    r"(?<![:\w])\d{1,3}(?![:\w])|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|couple)\b"
)
_COUNT_NOUN = r"[A-Za-z][A-Za-z'_-]{2,}"
_VALUE_WITH_OBJECT_RE = re.compile(
    rf"(?:{_COUNT_OBJECT_VALUE})\s+(?:{_COUNT_NOUN}\s+){{0,2}}{_COUNT_NOUN}",
    re.IGNORECASE,
)
_COUNT_TIMES_RE = re.compile(
    rf"(?:{_CARDINALITY_VALUE})\s+times?\b",
    re.IGNORECASE,
)
_COUNT_ADVERB_RE = re.compile(
    r"\b(?:once|twice)\b(?!\s+(?:a|per|daily|weekly|monthly|yearly|annually)\b)",
    re.IGNORECASE,
)
_COUNT_RANGE_RE = re.compile(r"\bonce\s+or\s+twice\b", re.IGNORECASE)
_COUNT_LABEL_VALUE_RE = re.compile(
    rf"\b(?:answer|count|number|total|cardinality)\b"
    rf".{{0,32}}(?:{_CARDINALITY_VALUE})",
    re.IGNORECASE | re.DOTALL,
)
_BOTH_PAIR_RE = re.compile(
    r"\bboth\s+"
    r"(?!before\b|after\b|during\b)"
    r"[A-Za-z][A-Za-z'_-]{1,40}(?:\s+[A-Za-z][A-Za-z'_-]{1,40}){0,3}"
    r"\s+and\s+"
    r"(?!before\b|after\b|during\b|then\b)"
    r"[A-Za-z][A-Za-z'_-]{1,40}(?:\s+[A-Za-z][A-Za-z'_-]{1,40}){0,3}\b",
    re.IGNORECASE,
)
_COUNT_AGGREGATION_QUERY_RE = re.compile(
    r"\b(how many|number of|count|total)\b",
    re.IGNORECASE,
)
_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+"
    r"(?:[\w+.-]+\s+){0,4}"
    r"(?:areas?|causes?|cities|countries|events?|activities?|hobbies|"
    r"instruments?|items?|martial\s+arts|people|places?|shelters?|states?|"
    r"traits?|books?|songs?|artists?|bands?|foods?|desserts?|pets?|projects?|tasks?|"
    r"types?|kinds?)\b|"
    r"\b(?:list|name|show)\b(?=.{0,100}\b(?:all|both|areas?|causes?|cities|"
    r"countries|events?|activities?|hobbies|instruments?|items?|martial\s+arts|"
    r"people|places?|shelters?|states?|traits?|books?|songs?|artists?|bands?|"
    r"foods?|desserts?|pets?|projects?|tasks?|types?|kinds?)\b)|"
    r"\b(?:all|both)\b(?=.{0,100}\b(?:areas?|causes?|cities|countries|events?|"
    r"activities?|hobbies|instruments?|items?|martial\s+arts|people|places?|"
    r"shelters?|states?|traits?|books?|songs?|artists?|bands?|foods?|desserts?|"
    r"pets?|projects?|tasks?|types?|kinds?)\b)|"
    r"\bwho\b(?=.{0,120}\b(?:friends?|people|person|volunteer(?:s|ed|ing)?|"
    r"met|helped|worked\s+with|customers?|clients?|colleagues?|teammates?)\b)|"
    r"\b(?:has|have|did|does)\s+\w{2,40}\s+"
    r"(?:bought|attended|joined|visited|played|shared|mentioned|done|used)\b|"
    r"\b(?:какие|какие\s+именно|что\s+за)\s+"
    r"(?:вещи|события|активности|занятия|инструменты|черты|места|книги|задачи)\b",
    re.IGNORECASE,
)
_WHERE_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,100}\b(?:been|friend|friends|go|gone|made|meet|met|"
    r"vacation(?:ed)?|visited|went)\b)|"
    r"\bгде\b(?=.{0,100}\b(?:друз|ездил|ездила|ездили|посещал|посещала|"
    r"посещали|познакомил|познакомила|познакомили)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SEQUENCE_AGGREGATION_QUERY_RE = re.compile(
    r"\b(?:in\s+(?:what|which)\s+order|(?:what|which|the)\s+order\s+of|"
    r"order\s+of.{0,120}(?:earliest|first).{0,60}(?:latest|last)|"
    r"in\s+(?:the\s+)?order(?:\s+from)?|"
    r"ordered\s+(?:events?|steps?)|"
    r"sequence\s+of|chronological(?:ly)?|timeline|what\s+happened\s+"
    r"(?:before|after|next)|(?:first|initially).{0,120}(?:then|next|after))\b",
    re.IGNORECASE | re.DOTALL,
)
_SEQUENCE_QUERY_PLAN_REASONS = frozenset(
    {
        "decomposition_event_sequence",
        "after_event_temporal_bridge",
        "before_event_temporal_bridge",
    }
)


def has_exact_count_cardinality_evidence(text: str) -> bool:
    """Return true when text states a count, not only an enumerated list."""

    if not text.strip():
        return False
    has_standalone_count_adverb = bool(_COUNT_ADVERB_RE.search(text)) and not bool(
        _COUNT_RANGE_RE.search(text)
    )
    return bool(
        _VALUE_WITH_OBJECT_RE.search(text)
        or _COUNT_TIMES_RE.search(text)
        or has_standalone_count_adverb
        or _COUNT_LABEL_VALUE_RE.search(text)
        or _BOTH_PAIR_RE.search(text)
    )


def keyword_aggregation_intent(
    query: str,
    *,
    query_plan: QueryExpansionPlan | None = None,
) -> AggregationIntent | None:
    """Normalize generic count, list, and sequence requests for admission policy."""

    if _COUNT_AGGREGATION_QUERY_RE.search(query):
        return AggregationIntent.COUNT
    if _SEQUENCE_AGGREGATION_QUERY_RE.search(query):
        return AggregationIntent.SEQUENCE
    if query_plan is not None and any(
        expansion.reason in _SEQUENCE_QUERY_PLAN_REASONS
        for expansion in query_plan.retrieval_queries
    ):
        return AggregationIntent.SEQUENCE
    if requests_list_aggregation(query):
        return AggregationIntent.LIST
    return None


def requests_list_aggregation(query: str) -> bool:
    """Return whether the query explicitly requests a generic list/inventory."""

    return bool(
        _LIST_AGGREGATION_QUERY_RE.search(query) or _WHERE_LIST_AGGREGATION_QUERY_RE.search(query)
    )


def keyword_aggregation_query_kind(
    query: str,
    *,
    query_plan: QueryExpansionPlan | None = None,
) -> str:
    """Return the normalized intent value for diagnostics and compatibility."""

    intent = keyword_aggregation_intent(query, query_plan=query_plan)
    return intent.value if intent else ""
