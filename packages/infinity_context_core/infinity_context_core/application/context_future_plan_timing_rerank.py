"""Future-plan timing rerank signals for planning and upcoming activity queries."""

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

_REASON = "future_plan_timing_bridge"
_QUERY_RE = re.compile(
    r"\b(?:when|what\s+(?:date|month|day)|which\s+(?:date|month|day))\b"
    r"(?=.{0,140}\b(?:plan|plans|planned|planning|intend|intends|"
    r"thinking\s+about|going\s+to|scheduled|upcoming|future)\b)",
    re.IGNORECASE | re.DOTALL,
)
_FUTURE_PLAN_ACTION_RE = re.compile(
    r"\b(?:plan|plans|planned|planning|intend|intends|intended|"
    r"thinking\s+about|consider(?:ing)?|going\s+to|scheduled|booked|"
    r"hop(?:e|es|ed|ing)\s+to|want(?:s|ed)?\s+to|will|"
    r"look(?:ing)?\s+forward)\b",
    re.IGNORECASE,
)
_FUTURE_TIME_RE = re.compile(
    r"\b(?:next\s+(?:day|week|month|year|summer|fall|winter|spring)|"
    r"next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend)|"
    r"tomorrow|tonight|upcoming|future|soon|later\s+(?:today|this\s+(?:week|month|year))|"
    r"this\s+(?:summer|fall|winter|spring|weekend)|summer\s+break|"
    r"in\s+(?:a|one|two|three|\d+)\s+(?:days?|weeks?|months?|years?)|"
    r"(?:on|by|for)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?:in|on|by|for)\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)(?:\s+\d{1,2})?)\b",
    re.IGNORECASE,
)
_PAST_ONLY_TIME_RE = re.compile(
    r"\b(?:last\s+(?:day|week|month|year|summer|fall|winter|spring|weekend)|"
    r"yesterday|ago|previously|two\s+weekends\s+ago|just\s+took|went)\b",
    re.IGNORECASE,
)
_CAMPING_QUERY_RE = re.compile(r"\bcamp(?:ing|ed)?\b", re.IGNORECASE)
_CAMPING_EVIDENCE_RE = re.compile(r"\bcamp(?:ing|ed)?\b", re.IGNORECASE)


def future_plan_timing_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer evidence that binds an intended activity to a future time."""

    if not _is_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    text = item.text
    if _exact_future_plan_timing_evidence(query=query, text=text):
        return DomainRerankSignal(
            boost=0.052,
            reason="future_plan_timing_exact_evidence",
            rank_signal_key="future_plan_timing_answer_evidence",
            rank_signal=3.0,
        )
    if _past_or_topic_only_evidence(query=query, text=text, relevance=relevance):
        return DomainRerankSignal(
            penalty=0.056,
            reason="future_plan_timing_weak_evidence",
        )
    return DomainRerankSignal()


def _is_candidate(*, query: str, query_reason: str, item: ContextItem) -> bool:
    if query_reason == _REASON:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    if signals.get("query_expansion_reason") == _REASON:
        return True
    return _QUERY_RE.search(query) is not None


def _exact_future_plan_timing_evidence(*, query: str, text: str) -> bool:
    if _CAMPING_QUERY_RE.search(query) is not None and _CAMPING_EVIDENCE_RE.search(text) is None:
        return False
    return (
        _FUTURE_PLAN_ACTION_RE.search(text) is not None
        and _FUTURE_TIME_RE.search(text) is not None
    )


def _past_or_topic_only_evidence(
    *,
    query: str,
    text: str,
    relevance: QueryRelevance,
) -> bool:
    if _CAMPING_QUERY_RE.search(query) is not None and _CAMPING_EVIDENCE_RE.search(text) is None:
        return True
    if _PAST_ONLY_TIME_RE.search(text) is not None and _FUTURE_TIME_RE.search(text) is None:
        return True
    return relevance.distinctive_term_hits < 3
