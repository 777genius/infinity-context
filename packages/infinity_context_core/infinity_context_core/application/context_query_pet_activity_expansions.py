"""Pet care and activity query expansion rules."""

from __future__ import annotations

_DOG_ACTIVITY_CARE_EXPANSION = (
    "dog dogs puppy pup pet pets care training class classes course positive "
    "reinforcement practice discipline command commands leash walk walks walking "
    "dog park playdate playdates park games fetch run running backyard indoor "
    "area breed size living space apartment open space grooming looking good "
    "pet store childhood family dog memories ownership frustration companion "
    "companions bonding workshop shelter adopted adoption name named beds comfort "
    "snow trail hike active city dressed costume leash incident calm tricks dog-sitting"
)
_PET_MEMORY_EXPANSION = (
    "pet dog puppy beloved companion goodbye passed away died loss grief remember "
    "memorial memory memories honor honour tribute keepsake photo picture collar "
    "paw print stuffed animal toy name named childhood family Michigan rescue dog "
    "values responsibility kindness compassion teach kids"
)
_PET_INVENTORY_EXPANSION = (
    "pet pets dog dogs puppy pup name names named called adopted got new addition "
    "family companion owner belongs shelter rescue more recently has have"
)
_PET_OWNERSHIP_EXPANSION = (
    "owner owns has have belongs to adopted got named called name names"
)

PET_ACTIVITY_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"pups"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "ownership"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pet", "dog"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "dresses"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "done"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pets", "view"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pets", "bonding"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pet", "store"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "backyard"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "comfort"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "snow"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "leash"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "active"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "stress"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "discipline"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "apartment"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"family", "dog"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"neighbors", "dogs"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"beds", "dogs"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"companions", "dogs"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"buddy", "walks"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"scout", "buddy"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "sitting"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dog", "shelter"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"cousin", "dog"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"dogs", "get"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pets", "offer"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"pets", "tricks"}),
        _DOG_ACTIVITY_CARE_EXPANSION,
        "dog_activity_care_bridge",
    ),
    (
        frozenset({"puppy", "name"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"puppy", "got"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"adopted", "puppy"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"pet", "adopted"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"pet", "adopt"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"pet", "has"}),
        _PET_INVENTORY_EXPANSION,
        "pet_inventory_bridge",
    ),
    (
        frozenset({"who", "owns"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"who", "has", "dog"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"who", "has", "cat"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"who", "has", "puppy"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"who", "has", "pup"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"who", "has", "pet"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"whose", "dog"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"dog", "name"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
    (
        frozenset({"pet", "name"}),
        _PET_OWNERSHIP_EXPANSION,
        "pet_ownership_bridge",
    ),
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
