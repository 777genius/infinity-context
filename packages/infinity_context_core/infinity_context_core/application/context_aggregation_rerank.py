"""Aggregation evidence rerank policy."""

from __future__ import annotations

import re

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.context_domain_rerank_types import DomainRerankSignal
from infinity_context_core.application.dto import ContextItem

_AGGREGATION_RETRIEVAL_SOURCE = "keyword_aggregation_chunks"
_AGGREGATION_COUNT_QUERY_RE = re.compile(
    r"\b(?:how\s+many|number\s+of|count|total|times?)\b|"
    r"\b(?:сколько|количество|число|раз)\b",
    re.IGNORECASE,
)
_AGGREGATION_LIST_QUERY_RE = re.compile(
    r"\b(?:what|which|where)\b(?=.{0,80}\b(?:items?|things?|countries|places|"
    r"types?|kinds?|events?|activities|bands?|artists?|shelters?|causes?|people|"
    r"foods?|recipes?|meals?|dishes?)\b)|"
    r"\b(?:какие|какой|где|кого|кому)\b",
    re.IGNORECASE | re.DOTALL,
)
_AGGREGATION_NUMERIC_ANSWER_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|once|twice|"
    r"couple|several|multiple|another|again)\b|"
    r"\b(?:один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|"
    r"десять|раз|дважды|несколько|много|ещ[её])\b",
    re.IGNORECASE,
)
_AGGREGATION_MARKER_RE = re.compile(r"\bD\d+:\d+\b")


def aggregation_evidence_rerank_signal(
    *,
    query: str,
    item: ContextItem,
    has_multi_evidence_competitor: bool = False,
) -> DomainRerankSignal:
    if not _is_aggregation_query(query):
        return DomainRerankSignal()
    is_list_query = _is_aggregation_list_query(query)
    answer_slot_count = aggregation_answer_slot_count(query=query, text=item.text)
    if answer_slot_count >= 2:
        if is_list_query:
            return DomainRerankSignal(
                boost=0.058,
                reason="aggregation_list_slot_diverse_evidence",
            )
        return DomainRerankSignal(
            boost=0.044,
            reason="aggregation_slot_diverse_evidence",
        )
    if _is_aggregation_context_item(item):
        if _aggregation_evidence_count(item) >= 2:
            if is_list_query:
                return DomainRerankSignal(
                    boost=0.046,
                    reason="aggregation_list_multi_evidence",
                )
            return DomainRerankSignal(boost=0.034, reason="aggregation_multi_evidence")
        if is_list_query:
            return DomainRerankSignal(boost=0.018, reason="aggregation_list_evidence")
        return DomainRerankSignal(boost=0.018, reason="aggregation_evidence")
    if _AGGREGATION_COUNT_QUERY_RE.search(query) and _is_single_weak_count_evidence(item):
        return DomainRerankSignal(penalty=0.055, reason="aggregation_single_evidence_noise")
    if (
        is_list_query
        and has_multi_evidence_competitor
        and _is_single_list_evidence(query=query, item=item)
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="aggregation_list_single_evidence_incomplete",
        )
    return DomainRerankSignal()


def has_multi_evidence_aggregation_candidate(
    *,
    query: str,
    items: tuple[ContextItem, ...],
) -> bool:
    if not _is_aggregation_query(query):
        return False
    return any(
        (
            _is_aggregation_context_item(item)
            and _aggregation_evidence_count(item) >= 2
        )
        or aggregation_answer_slot_count(query=query, text=item.text) >= 2
        for item in items
    )


def _is_aggregation_query(query: str) -> bool:
    return bool(
        _AGGREGATION_COUNT_QUERY_RE.search(query)
        or _AGGREGATION_LIST_QUERY_RE.search(query)
    )


def _is_aggregation_list_query(query: str) -> bool:
    return _AGGREGATION_LIST_QUERY_RE.search(query) is not None


def _is_aggregation_context_item(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    retrieval_source = str(diagnostics.get("retrieval_source") or "").strip()
    if retrieval_source == _AGGREGATION_RETRIEVAL_SOURCE:
        return True
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, list | tuple | set):
        return _AGGREGATION_RETRIEVAL_SOURCE in {str(source) for source in sources}
    return False


def _aggregation_evidence_count(item: ContextItem) -> int:
    marker_count = len(set(_AGGREGATION_MARKER_RE.findall(item.text)))
    return max(marker_count, len(item.source_refs))


def _is_single_weak_count_evidence(item: ContextItem) -> bool:
    if _aggregation_evidence_count(item) >= 2:
        return False
    return _AGGREGATION_NUMERIC_ANSWER_RE.search(item.text) is None


def _is_single_list_evidence(*, query: str, item: ContextItem) -> bool:
    if _is_aggregation_context_item(item) or _aggregation_evidence_count(item) >= 2:
        return False
    if aggregation_answer_slot_count(query=query, text=item.text) == 1:
        return True
    return not _list_evidence_looks_multi_value(item.text)


def _list_evidence_looks_multi_value(text: str) -> bool:
    if len(set(_AGGREGATION_MARKER_RE.findall(text))) >= 2:
        return True
    if len(re.findall(r"\b(?:also|another|as\s+well|and)\b", text, re.IGNORECASE)) >= 1:
        return True
    return ";" in text or len(re.findall(r",", text)) >= 2
