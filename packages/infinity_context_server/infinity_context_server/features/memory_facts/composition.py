"""Composition helpers for the memory_facts server feature."""

from __future__ import annotations

from dataclasses import dataclass

import infinity_context_core.features.memory_facts.public as memory_facts
from fastapi import APIRouter

from infinity_context_server.features.memory_facts.routes import (
    create_memory_facts_router,
)


@dataclass(frozen=True, slots=True)
class MemoryFactsServerFeature:
    """Server-side assembly for memory_facts routes and use cases."""

    use_cases: memory_facts.MemoryFactLifecycleUseCases
    route_prefix: str = ""

    @property
    def feature_id(self) -> str:
        return memory_facts.FEATURE_ID

    def create_router(self) -> APIRouter:
        return create_memory_facts_router(
            self.use_cases,
            prefix=self.route_prefix,
        )


@dataclass(frozen=True, slots=True)
class MemoryFactsServerComposition:
    """Backward-compatible dependency holder for the memory_facts route seam."""

    use_cases: memory_facts.MemoryFactLifecycleUseCases | None = None
    feature_id: str = memory_facts.FEATURE_ID

    @property
    def is_wired(self) -> bool:
        return self.use_cases is not None


def build_memory_facts_server_feature(
    use_cases: memory_facts.MemoryFactLifecycleUseCases,
    *,
    route_prefix: str = "",
) -> MemoryFactsServerFeature:
    """Create the server seam without constructing feature business logic."""

    return MemoryFactsServerFeature(
        use_cases=use_cases,
        route_prefix=route_prefix,
    )


def build_memory_facts_server_composition(
    *,
    use_cases: memory_facts.MemoryFactLifecycleUseCases | None = None,
) -> MemoryFactsServerComposition:
    """Create a dependency holder without instantiating production adapters."""

    return MemoryFactsServerComposition(use_cases=use_cases)


__all__ = (
    "MemoryFactsServerComposition",
    "MemoryFactsServerFeature",
    "build_memory_facts_server_composition",
    "build_memory_facts_server_feature",
)
