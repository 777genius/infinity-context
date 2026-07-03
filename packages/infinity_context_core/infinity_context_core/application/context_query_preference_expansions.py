"""Preference-oriented query expansion rules."""

from __future__ import annotations

_FAVORITE_PREFERENCE_EXPANSION = (
    "favorite favourite preferred prefer likes loves enjoys favorite thing "
    "chosen best top go-to one of favorites mentioned said described"
)

_PREFERENCE_REASON_EXPANSION = (
    "reason because cause preference prefer preferred chose chosen picked selected "
    "made decide decided liked enjoyed wanted mattered value fit better over instead"
)

PREFERENCE_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"reason", "prefer"}),
        _PREFERENCE_REASON_EXPANSION,
        "preference_reason_bridge",
    ),
    (
        frozenset({"made", "prefer"}),
        _PREFERENCE_REASON_EXPANSION,
        "preference_reason_bridge",
    ),
    (
        frozenset({"reason", "preference"}),
        _PREFERENCE_REASON_EXPANSION,
        "preference_reason_bridge",
    ),
    (
        frozenset({"reason", "preferred"}),
        _PREFERENCE_REASON_EXPANSION,
        "preference_reason_bridge",
    ),
    (
        frozenset({"reason", "preferr"}),
        _PREFERENCE_REASON_EXPANSION,
        "preference_reason_bridge",
    ),
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
