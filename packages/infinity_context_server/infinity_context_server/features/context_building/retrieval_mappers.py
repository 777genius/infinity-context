"""Exact contract/core mapping for locator-only Retrieval."""

from __future__ import annotations

from datetime import datetime

import infinity_context_core.features.context_building.public as core
from infinity_context_contracts.features.context_building import (
    RetrievalAppliedBoundsDto,
    RetrievalCandidateDto,
    RetrievalContributionDto,
    RetrievalNeighborDto,
    RetrievalProviderOutcomeDto,
    RetrieveContextRequestDto,
    RetrieveContextResponseDto,
)


def retrieval_request_to_core(
    request: RetrieveContextRequestDto,
) -> core.LocatorRetrievalRequest:
    return core.LocatorRetrievalRequest(
        contract_version=request.contract_version,
        capability_fingerprint=request.capability_fingerprint,
        profile_id=request.profile_id,
        scope=core.LocatorRetrievalScope(
            request.scope.space_id, request.scope.memory_scope_id, request.scope.thread_id
        ),
        queries=tuple(
            core.LocatorQueryVariant(item.query_id, item.query, item.weight_micros)
            for item in request.queries
        ),
        hard_filters=core.LocatorHardFilters(
            source_generations=tuple(
                core.LocatorSourceGeneration(item.source_key, item.projection_generation)
                for item in request.filters.source_generations
            ),
            excluded_source_keys=tuple(request.filters.excluded_source_keys),
            document_keys=tuple(request.filters.document_keys),
            kinds=tuple(request.filters.kinds),
            category=request.filters.category,
            tags_any=tuple(request.filters.tags_any),
            tags_all=tuple(request.filters.tags_all),
            tags_none=tuple(request.filters.tags_none),
            actor_keys=tuple(request.filters.actor_keys),
            time_interval=_interval(request.filters.time_interval),
            relative_time_interval=_relative_interval(request.filters.relative_time_interval),
        ),
        soft_preferences=core.LocatorSoftPreferences(
            source_preferences=tuple(
                core.LocatorWeightedKey(item.key, item.weight_micros)
                for item in request.soft_preferences.source_preferences
            ),
            actor_preferences=tuple(
                core.LocatorWeightedKey(item.key, item.weight_micros)
                for item in request.soft_preferences.actor_preferences
            ),
            time_interval=_interval(request.soft_preferences.time_interval),
            relative_time_interval=_relative_interval(
                request.soft_preferences.relative_time_interval
            ),
            time_weight_micros=request.soft_preferences.time_weight_micros,
        ),
        bounds=core.LocatorRetrievalBounds(
            request.bounds.candidate_limit,
            request.bounds.result_limit,
            request.bounds.neighbor_radius,
            request.bounds.response_byte_limit,
            request.bounds.deadline_ms,
        ),
    )


def retrieval_response_to_contract(
    response: core.LocatorRetrievalResponse,
) -> RetrieveContextResponseDto:
    return RetrieveContextResponseDto(
        status=response.status,
        capability_fingerprint=response.capability_fingerprint,
        profile_id=response.profile_id,
        applied_bounds=RetrievalAppliedBoundsDto(
            response.applied_bounds.candidate_limit,
            response.applied_bounds.result_limit,
            response.applied_bounds.neighbor_radius,
            response.applied_bounds.response_byte_limit,
            response.applied_bounds.deadline_ms,
            response.applied_bounds.returned_seeds,
            response.applied_bounds.returned_neighbors,
        ),
        candidates=tuple(_candidate(item) for item in response.candidates),
        provider_outcomes=tuple(
            RetrievalProviderOutcomeDto(item.provider_id, item.status, item.reason_code)
            for item in response.provider_outcomes
        ),
        degradation_reason_codes=response.degradation_reason_codes,
    )


def _candidate(item: core.LocatorResultCandidate) -> RetrievalCandidateDto:
    return RetrievalCandidateDto(
        locator=item.locator,
        source_key=item.source_key,
        document_key=item.document_key,
        chunk_key=item.chunk_key,
        canonical_identity=item.canonical_identity,
        canonical_version=item.canonical_version,
        lifecycle_status=item.lifecycle_status,
        relation=item.relation,
        distance=item.distance,
        provider_rank=item.provider_rank,
        fused_score=item.fused_score,
        base_score_picos=item.base_score_picos,
        preference_score_micros=item.preference_score_micros,
        preference_boost_micros=item.preference_boost_micros,
        rerank_score_picos=item.rerank_score_picos,
        source_requested_weight_micros=item.source_requested_weight_micros,
        source_matched_weight_micros=item.source_matched_weight_micros,
        actor_requested_weight_micros=item.actor_requested_weight_micros,
        actor_matched_weight_micros=item.actor_matched_weight_micros,
        time_requested_weight_micros=item.time_requested_weight_micros,
        time_matched_weight_micros=item.time_matched_weight_micros,
        matched_query_ids=item.matched_query_ids,
        contributions=tuple(
            RetrievalContributionDto(
                value.provider_id,
                value.query_id,
                value.provider_rank,
                value.provider_weight_micros,
                value.query_weight_micros,
                value.contribution_score_picos,
                value.provider_weight,
                value.query_weight,
                value.contribution,
                value.raw_score_kind,
                value.raw_score_value,
            )
            for value in item.contributions
        ),
        neighbors=tuple(
            RetrievalNeighborDto(
                value.locator,
                value.source_key,
                value.document_key,
                value.chunk_key,
                value.canonical_identity,
                value.canonical_version,
                value.lifecycle_status,
                value.relation,
                value.distance,
            )
            for value in item.neighbors
        ),
    )


def _interval(value: object | None) -> core.LocatorTimeInterval | None:
    if value is None:
        return None
    return core.LocatorTimeInterval(
        datetime.fromisoformat(value.start_at.replace("Z", "+00:00")),
        datetime.fromisoformat(value.end_at.replace("Z", "+00:00")),
    )


def _relative_interval(
    value: object | None,
) -> core.LocatorRelativeTimeInterval | None:
    if value is None:
        return None
    return core.LocatorRelativeTimeInterval(value.start_ms, value.end_ms)


__all__ = ("retrieval_request_to_core", "retrieval_response_to_contract")
