"""Composition helpers for the context_building server feature."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
import infinity_context_core.features.context_building.public as context_building

from infinity_context_server.features.context_building.routes import (
    create_context_building_router,
)


@dataclass(frozen=True, slots=True)
class ContextBuildingServerFeature:
    """Server-side assembly for context_building routes and use cases."""

    use_cases: context_building.ContextBuildingUseCases
    route_prefix: str = ""

    @property
    def feature_id(self) -> str:
        return context_building.FEATURE_ID

    def create_router(self) -> APIRouter:
        return create_context_building_router(
            self.use_cases,
            prefix=self.route_prefix,
        )


def build_context_building_server_feature(
    use_cases: context_building.ContextBuildingUseCases,
    *,
    route_prefix: str = "",
) -> ContextBuildingServerFeature:
    """Create the server seam without constructing feature business logic."""

    return ContextBuildingServerFeature(
        use_cases=use_cases,
        route_prefix=route_prefix,
    )


__all__ = (
    "ContextBuildingServerFeature",
    "build_context_building_server_feature",
)
