"""Adapter-facing query request mapping for context_building candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from infinity_context_core.features.context_building.public import (
    ContextCandidateRequest,
    ContextQueryPlan,
    ContextScope,
)


@dataclass(frozen=True, slots=True)
class ContextCandidateAdapterQuery:
    """Provider-neutral view of the feature-owned candidate request."""

    scope: ContextScope
    text: str
    intent: str
    as_of: datetime | None
    tags: tuple[str, ...]
    search_texts: tuple[str, ...]
    terms: tuple[str, ...]
    limit: int
    query_plan: ContextQueryPlan | None = None

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("Candidate adapter query limit must be positive")
        if not self.text.strip():
            raise ValueError("Candidate adapter query requires text")
        if not self.search_texts:
            raise ValueError("Candidate adapter query requires search texts")

    @classmethod
    def from_candidate_request(cls, request: ContextCandidateRequest) -> Self:
        """Convert the core port DTO into an adapter-consumable query shape."""

        query_plan = request.query_plan
        query = query_plan.normalized_query if query_plan is not None else request.query
        search_texts = (
            query_plan.search_texts if query_plan is not None else (query.text,)
        )
        tags = query_plan.normalized_tags if query_plan is not None else query.tags
        terms = query_plan.terms if query_plan is not None else ()

        return cls(
            scope=query.scope,
            text=query.text,
            intent=query.intent,
            as_of=query.as_of,
            tags=_clean_texts(tags),
            search_texts=_clean_texts(search_texts, fallback=query.text),
            terms=_clean_texts(terms),
            limit=request.limit,
            query_plan=query_plan,
        )


def context_candidate_adapter_query_from_request(
    request: ContextCandidateRequest,
) -> ContextCandidateAdapterQuery:
    """Create an adapter-facing context candidate query from the public port DTO."""

    return ContextCandidateAdapterQuery.from_candidate_request(request)


def _clean_texts(
    values: tuple[str, ...],
    *,
    fallback: str | None = None,
) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)

    if cleaned:
        return tuple(cleaned)
    if fallback is None:
        return ()
    normalized_fallback = " ".join(fallback.split())
    return (normalized_fallback,) if normalized_fallback else ()


__all__ = (
    "ContextCandidateAdapterQuery",
    "context_candidate_adapter_query_from_request",
)
