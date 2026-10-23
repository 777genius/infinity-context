"""Legacy domain rerank DTO and shared reason matching; distinct from the newer DTO."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem


@dataclass(frozen=True)
class DomainRerankSignal:
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""
    rank_signal_key: str = ""
    rank_signal: float = 0.0

# Keep the historical public type identity for introspection and old pickles.
DomainRerankSignal.__module__ = "infinity_context_core.application.context_domain_rerank_signals"

def _matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    return query_reason == target_reason or _score_signal_reason(item) == target_reason
