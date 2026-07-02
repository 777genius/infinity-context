"""Static deterministic query expansion rules."""

from __future__ import annotations

from infinity_context_core.application.context_query_expansion_rule_catalog_part1 import (
    EXPANSION_RULES_PART_1,
)
from infinity_context_core.application.context_query_expansion_rule_catalog_part2 import (
    EXPANSION_RULES_PART_2,
)
from infinity_context_core.application.context_query_expansion_rule_catalog_part3 import (
    EXPANSION_RULES_PART_3,
)
from infinity_context_core.application.context_query_expansion_rule_catalog_part4 import (
    EXPANSION_RULES_PART_4,
)
from infinity_context_core.application.context_query_expansion_rule_catalog_part5 import (
    EXPANSION_RULES_PART_5,
)
from infinity_context_core.application.context_query_expansion_rule_terms import (
    MAX_QUERY_EXPANSIONS as MAX_QUERY_EXPANSIONS,
)
from infinity_context_core.application.context_query_food_expansions import (
    FOOD_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_game_expansions import (
    GAME_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_health_lifestyle_expansions import (
    HEALTH_LIFESTYLE_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_pet_activity_expansions import (
    PET_ACTIVITY_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_preference_expansions import (
    PREFERENCE_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_sports_expansions import (
    SPORTS_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_temporal_expansions import (
    TEMPORAL_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_travel_expansions import (
    TRAVEL_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_vehicle_expansions import (
    VEHICLE_EXPANSION_RULES,
)

EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    *EXPANSION_RULES_PART_1,
    *EXPANSION_RULES_PART_2,
    *EXPANSION_RULES_PART_3,
    *EXPANSION_RULES_PART_4,
    *EXPANSION_RULES_PART_5,
    *FOOD_EXPANSION_RULES,
    *GAME_EXPANSION_RULES,
    *HEALTH_LIFESTYLE_EXPANSION_RULES,
    *PET_ACTIVITY_EXPANSION_RULES,
    *PREFERENCE_EXPANSION_RULES,
    *SPORTS_EXPANSION_RULES,
    *TEMPORAL_EXPANSION_RULES,
    *TRAVEL_EXPANSION_RULES,
    *VEHICLE_EXPANSION_RULES,
)
