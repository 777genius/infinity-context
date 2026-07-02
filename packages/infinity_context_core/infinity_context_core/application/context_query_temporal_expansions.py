"""General temporal query expansion rules."""

from __future__ import annotations

_GENERAL_TEMPORAL_EVENT_EXPANSION = (
    "when date dates time timeline session day weekday week month year recently "
    "yesterday last before after ago start started join joined went go attend "
    "attended event happened occurred finished received got made took hosted "
    "launched opened lost job trip visit"
)

TEMPORAL_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"when"}),
        _GENERAL_TEMPORAL_EVENT_EXPANSION,
        "general_temporal_event_bridge",
    ),
)
