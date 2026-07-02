"""Sports career and training query expansion rules."""

from __future__ import annotations

_SPORTS_ACTIVITY_EXPANSION = (
    "sports sport basketball career goals training skills team teammates game "
    "season points assists career-high high school introduced recovery ankle "
    "injury strength flexibility surfing surf surfed waves supplement drill "
    "practice mistake overcome performance city"
)

SPORTS_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"basketball"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"surfing"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"points", "game"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"career", "high"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"assists"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"ankle", "injury"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
    (
        frozenset({"strength", "flexibility"}),
        _SPORTS_ACTIVITY_EXPANSION,
        "sports_activity_bridge",
    ),
)
