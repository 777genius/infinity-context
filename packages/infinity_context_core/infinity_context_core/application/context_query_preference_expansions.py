"""Preference-oriented query expansion rules."""

from __future__ import annotations

_FAVORITE_PREFERENCE_EXPANSION = (
    "favorite favourite preferred prefer likes loves enjoys favorite thing "
    "chosen best top go-to one of favorites mentioned said described"
)

PREFERENCE_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"favorite", "book"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} book books novel novels series "
            "childhood reading story stories about genre author"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "series"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} book books novel novels series "
            "childhood reading story stories about genre author"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "dessert"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} dessert desserts dish dishes treat "
            "treats food meal recipe cooking show dairy-free ice cream cake sweet"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "dish"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} dish dishes dessert desserts food "
            "meal recipe cooking show hosted made ate"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "style"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} style type kind genre dance "
            "dancing painting art music movement choreography"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "memory"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} memory memories moment experience "
            "dance dancing performance class competition show first place"
        ),
        "favorite_preference_bridge",
    ),
    (
        frozenset({"favorite", "player"}),
        (
            f"{_FAVORITE_PREFERENCE_EXPANSION} player athlete sports basketball "
            "team game admire role model fan"
        ),
        "favorite_preference_bridge",
    ),
)
