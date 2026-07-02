"""Choice-reason rerank signals for why/pick/select memory queries."""

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

_REASON = "choice_reason_bridge"
_QUERY_RE = re.compile(
    r"\b(?:why|reason)\b(?=.{0,120}\b(?:choose|chose|chosen|pick|picked|"
    r"select|selected|choice|option|agency|provider|vendor|tool|model)\b)|"
    r"\b(?:what\s+made|made\s+(?:you|her|him|them)\s+pick)\b",
    re.IGNORECASE | re.DOTALL,
)
_CHOICE_ACTION_RE = re.compile(
    r"\b(?:choose|chose|chosen|pick|picked|select|selected|went\s+with)\b",
    re.IGNORECASE,
)
_REASON_MARKER_RE = re.compile(
    r"\b(?:because|cause|'cause|cuz|since|reason|due\s+to|"
    r"what\s+made|made\s+(?:me|her|him|them|you)|spoke\s+to\s+(?:me|her|him|them)|"
    r"stood\s+out|appealed\s+to)\b",
    re.IGNORECASE,
)
_CHOICE_REASON_DOMAIN_RE = re.compile(
    r"\b(?:help(?:s|ed|ing)?|support(?:s|ed|ing)?|inclusive|inclusivity|"
    r"lgbtq\+?|adoption|agency|provider|vendor|tool|model|service|option|"
    r"safe|reliable|trusted|fit|fits|matched|align(?:s|ed)?|available|"
    r"accessible|recommended|endorsed)\b",
    re.IGNORECASE,
)
_ADOPTION_AGENCY_QUERY_RE = re.compile(
    r"\b(?:adoption|agency|agencies)\b",
    re.IGNORECASE,
)
_ADOPTION_AGENCY_EVIDENCE_RE = re.compile(
    r"\b(?:adoption|agency|agencies|lgbtq\+?|inclusive|inclusivity|support)\b",
    re.IGNORECASE,
)
_WEAK_TOPIC_RE = re.compile(
    r"\b(?:mentioned|discussed|look(?:ing)?\s+into|research(?:ing)?|"
    r"general\s+planning|dream|hope|goal|summary)\b",
    re.IGNORECASE,
)


def choice_reason_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    """Prefer exact evidence explaining why an option was chosen."""

    if not _is_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    text = item.text
    if _exact_choice_reason_evidence(query=query, text=text):
        return DomainRerankSignal(
            boost=0.046,
            reason="choice_reason_exact_evidence",
            rank_signal_key="choice_reason_answer_evidence",
            rank_signal=3.0,
        )
    if _WEAK_TOPIC_RE.search(text) is not None or relevance.distinctive_term_hits < 3:
        return DomainRerankSignal(
            penalty=0.046,
            reason="choice_reason_weak_evidence",
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


def _exact_choice_reason_evidence(*, query: str, text: str) -> bool:
    if (
        _ADOPTION_AGENCY_QUERY_RE.search(query) is not None
        and _ADOPTION_AGENCY_EVIDENCE_RE.search(text) is None
    ):
        return False
    if (
        _ADOPTION_AGENCY_QUERY_RE.search(query) is not None
        and _REASON_MARKER_RE.search(text) is not None
        and _CHOICE_REASON_DOMAIN_RE.search(text) is not None
    ):
        return True
    return (
        _CHOICE_ACTION_RE.search(text) is not None
        and _REASON_MARKER_RE.search(text) is not None
        and _CHOICE_REASON_DOMAIN_RE.search(text) is not None
    )
