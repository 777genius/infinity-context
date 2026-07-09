"""Identity-specific deterministic rerank policy."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_types import DomainRerankSignal
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

_IDENTITY_RERANK_REASONS = frozenset(
    (
        "decomposition_identity_attribute",
        "identity_bridge",
    )
)
_IDENTITY_QUERY_RE = re.compile(
    r"\b(?:identity|gender\s+identity|identify|identifies|true\s+self)\b|"
    r"\b(?:transgender|trans|queer|nonbinary)\b(?=.{0,80}\b(?:identity|person|"
    r"woman|man|self)\b)",
    re.IGNORECASE | re.DOTALL,
)
_IDENTITY_EXACT_RE = re.compile(
    r"\b(?:identif(?:y|ies|ied)\s+as|"
    r"(?:is|am|are|was|were)\s+(?:a\s+)?(?:transgender|trans|queer|nonbinary|"
    r"gay|lesbian|bisexual)\b|"
    r"transgender\s+woman|trans\s+woman|transgender\s+man|trans\s+man|"
    r"gender\s+identity|true\s+self|my\s+identity|her\s+identity|"
    r"his\s+identity|their\s+identity)\b",
    re.IGNORECASE,
)
_IDENTITY_TOPIC_WEAK_RE = re.compile(
    r"\b(?:support\s+group|pride\s+(?:flag|mural|event|parade)|"
    r"transgender\s+stories|lgbtq?\s+(?:event|community|group)|"
    r"support(?:s|ed|ive|ing)?\s+(?:the\s+)?(?:transgender|lgbtq?|queer)\s+"
    r"(?:community|events?|rights?))\b",
    re.IGNORECASE,
)


def identity_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_identity_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _IDENTITY_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.042,
            reason="identity_exact_evidence",
        )
    if _IDENTITY_TOPIC_WEAK_RE.search(item.text) is not None or relevance.distinctive_term_hits < 4:
        return DomainRerankSignal(
            penalty=0.04,
            reason="identity_topic_only_evidence",
        )
    return DomainRerankSignal()


def _is_identity_candidate(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _IDENTITY_RERANK_REASONS:
        return True
    if query and _IDENTITY_QUERY_RE.search(query) is not None:
        return True
    return _score_signal_reason(item) in _IDENTITY_RERANK_REASONS
