"""Composition helpers for the memory_scopes server feature."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
import infinity_context_core.features.memory_scopes.public as memory_scopes

from infinity_context_server.features.memory_scopes.routes import (
    create_memory_scopes_router,
)


@dataclass(frozen=True, slots=True)
class MemoryScopesServerFeature:
    """Server-side assembly for memory_scopes routes and use cases."""

    use_cases: memory_scopes.MemoryScopeUseCases
    route_prefix: str = ""

    @property
    def feature_id(self) -> str:
        return memory_scopes.FEATURE_ID

    def create_router(self) -> APIRouter:
        return create_memory_scopes_router(
            self.use_cases,
            prefix=self.route_prefix,
        )


def build_memory_scopes_server_feature(
    use_cases: memory_scopes.MemoryScopeUseCases,
    *,
    route_prefix: str = "",
) -> MemoryScopesServerFeature:
    """Create the server seam without constructing feature business logic."""

    return MemoryScopesServerFeature(
        use_cases=use_cases,
        route_prefix=route_prefix,
    )


__all__ = (
    "MemoryScopesServerFeature",
    "build_memory_scopes_server_feature",
)
