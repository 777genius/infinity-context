"""Composition seam for multiple context candidate providers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import ClassVar

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    ContextCandidateProviderPort,
    ContextCandidateRequest,
    ContextItem,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateProviderChain:
    """Merge feature-owned candidate providers without exposing adapter internals."""

    providers: tuple[ContextCandidateProviderPort, ...]

    adapter_name: ClassVar[str] = "context_candidate_provider_chain"
    feature_id: ClassVar[str] = FEATURE_ID

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("ContextCandidateProviderChain requires at least one provider")

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        selected: list[ContextItem] = []
        seen_ids: set[str] = set()

        for provider in self.providers:
            remaining = request.limit - len(selected)
            if remaining < 1:
                break

            provider_request = (
                request if remaining == request.limit else replace(request, limit=remaining)
            )
            for item in await provider.find_candidates(provider_request):
                if item.item_id in seen_ids:
                    continue

                selected.append(item)
                seen_ids.add(item.item_id)
                if len(selected) >= request.limit:
                    return tuple(selected)

        return tuple(selected)


def create_context_candidate_provider_chain(
    providers: Iterable[ContextCandidateProviderPort],
) -> ContextCandidateProviderChain:
    """Create a deterministic provider chain from concrete feature adapters."""

    return ContextCandidateProviderChain(providers=tuple(providers))


__all__ = (
    "ContextCandidateProviderChain",
    "create_context_candidate_provider_chain",
)
