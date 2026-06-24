"""Apply bounded domain rerank signals for memory context items."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_causal_reason_rerank import (
    causal_reason_rerank_signal,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    DomainRerankSignal,
    age_birthday_rerank_signal,
    aggregation_evidence_rerank_signal,
    birthplace_rerank_signal,
    commonality_rerank_signal,
    current_state_rerank_signal,
    current_goal_rerank_signal,
    event_sequence_rerank_signal,
    inventory_list_rerank_signal,
    positive_preference_rerank_signal,
    relationship_duration_rerank_signal,
    relationship_origin_rerank_signal,
    relationship_status_rerank_signal,
    state_transition_rerank_signal,
    support_network_rerank_signal,
    symbol_importance_rerank_signal,
)
from infinity_context_core.application.context_activity_duration_rerank import (
    activity_duration_rerank_signal,
)
from infinity_context_core.application.context_frequency_rerank import (
    frequency_recurrence_rerank_signal,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.dto import ContextItem


@dataclass(frozen=True)
class DomainRerankAdjustment:
    boost: float = 0.0
    penalty: float = 0.0
    reasons: tuple[str, ...] = ()


def apply_domain_rerank_signals(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
    has_multi_evidence_aggregation_candidate: bool = False,
) -> DomainRerankAdjustment:
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []
    for signal in _domain_rerank_signals(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
    ):
        if signal.boost > 0:
            boost += signal.boost
            reasons.append(signal.reason)
        if signal.penalty > 0:
            penalty += signal.penalty
            reasons.append(signal.reason)
    return DomainRerankAdjustment(boost=boost, penalty=penalty, reasons=tuple(reasons))


def _domain_rerank_signals(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
    has_multi_evidence_aggregation_candidate: bool,
) -> tuple[DomainRerankSignal, ...]:
    return (
        support_network_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        inventory_list_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        frequency_recurrence_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        activity_duration_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        event_sequence_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        current_goal_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        positive_preference_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        causal_reason_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        relationship_status_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        relationship_duration_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        relationship_origin_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        state_transition_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        current_state_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        age_birthday_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        birthplace_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        symbol_importance_rerank_signal(
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        commonality_rerank_signal(
            query=query,
            query_reason=query_reason,
            item=item,
            relevance=relevance,
        ),
        aggregation_evidence_rerank_signal(
            query=query,
            item=item,
            has_multi_evidence_competitor=has_multi_evidence_aggregation_candidate,
        ),
    )
