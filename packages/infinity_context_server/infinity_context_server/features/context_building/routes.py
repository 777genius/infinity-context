"""Feature-owned FastAPI route seam for context_building."""

from __future__ import annotations

from typing import Any

import infinity_context_core.features.context_building.public as context_building
from fastapi import APIRouter, HTTPException, status

from infinity_context_server.features.context_building.contracts import (
    BuildContextHttpRequest,
)
from infinity_context_server.features.context_building.mappers import (
    build_context_query_from_contract,
    build_context_result_to_contract,
)


def create_context_building_router(
    use_cases: context_building.ContextBuildingUseCases,
    *,
    prefix: str = "",
) -> APIRouter:
    """Create routes that only translate HTTP contracts to feature use cases."""

    router = APIRouter(prefix=prefix, tags=["context_building"])

    @router.post("/context")
    async def build_context(request: BuildContextHttpRequest) -> dict[str, Any]:
        try:
            query = build_context_query_from_contract(request.to_contract())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        result = await use_cases.build_context.execute(query)
        return build_context_result_to_contract(result).to_dict()

    return router


__all__ = ("create_context_building_router",)
