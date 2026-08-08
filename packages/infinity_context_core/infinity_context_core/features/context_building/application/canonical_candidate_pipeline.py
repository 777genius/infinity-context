"""Canonical hydration and deterministic fusion for recall candidates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

from infinity_context_core.features.context_building.domain import (
    CandidateHit,
    ContextItem,
    FusedCandidate,
    HydratedContextCandidate,
)
from infinity_context_core.features.context_building.ports import (
    CanonicalContextHydratorPort,
    ContextCandidateHitProviderPort,
    ContextCandidateRequest,
)


@dataclass(frozen=True, slots=True)
class CandidateHitProviderRegistration:
    """Trusted application configuration for one recall provider."""

    provider_id: str
    provider: ContextCandidateHitProviderPort
    weight: float = 1.0
    required: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("Candidate provider id cannot be blank")
        if self.weight <= 0:
            raise ValueError("Candidate provider weight must be positive")


@dataclass(frozen=True, slots=True)
class CanonicalCandidatePipeline:
    """Treat search systems as indexes and Postgres hydration as the trust boundary."""

    providers: tuple[CandidateHitProviderRegistration, ...]
    hydrator: CanonicalContextHydratorPort
    overfetch_factor: int = 3
    max_scan_pages: int = 10
    rank_constant: float = 60.0

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("Canonical candidate pipeline requires providers")
        provider_ids = tuple(item.provider_id for item in self.providers)
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("Canonical candidate provider ids must be unique")
        if self.overfetch_factor < 1:
            raise ValueError("Candidate overfetch factor must be positive")
        if self.max_scan_pages < 1:
            raise ValueError("Candidate max scan pages must be positive")
        if self.rank_constant <= 0:
            raise ValueError("Candidate rank constant must be positive")

    async def find_candidates(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[ContextItem, ...]:
        page_size = request.limit * self.overfetch_factor
        active = list(self.providers)
        hits: list[CandidateHit] = []
        seen_hits: set[tuple[str, str, str, int, int]] = set()
        hydration_attempted: set[str] = set()
        hydrated_by_id: dict[str, HydratedContextCandidate] = {}
        weights = {item.provider_id: item.weight for item in self.providers}
        selected: tuple[ContextItem, ...] = ()
        for page_number in range(self.max_scan_pages):
            if not active:
                break
            page_request = replace(
                request,
                limit=page_size,
                offset=request.offset + (page_number * page_size),
            )
            provider_results = await asyncio.gather(
                *(
                    registration.provider.find_candidate_hits(page_request)
                    for registration in active
                ),
                return_exceptions=True,
            )
            next_active: list[CandidateHitProviderRegistration] = []
            for registration, result in zip(active, provider_results, strict=True):
                if isinstance(result, BaseException):
                    if registration.required:
                        raise result
                    continue
                new_hit_count = _append_provider_page(
                    hits,
                    seen_hits,
                    registration=registration,
                    result=result,
                )
                if len(result) == page_size and new_hit_count > 0:
                    next_active.append(registration)
            active = next_active
            selected = await self._hydrate_and_select(
                request,
                hits,
                weights,
                hydration_attempted=hydration_attempted,
                hydrated_by_id=hydrated_by_id,
            )
            if len(selected) >= request.limit:
                selected = await self._revalidate_selected(
                    request,
                    selected,
                    hits,
                    weights,
                    hydration_attempted=hydration_attempted,
                    hydrated_by_id=hydrated_by_id,
                )
                if len(selected) >= request.limit:
                    return selected
        if active:
            raise RuntimeError(
                "Canonical candidate scan limit reached before enough eligible facts were found"
            )
        return await self._revalidate_selected(
            request,
            selected,
            hits,
            weights,
            hydration_attempted=hydration_attempted,
            hydrated_by_id=hydrated_by_id,
        )

    async def _revalidate_selected(
        self,
        request: ContextCandidateRequest,
        selected: tuple[ContextItem, ...],
        hits: list[CandidateHit],
        weights: dict[str, float],
        *,
        hydration_attempted: set[str],
        hydrated_by_id: dict[str, HydratedContextCandidate],
    ) -> tuple[ContextItem, ...]:
        current = selected
        latest_batch_ids: set[str] = set()
        max_rounds = len({hit.canonical_id for hit in hits}) + 1
        for _round in range(max_rounds):
            if not current:
                return ()
            selected_ids = tuple(item.item_id for item in current)
            latest_batch_ids = set(selected_ids)
            for canonical_id in selected_ids:
                hydrated_by_id.pop(canonical_id, None)
            revalidated = await self.hydrator.hydrate_candidates(request, selected_ids)
            hydrated_by_id.update(
                (candidate.canonical_id, candidate) for candidate in revalidated
            )
            hydration_attempted.update(selected_ids)
            current = await self._hydrate_and_select(
                request,
                hits,
                weights,
                hydration_attempted=hydration_attempted,
                hydrated_by_id=hydrated_by_id,
            )
            if {item.item_id for item in current} <= latest_batch_ids:
                return current
        return tuple(item for item in current if item.item_id in latest_batch_ids)

    async def _hydrate_and_select(
        self,
        request: ContextCandidateRequest,
        hits: list[CandidateHit],
        weights: dict[str, float],
        *,
        hydration_attempted: set[str],
        hydrated_by_id: dict[str, HydratedContextCandidate],
    ) -> tuple[ContextItem, ...]:
        initially_fused = _fuse_hits(
            tuple(hits),
            weights=weights,
            rank_constant=self.rank_constant,
        )
        canonical_ids = tuple(candidate.canonical_id for candidate in initially_fused)
        if not canonical_ids:
            return ()

        pending_ids = tuple(
            canonical_id
            for canonical_id in canonical_ids
            if canonical_id not in hydration_attempted
        )
        if pending_ids:
            hydration_attempted.update(pending_ids)
            hydrated = await self.hydrator.hydrate_candidates(request, pending_ids)
            hydrated_by_id.update(
                (candidate.canonical_id, candidate) for candidate in hydrated
            )
        current_hits = tuple(
            hit
            for hit in hits
            if (candidate := hydrated_by_id.get(hit.canonical_id)) is not None
            and candidate.canonical_version == hit.canonical_version
        )
        finally_fused = _fuse_hits(
            current_hits,
            weights=weights,
            rank_constant=self.rank_constant,
        )

        selected: list[ContextItem] = []
        for candidate in finally_fused:
            hydrated_candidate = hydrated_by_id.get(candidate.canonical_id)
            if hydrated_candidate is None:
                continue
            providers = tuple(sorted({hit.provider_id for hit in candidate.hits}))
            selected.append(
                _with_retrieval_evidence(
                    hydrated_candidate.item,
                    providers=providers,
                    score=candidate.score,
                )
            )
            if len(selected) >= request.limit:
                break
        return tuple(selected)


def _append_provider_page(
    hits: list[CandidateHit],
    seen_hits: set[tuple[str, str, str, int, int]],
    *,
    registration: CandidateHitProviderRegistration,
    result: tuple[CandidateHit, ...],
) -> int:
    new_hit_count = 0
    for hit in result:
        if hit.provider_id != registration.provider_id:
            raise ValueError("Candidate provider returned a mismatched provider_id")
        identity = (
            hit.provider_id,
            hit.query_key,
            hit.canonical_id,
            hit.canonical_version,
            hit.rank,
        )
        if identity in seen_hits:
            continue
        seen_hits.add(identity)
        hits.append(hit)
        new_hit_count += 1
    return new_hit_count


def _fuse_hits(
    hits: tuple[CandidateHit, ...],
    *,
    weights: dict[str, float],
    rank_constant: float,
) -> tuple[FusedCandidate, ...]:
    groups_per_provider: dict[str, set[str]] = {}
    for hit in hits:
        groups_per_provider.setdefault(hit.provider_id, set()).add(hit.query_key)

    scores: dict[str, float] = {}
    hits_by_id: dict[str, list[CandidateHit]] = {}
    seen_per_ranking: set[tuple[str, str, str]] = set()
    for hit in sorted(
        hits,
        key=lambda value: (
            value.provider_id,
            value.query_key,
            value.rank,
            value.canonical_id,
        ),
    ):
        ranking_key = (hit.provider_id, hit.query_key, hit.canonical_id)
        if ranking_key in seen_per_ranking:
            continue
        seen_per_ranking.add(ranking_key)
        provider_weight = weights.get(hit.provider_id)
        if provider_weight is None:
            continue
        query_count = len(groups_per_provider[hit.provider_id])
        contribution = provider_weight / query_count / (rank_constant + hit.rank)
        scores[hit.canonical_id] = scores.get(hit.canonical_id, 0.0) + contribution
        hits_by_id.setdefault(hit.canonical_id, []).append(hit)

    return tuple(
        FusedCandidate(
            canonical_id=canonical_id,
            score=score,
            hits=tuple(hits_by_id[canonical_id]),
        )
        for canonical_id, score in sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
    )


def _with_retrieval_evidence(
    item: ContextItem,
    *,
    providers: tuple[str, ...],
    score: float,
) -> ContextItem:
    return replace(
        item,
        score=score,
        evidence=tuple(
            replace(evidence, retrieval_sources=providers, relevance_score=score)
            for evidence in item.evidence
        ),
    )


__all__ = ("CandidateHitProviderRegistration", "CanonicalCandidatePipeline")
