"""Frequency and recurrence rerank signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

_FREQUENCY_REASON = "decomposition_frequency_recurrence"
_FREQUENCY_QUERY_RE = re.compile(
    r"\bhow\s+often\b|\b(?:frequency|cadence|regularly|recurring)\b|"
    r"\b(?:times?\s+(?:a|per)\s+(?:day|week|month|year))\b",
    re.IGNORECASE,
)
_RECURRENCE_EXACT_RE = re.compile(
    r"\b(?:(?:every|each)\s+(?:day|night|morning|afternoon|evening|weekday|"
    r"weekend|week|month|year|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)|"
    r"every\s+(?:two|three|four|five|six|\d{1,2})\s+"
    r"(?:days|weeks|months|years)|"
    r"every\s+(?:other|few)\s+(?:day|days|week|weeks|month|months|year|years)|"
    r"daily|weekly|monthly|yearly|annually|biweekly|fortnightly|"
    r"periodically|regularly|usually|often|"
    r"(?:once|twice|three|four|five|six|\d{1,2})\s+every\s+"
    r"(?:two|three|four|five|six|\d{1,2})\s+"
    r"(?:days|weeks|months|years)|"
    r"(?:once|twice|three|four|five|six|\d{1,2})\s+"
    r"(?:daily|weekly|monthly|yearly|annually)|"
    r"(?:once|twice|two|three|four|five|six|\d{1,2})\s+times?\s+(?:a|per)\s+"
    r"(?:day|week|month|year)|"
    r"(?:once|twice)\s+(?:a|per)\s+(?:day|week|month|year)|"
    r"(?:a\s+)?couple\s+(?:of\s+)?times?\s+(?:a|per)\s+(?:day|week|month|year)|"
    r"several\s+times?\s+(?:a|per)\s+(?:day|week|month|year)|"
    r"(?:on|most)\s+(?:weekdays|weekends|monday|mondays|tuesday|tuesdays|"
    r"wednesday|wednesdays|thursday|thursdays|friday|fridays|saturday|"
    r"saturdays|sunday|sundays)(?:\s+(?:mornings?|afternoons?|evenings?|"
    r"nights?))?)\b|"
    r"\b(?:кажд\w+\s+(?:день|недел\w*|месяц|год|утро|вечер|выходн\w*)|"
    r"ежедневно|еженедельно|ежемесячно|ежегодно|регулярно|обычно|часто|"
    r"(?:один|два|три|четыре|пять|шесть|\d{1,2})\s+раз(?:а)?\s+в\s+"
    r"(?:день|недел\w*|месяц|год))\b",
    re.IGNORECASE,
)
_ONE_TIME_EVENT_RE = re.compile(
    r"\b(?:once|one\s+time|one-time|single\s+time)\b(?!\s+(?:a|per)\b)|"
    r"\b(?:for\s+orientation|only\s+once|just\s+once|single\s+visit)\b|"
    r"\b(?:один\s+раз|только\s+раз|единожды)\b",
    re.IGNORECASE,
)
_GENERIC_TOPIC_RE = re.compile(
    r"\b(?:schedule|calendar|activity|event|meeting|volunteer|practice|training)\b"
    r"(?![^.]{0,80}\b(?:every|daily|weekly|monthly|regularly|usually|often|"
    r"times?\s+(?:a|per)|on\s+(?:weekdays|weekends|mondays|tuesdays|wednesdays|"
    r"thursdays|fridays|saturdays|sundays)|most\s+(?:weekdays|weekends))\b)",
    re.IGNORECASE,
)


def frequency_recurrence_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer evidence that answers recurrence, and demote one-off mentions."""

    if not _is_frequency_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RECURRENCE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.03,
            reason="frequency_recurrence_exact_evidence",
        )
    if _ONE_TIME_EVENT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.052,
            reason="frequency_recurrence_one_time_noise",
        )
    if _GENERIC_TOPIC_RE.search(item.text) is not None or relevance.distinctive_term_hits < 4:
        return DomainRerankSignal(
            penalty=0.036,
            reason="frequency_recurrence_weak_evidence",
        )
    return DomainRerankSignal()


def _is_frequency_candidate(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason == _FREQUENCY_REASON:
        return True
    if query and _FREQUENCY_QUERY_RE.search(query) is not None:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    reason = signals.get("query_expansion_reason")
    return isinstance(reason, str) and reason == _FREQUENCY_REASON
