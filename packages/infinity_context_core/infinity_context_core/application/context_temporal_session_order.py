"""Session-order helpers for temporal context retrieval."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.dto import ContextItem

_SESSION_ORDINAL_RE = re.compile(
    r"\bsession(?:[\s_-]+)(?P<session>\d{1,4})\b", re.IGNORECASE
)
_DIALOGUE_TURN_RE = re.compile(r"\bD(?P<dialogue>\d{1,4}):\d{1,4}\b", re.IGNORECASE)


def temporal_session_recency_boost(item: ContextItem) -> float:
    """Return a bounded boost from LoCoMo-style session/dialogue ordinals."""

    session_order = max(temporal_session_orders(item), default=0)
    if session_order <= 0:
        return 0.0
    return round(min(0.026, 0.006 + min(session_order, 40) * 0.0008), 4)


def temporal_session_orders(item: ContextItem) -> tuple[int, ...]:
    """Return LoCoMo-style session/dialogue ordinals visible on an item."""

    return _session_orders_from_values(_session_order_source_values(item))


def temporal_session_orders_from_query(query: str) -> tuple[int, ...]:
    """Return explicit session/dialogue ordinals requested by a query."""

    return _session_orders_from_values((query,))


def _session_order_source_values(item: ContextItem) -> tuple[str, ...]:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    values = [
        item.item_id,
        item.text,
        str(diagnostics.get("source_id") or ""),
        str(provenance.get("source_id") or ""),
    ]
    values.extend(str(ref.source_id or "") for ref in item.source_refs)
    return tuple(value for value in values if value)


def _session_orders_from_values(values: tuple[str, ...]) -> tuple[int, ...]:
    orders: dict[int, None] = {}
    for value in values:
        for match in _SESSION_ORDINAL_RE.finditer(value):
            orders.setdefault(int(match.group("session")), None)
        for match in _DIALOGUE_TURN_RE.finditer(value):
            orders.setdefault(int(match.group("dialogue")), None)
    return tuple(orders)
