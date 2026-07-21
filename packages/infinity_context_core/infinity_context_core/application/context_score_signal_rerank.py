"""Score-signal helpers for deterministic context rerank policies."""

from __future__ import annotations

from infinity_context_core.application.context_internal_diagnostics import (
    item_score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem


def score_signal_reason(item: ContextItem) -> str:
    return item_score_signal_reason(item)


def matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    return query_reason == target_reason or score_signal_reason(item) == target_reason
