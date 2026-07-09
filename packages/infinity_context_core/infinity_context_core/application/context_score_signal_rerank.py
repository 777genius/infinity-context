"""Score-signal helpers for deterministic context rerank policies."""

from __future__ import annotations

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.dto import ContextItem


def score_signal_reason(item: ContextItem) -> str:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return str(signals.get("query_expansion_reason") or "").strip()


def matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    return query_reason == target_reason or score_signal_reason(item) == target_reason
