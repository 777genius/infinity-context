"""Deterministic weighted-RRF orchestration for locator-only Retrieval V2."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, replace

from infinity_context_core.features.context_building.domain.locator_retrieval_v2 import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    LOCATOR_RETRIEVAL_RANK_CONSTANT_V2,
    LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS_V2,
    MAX_PROVIDER_REGISTRATIONS_V2,
    CanonicalHydrationInvariantErrorV2,
    CanonicalLocatorCandidateV2,
    CanonicalLocatorReadV2,
    LocatorAppliedBoundsV2,
    LocatorHardFiltersV2,
    LocatorNeighborV2,
    LocatorProviderHitV2,
    LocatorProviderOutcomeV2,
    LocatorProviderResultV2,
    LocatorQueryVariantV2,
    LocatorRelativeTimeIntervalV2,
    LocatorResultCandidateV2,
    LocatorRetrievalBoundsV2,
    LocatorRetrievalCapabilityV2,
    LocatorRetrievalRequestV2,
    LocatorRetrievalResponseV2,
    LocatorRetrievalScopeV2,
    LocatorScoreContributionV2,
    LocatorSoftPreferencesV2,
    LocatorSourceGenerationV2,
    LocatorTimeIntervalV2,
    LocatorWeightedKeyV2,
    candidate_matches_request_v2,
    preference_evidence_v2,
)
from infinity_context_core.features.context_building.ports.locator_retrieval_v2 import (
    CanonicalLocatorReadPortV2,
    LocatorCandidateProviderPortV2,
)


def _utf8_sort_key(value: str) -> bytes:
    return value.encode("utf-8")


def _rrf_contribution_score_picos(
    provider_weight_micros: int,
    query_weight_micros: int,
    total_query_weight_micros: int,
    provider_rank: int,
) -> int:
    """Compute the authoritative contribution with integer round-half-even."""

    numerator = provider_weight_micros * query_weight_micros * 1_000_000
    denominator = total_query_weight_micros * (LOCATOR_RETRIEVAL_RANK_CONSTANT_V2 + provider_rank)
    quotient, remainder = divmod(numerator, denominator)
    doubled = remainder * 2
    if doubled > denominator or (doubled == denominator and quotient % 2 == 1):
        return quotient + 1
    return quotient


@dataclass(frozen=True, slots=True)
class LocatorProviderRegistrationV2:
    """Trusted provider configuration; request payloads cannot select or weight lanes."""

    provider_id: str
    provider: LocatorCandidateProviderPortV2
    weight_micros: int = 1_000_000
    required: bool = False
    healthy: bool = True
    profile_qualified: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("Locator provider_id must be a normalized non-blank string")
        if self.provider_id != self.provider_id.strip() or len(self.provider_id) > 256:
            raise ValueError("Locator provider_id must be a bounded normalized string")
        if not isinstance(self.weight_micros, int) or isinstance(self.weight_micros, bool):
            raise ValueError("Locator provider weight_micros must be an integer")
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("Locator provider weight_micros must be within 100000..10000000")
        if not isinstance(self.required, bool):
            raise ValueError("Locator provider required flag must be boolean")
        if not isinstance(self.healthy, bool) or not isinstance(self.profile_qualified, bool):
            raise ValueError("Locator provider health qualification flags must be boolean")
        if not callable(getattr(self.provider, "retrieve_locator_candidates", None)):
            raise ValueError("Locator provider registration has an invalid provider")


@dataclass(frozen=True, slots=True)
class _ProviderExecution:
    registration: LocatorProviderRegistrationV2
    result: LocatorProviderResultV2


@dataclass(frozen=True, slots=True)
class _Fused:
    canonical_identity: str
    canonical_version: int
    base_score_picos: int
    contributions: tuple[LocatorScoreContributionV2, ...]


@dataclass(frozen=True, slots=True)
class RetrieveLocatorsV2:
    """Execute generic fan-in, canonical filtering, fusion and neighbor attachment."""

    providers: tuple[LocatorProviderRegistrationV2, ...]
    canonical_reader: CanonicalLocatorReadPortV2
    capability: LocatorRetrievalCapabilityV2

    def __post_init__(self) -> None:
        providers = _registration_tuple(self.providers)
        object.__setattr__(self, "providers", providers)
        if not callable(getattr(self.canonical_reader, "hydrate_locator_candidates", None)):
            raise ValueError("Locator canonical reader lacks preliminary hydration")
        if not callable(getattr(self.canonical_reader, "hydrate_final_locator_read", None)):
            raise ValueError("Locator canonical reader lacks final read-session hydration")
        if not isinstance(self.capability, LocatorRetrievalCapabilityV2):
            raise ValueError("Locator retrieval requires a trusted capability descriptor")

    async def execute(self, request: LocatorRetrievalRequestV2) -> LocatorRetrievalResponseV2:
        request = _validated_request_copy(request)
        capability = LocatorRetrievalCapabilityV2(
            capability_fingerprint=self.capability.capability_fingerprint,
            profile_id=self.capability.profile_id,
            supports_neighbors=self.capability.supports_neighbors,
            service_revision=self.capability.service_revision,
            sdk_revision=self.capability.sdk_revision,
            index_profile_digest=self.capability.index_profile_digest,
            provider_lanes=self.capability.provider_lanes,
            endpoint=self.capability.endpoint,
            contract_version=self.capability.contract_version,
            ranking_policy=self.capability.ranking_policy,
            ranking_parameters=self.capability.ranking_parameters,
            attribute_schema=self.capability.attribute_schema,
            coverage=self.capability.coverage,
            bounds=self.capability.bounds,
            hard_filter_signals=self.capability.hard_filter_signals,
            soft_preference_signals=self.capability.soft_preference_signals,
            required_provider_lanes=self.capability.required_provider_lanes,
        )
        if (
            request.capability_fingerprint != capability.capability_fingerprint
            or request.profile_id != capability.profile_id
        ):
            return _bounded_empty_response(
                request,
                capability,
                status="unavailable",
                outcomes=(),
                degradation_codes=("capability_profile_mismatch",),
            )
        if capability.is_full_descriptor and not _registrations_match_capability(
            providers=self.providers, capability=capability
        ):
            return _bounded_empty_response(
                request,
                capability,
                status="unavailable",
                outcomes=(),
                degradation_codes=("capability_profile_mismatch",),
            )
        if request.bounds.neighbor_radius > 0 and not capability.supports_neighbors:
            return _bounded_empty_response(
                request,
                capability,
                status="unavailable",
                outcomes=(),
                degradation_codes=("neighbor_capability_unavailable",),
            )

        executions = await self._execute_all_providers(request)
        executions = tuple(
            sorted(
                executions,
                key=lambda item: _utf8_sort_key(item.registration.provider_id),
            )
        )
        outcomes = tuple(
            LocatorProviderOutcomeV2(
                item.registration.provider_id, item.result.status, item.result.reason_code
            )
            for item in executions
        )
        degradation_codes = _degradation_codes(executions)
        if any(
            item.registration.required and not _provider_is_qualified(item.result)
            for item in executions
        ):
            return _bounded_empty_response(
                request, capability, "unavailable", outcomes, degradation_codes
            )

        available = tuple(item for item in executions if _provider_is_qualified(item.result))
        if not available:
            status = (
                "unqualified"
                if any(item.result.status == "unqualified" for item in executions)
                else "unavailable"
            )
            return _bounded_empty_response(request, capability, status, outcomes, degradation_codes)

        fused = _fuse(request, available)[: request.bounds.candidate_limit]
        preliminary_rows = await self.canonical_reader.hydrate_locator_candidates(
            _validated_request_copy(request),
            tuple(item.canonical_identity for item in fused),
        )
        preliminary = _canonical_mapping(request, preliminary_rows, "preliminary hydration")
        selected = _select_results(request, fused, preliminary)
        selected = await self._hydrate_final_results(request, selected)
        response = LocatorRetrievalResponseV2(
            status="available" if selected else "unqualified",
            capability_fingerprint=capability.capability_fingerprint,
            profile_id=capability.profile_id,
            applied_bounds=_applied_bounds(request, selected),
            candidates=selected,
            provider_outcomes=outcomes,
            degradation_reason_codes=degradation_codes,
        )
        return _bounded_response(request, capability, response, outcomes, degradation_codes)

    async def _execute_all_providers(
        self, request: LocatorRetrievalRequestV2
    ) -> tuple[_ProviderExecution, ...]:
        registrations = _registration_tuple(self.providers)
        tasks = tuple(
            asyncio.create_task(self._execute_provider(item, request)) for item in registrations
        )
        try:
            return tuple(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _execute_provider(
        self,
        registration: LocatorProviderRegistrationV2,
        request: LocatorRetrievalRequestV2,
    ) -> _ProviderExecution:
        try:
            raw = await registration.provider.retrieve_locator_candidates(
                _validated_request_copy(request)
            )
            result = _validated_provider_result_copy(raw)
            _validate_provider_result(registration, request, result)
        except Exception:
            result = LocatorProviderResultV2(status="unavailable", reason_code="provider_error")
        return _ProviderExecution(registration, result)

    async def _hydrate_final_results(
        self,
        request: LocatorRetrievalRequestV2,
        selected: tuple[LocatorResultCandidateV2, ...],
    ) -> tuple[LocatorResultCandidateV2, ...]:
        if not selected:
            return ()
        raw = await self.canonical_reader.hydrate_final_locator_read(
            _validated_request_copy(request),
            tuple(item.canonical_identity for item in selected),
            request.bounds.neighbor_radius,
        )
        read = _validated_read_copy(raw)
        all_rows = (*read.seeds, *read.neighbors)
        _assert_snapshot_and_identity_invariants(all_rows, "final hydration")
        seeds = {
            item.canonical_identity: item
            for item in read.seeds
            if candidate_matches_request_v2(item, request)
        }
        seed_identities = set(seeds)
        neighbors = tuple(
            item
            for item in read.neighbors
            if candidate_matches_request_v2(item, request)
            and item.canonical_identity not in seed_identities
        )

        final: list[LocatorResultCandidateV2] = []
        proposed: dict[str, tuple[LocatorNeighborV2, ...]] = {}
        for ranked in selected:
            hydrated = seeds.get(ranked.canonical_identity)
            if hydrated is None or not _same_seed_coordinates(ranked, hydrated):
                continue
            proposed[ranked.canonical_identity] = _neighbors_for_seed(
                hydrated, neighbors, request.bounds.neighbor_radius
            )
            final.append(
                replace(
                    ranked,
                    locator=hydrated.locator,
                    source_key=hydrated.source_key,
                    document_key=hydrated.document_key,
                    chunk_key=hydrated.chunk_key,
                    canonical_version=hydrated.canonical_version,
                    lifecycle_status=hydrated.lifecycle_status,
                    neighbors=(),
                )
            )

        owners: dict[str, tuple[int, bytes, str]] = {}
        for seed_identity, values in proposed.items():
            for neighbor in values:
                owner = (abs(neighbor.distance), _utf8_sort_key(seed_identity), seed_identity)
                owners[neighbor.canonical_identity] = min(
                    owner, owners.get(neighbor.canonical_identity, owner)
                )
        return tuple(
            replace(
                item,
                neighbors=tuple(
                    neighbor
                    for neighbor in proposed[item.canonical_identity]
                    if owners[neighbor.canonical_identity][2] == item.canonical_identity
                ),
            )
            for item in final
        )


def _registration_tuple(values: object) -> tuple[LocatorProviderRegistrationV2, ...]:
    if isinstance(values, str | bytes):
        raise ValueError("Locator providers must be a collection")
    try:
        source = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError("Locator providers must be a collection") from error
    registrations = tuple(
        LocatorProviderRegistrationV2(
            item.provider_id,
            item.provider,
            item.weight_micros,
            item.required,
            item.healthy,
            item.profile_qualified,
        )
        if isinstance(item, LocatorProviderRegistrationV2)
        else _raise_invalid_registration()
        for item in source
    )
    if not 1 <= len(registrations) <= MAX_PROVIDER_REGISTRATIONS_V2:
        raise ValueError("Locator retrieval requires 1..4 providers")
    ids = tuple(item.provider_id for item in registrations)
    if len(set(ids)) != len(ids):
        raise ValueError("Locator retrieval provider ids must be unique")
    return registrations


def _raise_invalid_registration() -> LocatorProviderRegistrationV2:
    raise ValueError("Locator providers contain an invalid runtime type")


def _validated_request_copy(value: object) -> LocatorRetrievalRequestV2:
    if not isinstance(value, LocatorRetrievalRequestV2):
        raise ValueError("Locator request has an invalid runtime type")
    scope = value.scope
    filters = value.hard_filters
    preferences = value.soft_preferences
    bounds = value.bounds
    if not isinstance(scope, LocatorRetrievalScopeV2):
        raise ValueError("Locator request scope has an invalid runtime type")
    if not isinstance(filters, LocatorHardFiltersV2):
        raise ValueError("Locator request filters have an invalid runtime type")
    if not isinstance(preferences, LocatorSoftPreferencesV2):
        raise ValueError("Locator request preferences have an invalid runtime type")
    if not isinstance(bounds, LocatorRetrievalBoundsV2):
        raise ValueError("Locator request bounds have an invalid runtime type")
    queries = tuple(
        LocatorQueryVariantV2(item.query_id, item.query, item.weight_micros)
        if isinstance(item, LocatorQueryVariantV2)
        else _raise_invalid_query()
        for item in tuple(value.queries)
    )
    interval = filters.time_interval
    hard_interval = (
        None
        if interval is None
        else LocatorTimeIntervalV2(interval.start_at, interval.end_at)
        if isinstance(interval, LocatorTimeIntervalV2)
        else _raise_invalid_interval()
    )
    relative = filters.relative_time_interval
    hard_relative = (
        None
        if relative is None
        else LocatorRelativeTimeIntervalV2(relative.start_ms, relative.end_ms)
        if isinstance(relative, LocatorRelativeTimeIntervalV2)
        else _raise_invalid_relative_interval()
    )
    preference_interval = preferences.time_interval
    soft_interval = (
        None
        if preference_interval is None
        else LocatorTimeIntervalV2(preference_interval.start_at, preference_interval.end_at)
        if isinstance(preference_interval, LocatorTimeIntervalV2)
        else _raise_invalid_interval()
    )
    preference_relative = preferences.relative_time_interval
    soft_relative = (
        None
        if preference_relative is None
        else LocatorRelativeTimeIntervalV2(preference_relative.start_ms, preference_relative.end_ms)
        if isinstance(preference_relative, LocatorRelativeTimeIntervalV2)
        else _raise_invalid_relative_interval()
    )
    return LocatorRetrievalRequestV2(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2
        if value.contract_version == LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2
        else value.contract_version,
        value.capability_fingerprint,
        value.profile_id,
        LocatorRetrievalScopeV2(scope.space_id, scope.memory_scope_id, scope.thread_id),
        queries,
        LocatorHardFiltersV2(
            tuple(
                LocatorSourceGenerationV2(item.source_key, item.projection_generation)
                if isinstance(item, LocatorSourceGenerationV2)
                else _raise_invalid_source_generation()
                for item in tuple(filters.source_generations)
            ),
            tuple(filters.excluded_source_keys),
            tuple(filters.document_keys),
            tuple(filters.kinds),
            filters.category,
            tuple(filters.tags_any),
            tuple(filters.tags_all),
            tuple(filters.tags_none),
            tuple(filters.actor_keys),
            hard_interval,
            hard_relative,
        ),
        LocatorSoftPreferencesV2(
            tuple(
                LocatorWeightedKeyV2(item.key, item.weight_micros)
                if isinstance(item, LocatorWeightedKeyV2)
                else _raise_invalid_weighted_key()
                for item in tuple(preferences.source_preferences)
            ),
            tuple(
                LocatorWeightedKeyV2(item.key, item.weight_micros)
                if isinstance(item, LocatorWeightedKeyV2)
                else _raise_invalid_weighted_key()
                for item in tuple(preferences.actor_preferences)
            ),
            soft_interval,
            soft_relative,
            preferences.time_weight_micros,
        ),
        LocatorRetrievalBoundsV2(
            bounds.candidate_limit,
            bounds.result_limit,
            bounds.neighbor_radius,
            bounds.response_byte_limit,
            bounds.deadline_ms,
        ),
    )


def _raise_invalid_query() -> LocatorQueryVariantV2:
    raise ValueError("Locator queries contain an invalid runtime type")


def _raise_invalid_interval() -> LocatorTimeIntervalV2:
    raise ValueError("Locator interval has an invalid runtime type")


def _raise_invalid_relative_interval() -> LocatorRelativeTimeIntervalV2:
    raise ValueError("Locator relative interval has an invalid runtime type")


def _raise_invalid_source_generation() -> LocatorSourceGenerationV2:
    raise ValueError("Locator source_generations contains an invalid runtime type")


def _raise_invalid_weighted_key() -> LocatorWeightedKeyV2:
    raise ValueError("Locator preferences contain an invalid runtime type")


def _validated_provider_result_copy(value: object) -> LocatorProviderResultV2:
    if not isinstance(value, LocatorProviderResultV2):
        raise ValueError("Locator provider result has an invalid runtime type")
    hits = tuple(
        LocatorProviderHitV2(
            item.canonical_identity,
            item.canonical_version,
            item.provider_id,
            item.query_id,
            item.provider_rank,
            item.raw_score_kind,
            item.raw_score_value,
        )
        if isinstance(item, LocatorProviderHitV2)
        else _raise_invalid_hit()
        for item in tuple(value.hits)
    )
    return LocatorProviderResultV2(hits, value.status, value.reason_code)


def _raise_invalid_hit() -> LocatorProviderHitV2:
    raise ValueError("Locator provider hits contain an invalid runtime type")


def _validated_canonical_copy(value: object) -> CanonicalLocatorCandidateV2:
    if not isinstance(value, CanonicalLocatorCandidateV2):
        raise CanonicalHydrationInvariantErrorV2(
            "Canonical hydration returned an invalid row runtime type"
        )
    try:
        return replace(value, tags=tuple(value.tags), actor_keys=tuple(value.actor_keys))
    except (TypeError, ValueError) as error:
        raise CanonicalHydrationInvariantErrorV2(
            "Canonical hydration returned a malformed row"
        ) from error


def _validated_read_copy(value: object) -> CanonicalLocatorReadV2:
    if not isinstance(value, CanonicalLocatorReadV2):
        raise CanonicalHydrationInvariantErrorV2(
            "Final canonical hydration returned an invalid read envelope"
        )
    try:
        seeds = tuple(_validated_canonical_copy(item) for item in tuple(value.seeds))
        neighbors = tuple(_validated_canonical_copy(item) for item in tuple(value.neighbors))
        return CanonicalLocatorReadV2(seeds, neighbors)
    except CanonicalHydrationInvariantErrorV2:
        raise
    except (TypeError, ValueError) as error:
        raise CanonicalHydrationInvariantErrorV2(
            "Final canonical hydration returned malformed collections"
        ) from error


def _canonical_mapping(
    request: LocatorRetrievalRequestV2, values: object, label: str
) -> dict[str, CanonicalLocatorCandidateV2]:
    if isinstance(values, str | bytes):
        raise CanonicalHydrationInvariantErrorV2(f"{label} returned a malformed collection")
    try:
        candidates = tuple(  # type: ignore[arg-type]
            _validated_canonical_copy(item) for item in tuple(values)
        )
    except CanonicalHydrationInvariantErrorV2:
        raise
    except TypeError as error:
        raise CanonicalHydrationInvariantErrorV2(
            f"{label} returned a malformed collection"
        ) from error
    _assert_snapshot_and_identity_invariants(candidates, label)
    return {
        item.canonical_identity: item
        for item in candidates
        if candidate_matches_request_v2(item, request)
    }


def _assert_snapshot_and_identity_invariants(
    candidates: tuple[CanonicalLocatorCandidateV2, ...], label: str
) -> None:
    snapshots = {item.read_snapshot for item in candidates}
    if len(snapshots) > 1:
        raise CanonicalHydrationInvariantErrorV2(f"{label} mixed read snapshots")
    identities = tuple(item.canonical_identity for item in candidates)
    if len(set(identities)) != len(identities):
        raise CanonicalHydrationInvariantErrorV2(f"{label} returned duplicate identities")


def _validate_provider_result(
    registration: LocatorProviderRegistrationV2,
    request: LocatorRetrievalRequestV2,
    result: LocatorProviderResultV2,
) -> None:
    query_ids = {item.query_id for item in request.queries}
    if len(result.hits) > request.bounds.candidate_limit * len(request.queries):
        raise ValueError("Locator provider result exceeds candidate bound")
    for hit in result.hits:
        if hit.provider_id != registration.provider_id:
            raise ValueError("Locator provider returned a mismatched provider_id")
        if hit.query_id not in query_ids:
            raise ValueError("Locator provider returned an unknown query_id")


def _fuse(
    request: LocatorRetrievalRequestV2,
    executions: tuple[_ProviderExecution, ...],
) -> tuple[_Fused, ...]:
    query_weights = {item.query_id: item.weight_micros for item in request.queries}
    total_query_weight = sum(query_weights.values())
    unique: dict[tuple[str, str, str], tuple[LocatorProviderHitV2, int]] = {}
    for execution in executions:
        for hit in execution.result.hits:
            key = (hit.provider_id, hit.query_id, hit.canonical_identity)
            current = unique.get(key)
            if current is None or _hit_order(hit) < _hit_order(current[0]):
                unique[key] = (
                    hit,
                    execution.registration.weight_micros,
                )

    grouped: dict[tuple[str, int], list[LocatorScoreContributionV2]] = {}
    versions: dict[str, set[int]] = {}
    for hit, provider_weight in unique.values():
        versions.setdefault(hit.canonical_identity, set()).add(hit.canonical_version)
        query_weight = query_weights[hit.query_id]
        contribution_score_picos = _rrf_contribution_score_picos(
            provider_weight,
            query_weight,
            total_query_weight,
            hit.provider_rank,
        )
        grouped.setdefault((hit.canonical_identity, hit.canonical_version), []).append(
            LocatorScoreContributionV2(
                hit.provider_id,
                hit.query_id,
                hit.provider_rank,
                provider_weight,
                query_weight,
                contribution_score_picos,
                hit.raw_score_kind,
                hit.raw_score_value,
            )
        )
    fused: list[_Fused] = []
    for (identity, version), contributions in grouped.items():
        if len(versions[identity]) != 1:
            continue
        ordered = tuple(
            sorted(
                contributions,
                key=lambda item: (
                    _utf8_sort_key(item.provider_id),
                    _utf8_sort_key(item.query_id),
                ),
            )
        )
        fused.append(
            _Fused(
                identity,
                version,
                sum(item.contribution_score_picos for item in ordered),
                ordered,
            )
        )
    return tuple(
        sorted(
            fused,
            key=lambda item: (
                -item.base_score_picos,
                _utf8_sort_key(item.canonical_identity),
            ),
        )
    )


def _hit_order(hit: LocatorProviderHitV2) -> tuple[int, int, str, float]:
    return (
        hit.provider_rank,
        -hit.canonical_version,
        hit.raw_score_kind or "",
        hit.raw_score_value or 0.0,
    )


def _select_results(
    request: LocatorRetrievalRequestV2,
    fused: tuple[_Fused, ...],
    canonical: dict[str, CanonicalLocatorCandidateV2],
) -> tuple[LocatorResultCandidateV2, ...]:
    selected: list[LocatorResultCandidateV2] = []
    for item in fused:
        hydrated = canonical.get(item.canonical_identity)
        if hydrated is None or hydrated.canonical_version != item.canonical_version:
            continue
        evidence = preference_evidence_v2(
            request.soft_preferences,
            source_key=hydrated.source_key,
            actor_keys=hydrated.actor_keys,
            start_at=hydrated.start_at,
            end_at=hydrated.end_at,
            relative_start_ms=hydrated.relative_start_ms,
            relative_end_ms=hydrated.relative_end_ms,
        )
        selected.append(
            LocatorResultCandidateV2(
                hydrated.locator,
                hydrated.source_key,
                hydrated.document_key,
                hydrated.chunk_key,
                hydrated.canonical_identity,
                hydrated.canonical_version,
                hydrated.lifecycle_status,
                min(value.provider_rank for value in item.contributions),
                item.base_score_picos / LOCATOR_RETRIEVAL_SCORE_SCALE_PICOS_V2,
                tuple(
                    sorted(
                        {value.query_id for value in item.contributions},
                        key=_utf8_sort_key,
                    )
                ),
                item.contributions,
                item.base_score_picos,
                preference_score_micros=evidence.score_micros,
                preference_boost_micros=evidence.boost_micros,
                source_requested_weight_micros=evidence.source_requested_weight_micros,
                source_matched_weight_micros=evidence.source_matched_weight_micros,
                actor_requested_weight_micros=evidence.actor_requested_weight_micros,
                actor_matched_weight_micros=evidence.actor_matched_weight_micros,
                time_requested_weight_micros=evidence.time_requested_weight_micros,
                time_matched_weight_micros=evidence.time_matched_weight_micros,
            )
        )
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                -item.rerank_score_picos,  # type: ignore[operator]
                -item.base_score_picos,
                _utf8_sort_key(item.canonical_identity),
            ),
        )[: request.bounds.result_limit]
    )


def _same_seed_coordinates(
    ranked: LocatorResultCandidateV2, hydrated: CanonicalLocatorCandidateV2
) -> bool:
    return (
        ranked.canonical_identity,
        ranked.canonical_version,
        ranked.locator,
        ranked.source_key,
        ranked.document_key,
        ranked.chunk_key,
    ) == (
        hydrated.canonical_identity,
        hydrated.canonical_version,
        hydrated.locator,
        hydrated.source_key,
        hydrated.document_key,
        hydrated.chunk_key,
    )


def _neighbors_for_seed(
    seed: CanonicalLocatorCandidateV2,
    candidates: tuple[CanonicalLocatorCandidateV2, ...],
    radius: int,
) -> tuple[LocatorNeighborV2, ...]:
    if seed.sequence_ordinal is None or radius == 0:
        return ()
    positions: dict[int, CanonicalLocatorCandidateV2] = {}
    duplicate_positions: set[int] = set()
    for candidate in candidates:
        if (
            candidate.source_key != seed.source_key
            or candidate.projection_generation != seed.projection_generation
            or candidate.thread_id != seed.thread_id
            or candidate.read_snapshot != seed.read_snapshot
            or candidate.sequence_ordinal is None
        ):
            continue
        distance = candidate.sequence_ordinal - seed.sequence_ordinal
        if distance == 0 or abs(distance) > radius:
            continue
        if distance in positions:
            duplicate_positions.add(distance)
        else:
            positions[distance] = candidate
    for distance in duplicate_positions:
        positions.pop(distance, None)
    attached: list[LocatorNeighborV2] = []
    for distance in (*range(-radius, 0), *range(1, radius + 1)):
        candidate = positions.get(distance)
        direction = -1 if distance < 0 else 1
        contiguous = all(
            step in positions for step in range(direction, distance + direction, direction)
        )
        if candidate is None or not contiguous:
            continue
        attached.append(
            LocatorNeighborV2(
                candidate.locator,
                candidate.source_key,
                candidate.document_key,
                candidate.chunk_key,
                candidate.canonical_identity,
                candidate.canonical_version,
                candidate.lifecycle_status,
                "neighbor",
                distance,
            )
        )
    return tuple(attached)


def _degradation_codes(executions: tuple[_ProviderExecution, ...]) -> tuple[str, ...]:
    codes: set[str] = set()
    for item in executions:
        if item.registration.required or _provider_is_qualified(item.result):
            continue
        if item.result.reason_code == "provider_error":
            codes.add("optional_provider_failed")
        elif item.result.status == "unqualified":
            codes.add("optional_provider_unqualified")
        else:
            codes.add("optional_provider_unavailable")
    return tuple(sorted(codes, key=_utf8_sort_key))


def _provider_is_qualified(result: LocatorProviderResultV2) -> bool:
    return result.status == "available" and result.reason_code != "provider_truncated"


def _registrations_match_capability(
    *,
    providers: tuple[LocatorProviderRegistrationV2, ...],
    capability: LocatorRetrievalCapabilityV2,
) -> bool:
    if not capability.profile_qualified:
        return False
    actual = tuple(
        sorted(
            (
                (
                    item.provider_id,
                    item.required,
                    item.healthy,
                    item.weight_micros,
                    item.profile_qualified,
                )
                for item in providers
            ),
            key=lambda item: _utf8_sort_key(item[0]),
        )
    )
    expected = tuple(
        (
            item.provider_id,
            item.required,
            item.healthy,
            item.weight_micros,
            item.profile_qualified,
        )
        for item in capability.provider_lanes
    )
    return actual == expected


def _response_size_bytes(response: LocatorRetrievalResponseV2) -> int:
    encoded = json.dumps(
        _canonical_json_order(asdict(response)),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(encoded)


def _canonical_json_order(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonical_json_order(value[key]) for key in sorted(value, key=_utf8_sort_key)}
    if isinstance(value, tuple | list):
        return [_canonical_json_order(item) for item in value]
    return value


def _applied_bounds(
    request: LocatorRetrievalRequestV2,
    candidates: tuple[LocatorResultCandidateV2, ...],
) -> LocatorAppliedBoundsV2:
    return LocatorAppliedBoundsV2(
        request.bounds.candidate_limit,
        request.bounds.result_limit,
        request.bounds.neighbor_radius,
        request.bounds.response_byte_limit,
        request.bounds.deadline_ms,
        len(candidates),
        sum(len(item.neighbors) for item in candidates),
    )


def _bounded_response(
    request: LocatorRetrievalRequestV2,
    capability: LocatorRetrievalCapabilityV2,
    response: LocatorRetrievalResponseV2,
    outcomes: tuple[LocatorProviderOutcomeV2, ...],
    degradation_codes: tuple[str, ...],
) -> LocatorRetrievalResponseV2:
    if _response_size_bytes(response) <= request.bounds.response_byte_limit:
        return response
    return _bounded_empty_response(
        request,
        capability,
        "unavailable",
        outcomes,
        tuple(
            sorted(
                {*degradation_codes, "response_byte_limit_exceeded"},
                key=_utf8_sort_key,
            )
        ),
    )


def _bounded_empty_response(
    request: LocatorRetrievalRequestV2,
    capability: LocatorRetrievalCapabilityV2,
    status: str,
    outcomes: tuple[LocatorProviderOutcomeV2, ...],
    degradation_codes: tuple[str, ...],
) -> LocatorRetrievalResponseV2:
    response = LocatorRetrievalResponseV2(
        status,
        capability.capability_fingerprint,
        capability.profile_id,
        _applied_bounds(request, ()),
        (),
        outcomes,
        tuple(sorted(set(degradation_codes), key=_utf8_sort_key)),
    )
    if _response_size_bytes(response) > request.bounds.response_byte_limit:
        raise ValueError("Locator response_byte_limit cannot hold the mandatory envelope")
    return response


__all__ = ("LocatorProviderRegistrationV2", "RetrieveLocatorsV2")
