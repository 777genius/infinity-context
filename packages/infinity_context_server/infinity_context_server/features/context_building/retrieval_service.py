"""Contract-C capability snapshots and Retrieval V2 execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter

import infinity_context_core.features.context_building.public as core
from infinity_context_contracts.features.context_building import (
    CAPABILITY_ATTRIBUTE_SCHEMA_V2,
    CAPABILITY_CONTRACT_VERSION_V2,
    CAPABILITY_COVERAGE_V2,
    CAPABILITY_ENDPOINT_V2,
    CAPABILITY_HARD_FILTER_SIGNALS_V2,
    CAPABILITY_RANKING_POLICY_V2,
    CAPABILITY_SOFT_PREFERENCE_SIGNALS_V2,
    RetrievalV2CapabilityBoundsDto,
    RetrievalV2CapabilityDto,
    RetrievalV2ProviderLaneCapabilityDto,
    RetrievalV2RankingParametersDto,
    capability_fingerprint_v2,
)


class RetrievalProfileConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RetrievalLaneRuntime:
    provider_id: str
    provider: core.LocatorCandidateProviderPortV2
    health: Callable[[], Awaitable[bool]]
    required: bool = True
    weight_micros: int = 1_000_000
    profile_qualification: Callable[[], Awaitable[bool]] | None = None

    def __post_init__(self) -> None:
        if not 100_000 <= self.weight_micros <= 10_000_000:
            raise ValueError("Retrieval lane weight_micros is outside Contract C")


@dataclass(frozen=True, slots=True)
class LocatorRetrievalService:
    """Capture one immutable health/capability snapshot per operation."""

    lanes: tuple[RetrievalLaneRuntime, ...]
    canonical_reader: core.CanonicalLocatorReadPortV2
    service_revision: str
    index_profile_digest: str
    profile_kind: str
    sdk_revision: str | None = None
    supports_neighbors: bool = True
    diagnostics: object | None = None
    profile_id_override: str | None = None

    async def descriptor(self) -> RetrievalV2CapabilityDto:
        sdk_revision = self.sdk_revision or self.service_revision
        lanes: list[RetrievalV2ProviderLaneCapabilityDto] = []
        for lane in sorted(self.lanes, key=lambda item: item.provider_id.encode("utf-8")):
            try:
                healthy = bool(await lane.health())
            except Exception:
                healthy = False
            qualified = healthy
            if healthy and lane.profile_qualification is not None:
                try:
                    qualified = bool(await lane.profile_qualification())
                except Exception:
                    qualified = False
            lanes.append(
                RetrievalV2ProviderLaneCapabilityDto(
                    provider_id=lane.provider_id,
                    required=lane.required,
                    healthy=healthy,
                    weight_micros=lane.weight_micros,
                    profile_qualified=qualified,
                )
            )
        required = tuple(lane.provider_id for lane in lanes if lane.required)
        profile_id = self.profile_id_override or (
            f"locator-v2-{self.profile_kind}-{self.index_profile_digest}"
        )
        payload = {
            "endpoint": CAPABILITY_ENDPOINT_V2,
            "contract_version": CAPABILITY_CONTRACT_VERSION_V2,
            "ranking_policy": CAPABILITY_RANKING_POLICY_V2,
            "ranking_parameters": RetrievalV2RankingParametersDto().to_dict(),
            "capability_fingerprint": "0" * 64,
            "profile_id": profile_id,
            "service_revision": self.service_revision,
            "sdk_revision": sdk_revision,
            "attribute_schema": CAPABILITY_ATTRIBUTE_SCHEMA_V2,
            "index_profile_digest": self.index_profile_digest,
            "coverage": CAPABILITY_COVERAGE_V2,
            "supports_neighbors": self.supports_neighbors,
            "bounds": RetrievalV2CapabilityBoundsDto().to_dict(),
            "hard_filter_signals": list(CAPABILITY_HARD_FILTER_SIGNALS_V2),
            "soft_preference_signals": list(CAPABILITY_SOFT_PREFERENCE_SIGNALS_V2),
            "required_provider_lanes": list(required),
            "provider_lanes": [lane.to_dict() for lane in lanes],
        }
        payload["capability_fingerprint"] = capability_fingerprint_v2(payload)
        record = getattr(self.diagnostics, "record", None)
        if callable(record):
            for lane in lanes:
                if not lane.healthy:
                    record(profile_id, f"lane_failure:{lane.provider_id}")
                elif not lane.profile_qualified:
                    record(profile_id, f"profile_failure:{lane.provider_id}")
        return RetrievalV2CapabilityDto.from_dict(payload)

    async def execute(
        self, request: core.LocatorRetrievalRequestV2
    ) -> core.LocatorRetrievalResponseV2:
        started = perf_counter()
        descriptor = await self.descriptor()
        if (
            request.capability_fingerprint != descriptor.capability_fingerprint
            or request.profile_id != descriptor.profile_id
        ):
            record = getattr(self.diagnostics, "record", None)
            if callable(record):
                record(descriptor.profile_id, "fingerprint_failure")
            raise RetrievalProfileConflict("retrieval capability/profile is stale or mismatched")
        lane_by_id = {lane.provider_id: lane for lane in descriptor.provider_lanes}
        registrations = tuple(
            core.LocatorProviderRegistrationV2(
                provider_id=lane.provider_id,
                provider=lane.provider,
                weight_micros=lane.weight_micros,
                required=lane.required,
                healthy=lane_by_id[lane.provider_id].healthy,
                profile_qualified=lane_by_id[lane.provider_id].profile_qualified,
            )
            for lane in self.lanes
        )
        capability = core.LocatorRetrievalCapabilityV2(
            capability_fingerprint=descriptor.capability_fingerprint,
            profile_id=descriptor.profile_id,
            supports_neighbors=descriptor.supports_neighbors,
            service_revision=descriptor.service_revision,
            sdk_revision=descriptor.sdk_revision,
            index_profile_digest=descriptor.index_profile_digest,
            provider_lanes=tuple(
                core.LocatorProviderLaneCapabilityV2(
                    lane.provider_id,
                    lane.required,
                    lane.healthy,
                    lane.weight_micros,
                    lane.profile_qualified,
                )
                for lane in descriptor.provider_lanes
            ),
            ranking_policy=descriptor.ranking_policy,
            ranking_parameters=core.LocatorRankingParametersV2(
                descriptor.ranking_parameters.rank_constant,
                descriptor.ranking_parameters.weight_scale_micros,
                descriptor.ranking_parameters.score_scale_picos,
                descriptor.ranking_parameters.preference_scale_micros,
                descriptor.ranking_parameters.max_preference_boost_micros,
                descriptor.ranking_parameters.contribution_rounding,
                descriptor.ranking_parameters.preference_rounding,
                descriptor.ranking_parameters.canonical_signal_match_policy,
            ),
            required_provider_lanes=tuple(descriptor.required_provider_lanes),
        )
        result = await core.RetrieveLocatorsV2(
            providers=registrations,
            canonical_reader=self.canonical_reader,
            capability=capability,
        ).execute(request)
        record = getattr(self.diagnostics, "record", None)
        if callable(record):
            record(descriptor.profile_id, f"request_outcome:{result.status}")
            record(descriptor.profile_id, "request_latency_ms", (perf_counter() - started) * 1000)
        return result


__all__ = (
    "LocatorRetrievalService",
    "RetrievalLaneRuntime",
    "RetrievalProfileConflict",
)
