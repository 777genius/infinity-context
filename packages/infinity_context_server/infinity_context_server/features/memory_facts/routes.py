"""Route seam for the memory_facts server feature mirror."""

from __future__ import annotations

from fastapi import APIRouter

from infinity_context_server.features.memory_facts.composition import (
    MemoryFactsServerComposition,
    build_memory_facts_server_composition,
)


def create_memory_facts_router(
    *,
    composition: MemoryFactsServerComposition | None = None,
) -> APIRouter:
    """Return the feature-owned router placeholder without registering endpoints."""

    _composition = composition or build_memory_facts_server_composition()
    return APIRouter(prefix="/facts", tags=[_composition.feature_id])


__all__ = ("create_memory_facts_router",)
