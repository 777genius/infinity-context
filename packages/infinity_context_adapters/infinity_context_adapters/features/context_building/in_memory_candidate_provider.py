"""In-memory candidate provider for context_building adapter tests and wiring."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from infinity_context_core.features.context_building.public import (
    FEATURE_ID,
    ContextCandidateProviderPort,
    ContextCandidateRequest,
    ContextItem,
)

from infinity_context_adapters.features.context_building.records import (
    ContextCandidateRecord,
)
from infinity_context_adapters.features.context_building.query_request import (
    ContextCandidateAdapterQuery,
)


@dataclass(frozen=True, slots=True)
class InMemoryContextCandidateProvider:
    """Stdlib-only candidate provider that honors context_building scope rules."""

    records: tuple[ContextCandidateRecord, ...] = ()

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        adapter_query = ContextCandidateAdapterQuery.from_candidate_request(request)
        matching_records = [
            record for record in self.records if record.matches_request(adapter_query)
        ]
        ranked_records = sorted(
            enumerate(matching_records),
            key=lambda item: (-item[1].priority, -item[1].score, item[0]),
        )
        return tuple(
            record.to_context_item()
            for _, record in ranked_records[: adapter_query.limit]
        )


def create_in_memory_context_candidate_provider(
    records: Iterable[ContextCandidateRecord] = (),
) -> ContextCandidateProviderPort:
    """Create a deterministic in-memory implementation of the candidate port."""

    return InMemoryContextCandidateProvider(records=tuple(records))


__all__ = (
    "InMemoryContextCandidateProvider",
    "create_in_memory_context_candidate_provider",
)
