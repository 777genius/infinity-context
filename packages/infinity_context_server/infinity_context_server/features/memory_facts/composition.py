"""Composition seam for the memory_facts server feature mirror."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    MemoryFactLifecycleUseCases,
)


@dataclass(frozen=True, slots=True)
class MemoryFactsServerComposition:
    """Feature-local server dependencies for future runtime wiring."""

    use_cases: MemoryFactLifecycleUseCases | None = None
    feature_id: str = FEATURE_ID

    @property
    def is_wired(self) -> bool:
        return self.use_cases is not None


def build_memory_facts_server_composition(
    *,
    use_cases: MemoryFactLifecycleUseCases | None = None,
) -> MemoryFactsServerComposition:
    """Create the server feature seam without instantiating production adapters."""

    return MemoryFactsServerComposition(use_cases=use_cases)


__all__ = (
    "MemoryFactsServerComposition",
    "build_memory_facts_server_composition",
)
