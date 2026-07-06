"""Public server seam for the context_building feature mirror."""

from __future__ import annotations

import infinity_context_core.features.context_building.public as context_building

from infinity_context_server.features.context_building.composition import (
    ContextBuildingServerFeature,
    build_context_building_server_feature,
)
from infinity_context_server.features.context_building.contracts import (
    BuildContextHttpRequest,
    ContextBudgetHttpRequest,
    MemoryInsightsHttpRequest,
)
from infinity_context_server.features.context_building.digest_api_responses import (
    LegacyDigestApiResponseMapper,
)
from infinity_context_server.features.context_building.insights_api_responses import (
    LegacyMemoryInsightsApiResponseMapper,
)
from infinity_context_server.features.context_building.legacy_api_responses import (
    LegacyContextApiResponseMapper,
)
from infinity_context_server.features.context_building.mappers import (
    build_context_query_from_contract,
    build_context_result_to_contract,
)
from infinity_context_server.features.context_building.routes import (
    create_context_building_router,
)

FEATURE_ID = context_building.FEATURE_ID

__all__ = (
    "BuildContextHttpRequest",
    "ContextBudgetHttpRequest",
    "MemoryInsightsHttpRequest",
    "ContextBuildingServerFeature",
    "FEATURE_ID",
    "LegacyContextApiResponseMapper",
    "LegacyDigestApiResponseMapper",
    "LegacyMemoryInsightsApiResponseMapper",
    "build_context_building_server_feature",
    "build_context_query_from_contract",
    "build_context_result_to_contract",
    "create_context_building_router",
)
