"""Game and gaming event query expansion rules."""

from __future__ import annotations

_GAME_DETAIL_EXPANSION = (
    "game games gaming video game videogame console pc nintendo play played playing "
    "favorite recommend recommended tournament tournaments convention esports online "
    "team teammates party room setup lighting equipment headphones controller keyboard "
    "Xenoblade Chronicles Cyberpunk Valorant CS:GO Counter Strike Among Us Codenames "
    "board game tabletop card game strategy game RPG role-playing futuristic setting "
    "gameplay nonstop purpose fundraiser charity friends invited"
)

GAME_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"game", "convention"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"game", "nonstop"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"game", "xenoblade"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"game", "tournament"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "tournament"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "party"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "room"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "team"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"games", "favorite"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"games", "played"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"games", "partner"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "equipment"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
    (
        frozenset({"gaming", "headphones"}),
        _GAME_DETAIL_EXPANSION,
        "game_detail_bridge",
    ),
)
