"""Canonical hydration trust-boundary checks for context retrieval."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from infinity_context_core.features.context_building.public import (
    CandidateHit,
    CandidateHitProviderRegistration,
    CanonicalCandidatePipeline,
    ContextCandidateRequest,
    ContextEvidence,
    ContextItem,
    ContextQuery,
    ContextScope,
    ContextSourceRef,
    HydratedContextCandidate,
)


@dataclass
class _HitProvider:
    hits: tuple[CandidateHit, ...] = ()
    error: BaseException | None = None
    requested_limits: list[int] | None = None
    requested_offsets: list[int] | None = None

    async def find_candidate_hits(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[CandidateHit, ...]:
        if self.requested_limits is not None:
            self.requested_limits.append(request.limit)
        if self.requested_offsets is not None:
            self.requested_offsets.append(request.offset)
        if self.error is not None:
            raise self.error
        return self.hits[request.offset : request.offset + request.limit]


@dataclass
class _Hydrator:
    candidates: tuple[HydratedContextCandidate, ...]
    requested_ids: tuple[str, ...] = ()
    requested_batches: list[tuple[str, ...]] | None = None

    async def hydrate_candidates(
        self,
        _request: ContextCandidateRequest,
        canonical_ids: tuple[str, ...],
    ) -> tuple[HydratedContextCandidate, ...]:
        self.requested_ids = canonical_ids
        if self.requested_batches is not None:
            self.requested_batches.append(canonical_ids)
        allowed = set(canonical_ids)
        return tuple(item for item in self.candidates if item.canonical_id in allowed)


def test_pipeline_rejects_stale_and_missing_hits_then_refills() -> None:
    limits: list[int] = []
    hydration_batches: list[tuple[str, ...]] = []
    provider = _HitProvider(
        requested_limits=limits,
        hits=(
            _hit("stale", version=1, rank=1),
            _hit("current-1", version=2, rank=2),
            _hit("missing", version=1, rank=3),
            _hit("current-2", version=3, rank=4),
        ),
    )
    hydrator = _Hydrator(
        requested_batches=hydration_batches,
        candidates=(
            _hydrated("stale", version=2),
            _hydrated("current-1", version=2),
            _hydrated("current-2", version=3),
        )
    )
    pipeline = CanonicalCandidatePipeline(
        providers=(CandidateHitProviderRegistration("vector", provider),),
        hydrator=hydrator,
        overfetch_factor=3,
    )

    result = asyncio.run(pipeline.find_candidates(_request(limit=2)))

    assert limits == [6]
    assert tuple(item.item_id for item in result) == ("current-1", "current-2")
    assert set(hydration_batches[0]) == {"stale", "current-1", "missing", "current-2"}
    assert hydration_batches[1] == ("current-1", "current-2")
    assert result[0].evidence[0].retrieval_sources == ("vector",)
    assert result[0].evidence[0].relevance_score > result[1].evidence[0].relevance_score


def test_pipeline_pages_past_ineligible_provider_results() -> None:
    offsets: list[int] = []
    hydration_batches: list[tuple[str, ...]] = []
    provider = _HitProvider(
        requested_offsets=offsets,
        hits=tuple(
            _hit(
                f"stale-{rank}" if rank <= 6 else "current",
                version=1,
                rank=rank,
            )
            for rank in range(1, 8)
        ),
    )
    hydrator = _Hydrator(
        requested_batches=hydration_batches,
        candidates=(
            *(_hydrated(f"stale-{rank}", version=2) for rank in range(1, 7)),
            _hydrated("current", version=1),
        )
    )
    pipeline = CanonicalCandidatePipeline(
        providers=(CandidateHitProviderRegistration("vector", provider),),
        hydrator=hydrator,
        overfetch_factor=3,
    )

    result = asyncio.run(pipeline.find_candidates(_request(limit=2)))

    assert offsets == [0, 6]
    assert hydration_batches == [
        tuple(f"stale-{rank}" for rank in range(1, 7)),
        ("current",),
        ("current",),
    ]
    assert tuple(item.item_id for item in result) == ("current",)


def test_pipeline_revalidates_selected_ids_after_later_page_mutation() -> None:
    provider = _HitProvider(
        hits=(
            _hit("changed", version=1, rank=1),
            *(
                _hit(f"stale-{rank}", version=1, rank=rank)
                for rank in range(2, 7)
            ),
            _hit("current", version=1, rank=7),
        )
    )

    class MutatingHydrator:
        def __init__(self) -> None:
            self.batches: list[tuple[str, ...]] = []

        async def hydrate_candidates(
            self,
            _request: ContextCandidateRequest,
            canonical_ids: tuple[str, ...],
        ) -> tuple[HydratedContextCandidate, ...]:
            self.batches.append(canonical_ids)
            candidates = {
                "changed": _hydrated("changed", version=1),
                "current": _hydrated("current", version=1),
                **{
                    f"stale-{rank}": _hydrated(f"stale-{rank}", version=2)
                    for rank in range(2, 7)
                },
            }
            if len(self.batches) >= 3:
                candidates.pop("changed")
            return tuple(
                candidates[canonical_id]
                for canonical_id in canonical_ids
                if canonical_id in candidates
            )

    hydrator = MutatingHydrator()
    pipeline = CanonicalCandidatePipeline(
        providers=(CandidateHitProviderRegistration("vector", provider),),
        hydrator=hydrator,
        overfetch_factor=3,
    )

    result = asyncio.run(pipeline.find_candidates(_request(limit=2)))

    assert tuple(item.item_id for item in result) == ("current",)
    assert hydrator.batches[2] == ("changed", "current")


def test_pipeline_revalidates_promoted_cached_fallback_before_return() -> None:
    provider = _HitProvider(
        hits=(
            _hit("selected-a", version=1, rank=1),
            _hit("fallback-b", version=1, rank=2),
        )
    )

    class ConcurrentMutationHydrator:
        def __init__(self) -> None:
            self.batches: list[tuple[str, ...]] = []

        async def hydrate_candidates(
            self,
            _request: ContextCandidateRequest,
            canonical_ids: tuple[str, ...],
        ) -> tuple[HydratedContextCandidate, ...]:
            self.batches.append(canonical_ids)
            if len(self.batches) == 1:
                return (_hydrated("selected-a"), _hydrated("fallback-b"))
            if canonical_ids == ("fallback-b",):
                return (_hydrated("fallback-b", version=2),)
            return ()

    hydrator = ConcurrentMutationHydrator()
    pipeline = CanonicalCandidatePipeline(
        providers=(CandidateHitProviderRegistration("vector", provider),),
        hydrator=hydrator,
        overfetch_factor=3,
    )

    result = asyncio.run(pipeline.find_candidates(_request(limit=1)))

    assert result == ()
    assert hydrator.batches == [
        ("selected-a", "fallback-b"),
        ("selected-a",),
        ("fallback-b",),
    ]


def test_fusion_is_independent_of_provider_registration_order() -> None:
    vector = _HitProvider(
        hits=(
            _hit("alpha", provider="vector", rank=1),
            _hit("beta", provider="vector", rank=2),
        )
    )
    graph = _HitProvider(
        hits=(
            _hit("beta", provider="graph", rank=1),
            _hit("alpha", provider="graph", rank=2),
        )
    )
    hydrated = _Hydrator(candidates=(_hydrated("alpha"), _hydrated("beta")))
    forward = CanonicalCandidatePipeline(
        providers=(
            CandidateHitProviderRegistration("vector", vector),
            CandidateHitProviderRegistration("graph", graph),
        ),
        hydrator=hydrated,
    )
    reverse = CanonicalCandidatePipeline(
        providers=tuple(reversed(forward.providers)),
        hydrator=hydrated,
    )

    forward_result = asyncio.run(forward.find_candidates(_request(limit=2)))
    reverse_result = asyncio.run(reverse.find_candidates(_request(limit=2)))

    assert tuple(item.item_id for item in forward_result) == ("alpha", "beta")
    assert forward_result == reverse_result
    assert forward_result[0].evidence[0].retrieval_sources == ("graph", "vector")


def test_optional_provider_failure_degrades_but_required_failure_is_visible() -> None:
    failed = _HitProvider(error=RuntimeError("index unavailable"))
    healthy = _HitProvider(hits=(_hit("alpha", provider="keyword", rank=1),))
    hydrator = _Hydrator(candidates=(_hydrated("alpha"),))
    degraded = CanonicalCandidatePipeline(
        providers=(
            CandidateHitProviderRegistration("vector", failed),
            CandidateHitProviderRegistration("keyword", healthy, required=True),
        ),
        hydrator=hydrator,
    )

    assert tuple(
        item.item_id for item in asyncio.run(degraded.find_candidates(_request(limit=1)))
    ) == ("alpha",)

    required = CanonicalCandidatePipeline(
        providers=(CandidateHitProviderRegistration("vector", failed, required=True),),
        hydrator=hydrator,
    )
    with pytest.raises(RuntimeError, match="index unavailable"):
        asyncio.run(required.find_candidates(_request(limit=1)))


def _hit(
    canonical_id: str,
    *,
    version: int = 1,
    provider: str = "vector",
    rank: int,
) -> CandidateHit:
    return CandidateHit(
        canonical_id=canonical_id,
        canonical_version=version,
        provider_id=provider,
        query_key="normalized",
        rank=rank,
    )


def _hydrated(canonical_id: str, *, version: int = 1) -> HydratedContextCandidate:
    evidence = ContextEvidence(
        text=f"Canonical {canonical_id}",
        source_refs=(ContextSourceRef(source_type="fact", source_id=canonical_id),),
        canonical_version=version,
    )
    return HydratedContextCandidate(
        canonical_id=canonical_id,
        canonical_version=version,
        item=ContextItem(
            item_id=canonical_id,
            text=evidence.text,
            evidence=(evidence,),
        ),
    )


def _request(*, limit: int) -> ContextCandidateRequest:
    return ContextCandidateRequest(
        query=ContextQuery(
            scope=ContextScope(space_id="space-1", memory_scope_id="scope-1"),
            text="deployment architecture",
        ),
        limit=limit,
    )
