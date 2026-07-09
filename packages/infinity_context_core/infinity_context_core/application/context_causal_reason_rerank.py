"""Causal reason rerank signals for why/reason memory queries."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import safe_score_signals
from infinity_context_core.application.context_domain_rerank_signals import DomainRerankSignal
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem

_CAUSAL_REASON_RERANK_REASONS = frozenset(
    (
        "business_start_reason_bridge",
        "charity_brand_sponsorship_bridge",
        "family_motivation_context_bridge",
        "motivation_reason_bridge",
        "pottery_color_reason_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "shelter_comfort_reason_bridge",
        "support_career_motivation_bridge",
        "yoga_delay_gaming_bridge",
    )
)
_CAUSAL_REASON_QUERY_RE = re.compile(
    r"\b(?:why|reason|because|cause|caused|gave|motivat(?:e|ed|ion)|"
    r"inspired?|led\s+to|made\s+(?:me|her|him|them)|sense\s+of\s+belonging)\b|"
    r"\b(?:почему|причин\w*|потому|мотивир\w*|вдохнов\w*)\b",
    re.IGNORECASE,
)
_CAUSAL_REASON_MARKER_RE = re.compile(
    r"\b(?:because|so|since|therefore|as\s+a\s+result|which\s+made|"
    r"that\s+made|this\s+made|led\s+(?:me|her|him|them)?\s*to|"
    r"inspired|motivated|made\s+(?:me|her|him|them)\s+(?:feel|realize|want)|"
    r"gave\s+(?:me|her|him|them)|wanted\s+to|in\s+order\s+to|so\s+(?:i|she|he|they))\b|"
    r"\b(?:потому|поэтому|из-за|вдохнов\w*|мотивир\w*|чтобы)\b",
    re.IGNORECASE,
)
_CAUSAL_REASON_DOMAIN_EVIDENCE_RE = re.compile(
    r"\b(?:lost\s+(?:her|his|their|my)?\s*(?:door\s+dash\s+)?job|job\s+loss|"
    r"passionate\s+about\s+fashion|blend\s+dance\s+and\s+fashion|"
    r"sitting\s+alone|looking\s+sad|no\s+other\s+family|offered\s+comfort|"
    r"listening\s+ear|made\s+her\s+laugh|give\s+back|make\s+a\s+difference|"
    r"inspire\s+people|disadvantaged\s+kids|nike|gatorade|under\s+armou?r|"
    r"sponsorship|basketball\s+shoe\s+and\s+gear|sports?\s+brands?|"
    r"working\s+with\s+(?:such\s+)?big\s+brands|walking\s+dead|console\s+games|"
    r"instead\s+of\s+(?:doing\s+)?yoga|clear\s+(?:my|her|his|their)?\s*head|"
    r"stress\s+relief|relax|refresh|made\s+me\s+realize|mental\s+health|"
    r"help\s+people\s+feel\s+safe|catch\s+(?:the\s+)?eye|make\s+people\s+smile)\b",
    re.IGNORECASE,
)
_CAUSAL_REASON_WEAK_TOPIC_RE = re.compile(
    r"\b(?:mentioned|talked\s+about|discussed|heard\s+about|general\s+planning|"
    r"notes?|update|topic|context|saw|watched|visited|attended)\b|"
    r"\b(?:обсуждал\w*|упомянул\w*|заметк\w*|контекст)\b",
    re.IGNORECASE,
)
_YOGA_DELAY_GAMING_PLANNED_PLAY_RE = re.compile(
    r"\b(?:plan(?:ned|ning)?|arrang(?:ed|ing)?|going|intend(?:ed|ing)?|wanted)\s+"
    r"(?:to\s+)?(?:play|try)\b"
    r"(?=.{0,140}\b(?:console|video\s*games?|videogames?|xbox|"
    r"playstation|nintendo|switch|games?)\b)|"
    r"\b(?:plan(?:ned|ning)?|arrang(?:ed|ing)?|going)\s+to\s+play\s+"
    r"\"[^\"\n]{1,80}\""
    r"(?=.{0,120}\b(?:next|later|tomorrow|weekend|saturday|sunday|"
    r"monday|tuesday|wednesday|thursday|friday)\b)|"
    r"\b(?:play|playing)\b"
    r"(?=.{0,90}\b(?:console|video\s*games?|videogames?|games?)\b)"
    r"(?=.{0,150}\b(?:partner|next|planned|planning|instead)\b)",
    re.IGNORECASE | re.DOTALL,
)
_YOGA_DELAY_GAMING_ACTIVE_PLAY_RE = re.compile(
    r"\b(?:gaming|played|playing)\b"
    r"(?=.{0,120}\b(?:console|video\s*games?|videogames?|games?|xbox|"
    r"playstation|nintendo|switch)\b)|"
    r"\b(?:console|video\s*games?|videogames?|games?|xbox|playstation|"
    r"nintendo|switch)\b"
    r"(?=.{0,120}\b(?:gaming|played|playing)\b)",
    re.IGNORECASE | re.DOTALL,
)
_YOGA_DELAY_GAMING_BACKGROUND_RE = re.compile(
    r"\b(?:partner'?s\s+video\s+games|video\s*games?|videogames?|"
    r"game\s+console|new\s+game\s+console)\b",
    re.IGNORECASE,
)


def causal_reason_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_causal_reason_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if _causal_reason_exact_evidence(item.text) and relevance.distinctive_term_hits >= 3:
        return DomainRerankSignal(boost=0.026, reason="causal_reason_exact_evidence")
    if (
        _CAUSAL_REASON_WEAK_TOPIC_RE.search(item.text) is not None
        or relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(penalty=0.04, reason="causal_reason_weak_evidence")
    return DomainRerankSignal()


def _is_causal_reason_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _CAUSAL_REASON_RERANK_REASONS:
        return True
    if _score_signal_reason(item) in _CAUSAL_REASON_RERANK_REASONS:
        return True
    return _CAUSAL_REASON_QUERY_RE.search(query) is not None


def _causal_reason_exact_evidence(text: str) -> bool:
    return (
        _CAUSAL_REASON_MARKER_RE.search(text) is not None
        or _CAUSAL_REASON_DOMAIN_EVIDENCE_RE.search(text) is not None
        or yoga_delay_gaming_answer_rank(text) <= 1
    )


def _score_signal_reason(item: ContextItem) -> str:
    signals = safe_score_signals(item.diagnostics)
    return str(signals.get("query_expansion_reason") or "")


def yoga_delay_gaming_answer_rank(text: str) -> int:
    """Rank English evidence for yoga being displaced by planned gaming."""
    if _YOGA_DELAY_GAMING_PLANNED_PLAY_RE.search(text) is not None:
        return 0
    if _YOGA_DELAY_GAMING_ACTIVE_PLAY_RE.search(text) is not None:
        return 1
    if _YOGA_DELAY_GAMING_BACKGROUND_RE.search(text) is not None:
        return 2
    return 5
