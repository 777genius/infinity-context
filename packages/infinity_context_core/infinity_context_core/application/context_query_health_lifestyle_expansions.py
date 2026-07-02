"""Health, stress, and lifestyle issue query expansion rules."""

from __future__ import annotations

_HEALTH_LIFESTYLE_EXPANSION = (
    "health issue health issues health scare health scares incident incidents "
    "heart palpitation palpitations shocked lifestyle change dietary changes "
    "healthy meals snacks unhealthy snacks grocery store supermarket frustrating "
    "recurring issue electronics issue phone problem device fitness goals gym "
    "progress workout working out checkup checkups knee injury knee issue healing "
    "stress reliever stress relief stress-buster stress buster coping relax "
    "healthy lifestyle take care serious motivation"
)

HEALTH_LIFESTYLE_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"health", "issue"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"health", "scare"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"health", "incidents"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"heart", "palpitation"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"health", "checkups"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"healthy", "meals"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"unhealthy", "snacks"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"grocery", "issue"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"supermarket", "issue"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"electronics", "issue"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"fitness", "goals"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"gym", "progress"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"knee", "issue"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"stress", "reliever"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
    (
        frozenset({"stress", "buster"}),
        _HEALTH_LIFESTYLE_EXPANSION,
        "health_lifestyle_bridge",
    ),
)
