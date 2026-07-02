"""Vehicle interest and work query expansion rules."""

from __future__ import annotations

_VEHICLE_INTEREST_EXPANSION = (
    "car cars vehicle vehicles auto automobile drive driving owned owns got bought "
    "Prius Subaru Forester Dodge Charger brand make model type kind classic muscle "
    "restoration restore restored repair fixed shop garage mechanic engines engineering "
    "modification modifications custom mod workshop project projects passion hobby "
    "work working satisfying unique old car knowledge techniques"
)

VEHICLE_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"car", "drive"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "type"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"cars", "type"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "brand"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "work"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"cars", "work"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "modification"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "restoration"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "restored"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "fixed"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"car", "like"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"engines", "work"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
    (
        frozenset({"dodge", "subaru"}),
        _VEHICLE_INTEREST_EXPANSION,
        "vehicle_interest_bridge",
    ),
)
