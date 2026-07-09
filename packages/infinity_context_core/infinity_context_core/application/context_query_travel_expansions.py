"""Travel destination and place-detail query expansion rules."""

from __future__ import annotations

_TRAVEL_PLACE_DETAIL_EXPANSION = (
    "travel traveled travelling traveling trip trips road trip destination destinations "
    "visit visited visiting vacation abroad overseas country countries city cities "
    "place places stayed staying tickets booked recommended semester abroad itinerary "
    "tour photo photograph coastline views Rome Barcelona Paris Canada Japan Ireland "
    "Rio de Janeiro Universal Studios New York City"
)

TRAVEL_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"country", "visit"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "visited"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "visiting"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"countries", "visited"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "tickets"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "buy"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "during"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"country", "located"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"city", "traveling"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"city", "staying"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"city", "recommend"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"city", "featured"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"city", "at"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"cities", "travel"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"road", "trip"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"trip", "rome"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"trip", "barcelona"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"new", "york", "city"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"travel", "club"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"japan"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"canada"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"universal", "studios"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"rio", "janeiro"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
    (
        frozenset({"semester", "abroad"}),
        _TRAVEL_PLACE_DETAIL_EXPANSION,
        "trip_destination_bridge",
    ),
)
