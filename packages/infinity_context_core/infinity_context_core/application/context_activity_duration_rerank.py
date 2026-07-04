"""Activity and state duration rerank signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_query_duration import (
    requests_activity_duration_context,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

_ACTIVITY_DURATION_REASON = "decomposition_activity_duration"
_ACTIVITY_DURATION_EXACT_RE = re.compile(
    r"\b(?:for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+|over\s+)?"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"a|an|few|a\s+few|several|many|a\s+couple\s+of|couple\s+of)\s+"
    r"(?:years?|months?|weeks?|days?|decades?)|"
    r"since\s+(?:\d{4}|[A-Z][a-z]+\s+\d{4}|childhood|college|school|"
    r"last\s+(?:year|month|week|spring|summer|fall|autumn|winter))|"
    r"since\s+(?:(?:the\s+)?age\s+of\s+|i\s+was\s+)?"
    r"(?:\d{1,2}|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen)(?:\s+or\s+so)?|"
    r"(?:started|began)\s+(?:volunteering|working|living|using|playing|"
    r"running|training|practicing|creating|painting|drawing|studying|taking)\s+"
    r"(?:(?:in|during|around)\s+(?:\d{4}|[A-Z][a-z]+)|"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:years?|months?|weeks?|days?)\s+ago)|"
    r"has\s+been\s+(?:volunteering|working|living|using|playing|running|"
    r"training|practicing)\s+for)\b|"
    r"\b(?:уже\s+)?(?:\d+|один|одна|два|две|три|четыре|пять|шесть|"
    r"семь|восемь|девять|десять|несколько)\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)\b|"
    r"\bс\s+\d{4}\b|"
    r"\b(?:начал\w*|начала\w*)\s+"
    r"(?:волонтер\w*|работ\w*|жить|использ\w*|игра\w*)\s+"
    r"(?:в|с)\s+\d{4}\b",
    re.IGNORECASE,
)
_ACTIVITY_DURATION_WEAK_TOPIC_RE = re.compile(
    r"\b(?:volunteer(?:s|ed|ing)?|work(?:s|ed|ing)?|live(?:s|d|ing)?|"
    r"use(?:s|d|ing)?|play(?:s|ed|ing)?|run(?:s|ning)?|practice(?:s|d|ing)?|"
    r"train(?:s|ed|ing)?|stud(?:y|ied|ying)|tak(?:e|es|ing)|"
    r"art|creat(?:e|ed|ing)|paint(?:s|ed|ing)?|"
    r"draw(?:s|ing)?|have|has|had|own(?:s|ed)?|pets?|snakes?|dogs?|cats?)\b|"
    r"\b(?:волонтер\w*|работ\w*|жив[её]т|жил\w*|использ\w*|игра\w*)\b",
    re.IGNORECASE,
)


def activity_duration_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer explicit duration answers over topic-only activity mentions."""

    if not _is_activity_duration_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if _ACTIVITY_DURATION_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.03,
            reason="activity_duration_exact_evidence",
        )
    if _ACTIVITY_DURATION_WEAK_TOPIC_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.046,
            reason="activity_duration_weak_evidence",
        )
    if relevance.distinctive_term_hits < 4:
        return DomainRerankSignal(
            penalty=0.034,
            reason="activity_duration_weak_evidence",
        )
    return DomainRerankSignal()


def is_activity_duration_evidence_text(text: str) -> bool:
    """Return true when text carries both an activity/state and an explicit duration."""

    return (
        _ACTIVITY_DURATION_EXACT_RE.search(text) is not None
        and _ACTIVITY_DURATION_WEAK_TOPIC_RE.search(text) is not None
    )


def _is_activity_duration_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason == _ACTIVITY_DURATION_REASON:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    reason = signals.get("query_expansion_reason")
    if isinstance(reason, str) and reason == _ACTIVITY_DURATION_REASON:
        return True
    raw_tokens = frozenset(re.findall(r"\w+", query.casefold()))
    return requests_activity_duration_context(
        raw_tokens=raw_tokens,
        variants=raw_tokens,
    )
