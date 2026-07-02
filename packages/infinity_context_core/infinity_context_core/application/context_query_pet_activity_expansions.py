"""Pet care and activity query expansion rules."""

from __future__ import annotations

_DOG_ACTIVITY_CARE_EXPANSION = (
    "dog dogs puppy pup pet pets care training class classes course positive "
    "reinforcement practice discipline command commands leash walk walks walking "
    "dog park playdate playdates park games fetch run running backyard indoor "
    "area breed size living space apartment open space grooming looking good "
    "pet store childhood family dog memories"
)

PET_ACTIVITY_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"dogs", "classes"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "training"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "care"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "park"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "park"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "walk"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "walks"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"childhood", "dog"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "memories"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "breed"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "type"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
)
