"""Feature-owned pipeline for composing context candidate providers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from infinity_context_core.features.context_building.domain import ContextItem
from infinity_context_core.features.context_building.ports import (
    ContextCandidateProviderPort,
    ContextCandidateRequest,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateProviderPipeline:
    """Merge candidate providers behind the context_building port boundary."""

    providers: tuple[ContextCandidateProviderPort, ...]

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError(
                "ContextCandidateProviderPipeline requires at least one provider"
            )

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        selected: list[ContextItem] = []
        seen_ids: set[str] = set()

        for provider in self.providers:
            if len(selected) >= request.limit:
                break

            for item in await provider.find_candidates(request):
                if item.item_id in seen_ids:
                    continue

                selected.append(item)
                seen_ids.add(item.item_id)
                if len(selected) >= request.limit:
                    return tuple(selected)

        return tuple(selected)


def create_context_candidate_provider_pipeline(
    providers: Iterable[ContextCandidateProviderPort],
) -> ContextCandidateProviderPipeline:
    """Create a deterministic provider pipeline from concrete adapters."""

    return ContextCandidateProviderPipeline(providers=tuple(providers))


__all__ = (
    "ContextCandidateProviderPipeline",
    "create_context_candidate_provider_pipeline",
)
