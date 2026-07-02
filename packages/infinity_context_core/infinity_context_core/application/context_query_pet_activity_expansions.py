"""Pet care and activity query expansion rules."""

from __future__ import annotations

_DOG_ACTIVITY_CARE_EXPANSION = (
    "dog dogs puppy pup pet pets care training class classes course positive "
    "reinforcement practice discipline command commands leash walk walks walking "
    "dog park playdate playdates park games fetch run running backyard indoor "
    "area breed size living space apartment open space grooming looking good "
    "pet store childhood family dog memories"
)
_PET_MEMORY_EXPANSION = (
    "pet dog puppy beloved companion goodbye passed away died loss grief remember "
    "memorial memory memories honor honour tribute keepsake photo picture collar "
    "paw print stuffed animal toy name named childhood family Michigan rescue dog "
    "values responsibility kindness compassion teach kids"
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
    (
        frozenset({"pet", "goodbye"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
    (
        frozenset({"pet", "honor"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
    (
        frozenset({"pet", "memories"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
    (
        frozenset({"dog", "remember"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
    (
        frozenset({"dog", "michigan"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
    (
        frozenset({"rescue", "dog"}),
        _PET_MEMORY_EXPANSION,
        "pet_memory_bridge",
    ),
)
