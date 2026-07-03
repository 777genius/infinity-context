"""Session-order helpers for temporal context retrieval."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.dto import ContextItem

_SESSION_ORDINAL_RE = re.compile(r"\bsession[_-](?P<session>\d{1,4})\b", re.IGNORECASE)
_DIALOGUE_TURN_RE = re.compile(r"\bD(?P<dialogue>\d{1,4}):\d{1,4}\b", re.IGNORECASE)


def temporal_session_recency_boost(item: ContextItem) -> float:
    """Return a bounded boost from LoCoMo-style session/dialogue ordinals."""

    session_order = _session_order(item)
    if session_order <= 0:
        return 0.0
    return round(min(0.026, 0.006 + min(session_order, 40) * 0.0008), 4)


def _session_order(item: ContextItem) -> int:
    values: list[int] = []
    for value in _session_order_source_values(item):
        values.extend(
            int(match.group("session")) for match in _SESSION_ORDINAL_RE.finditer(value)
        )
        values.extend(
            int(match.group("dialogue")) for match in _DIALOGUE_TURN_RE.finditer(value)
        )
    return max(values, default=0)


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
