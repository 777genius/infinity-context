from __future__ import annotations

import asyncio

import infinity_context_core.features.context_building.public as core
import pytest
from infinity_context_server.features.context_building.retrieval_service import (
    LocatorRetrievalService,
    RetrievalLaneRuntime,
    RetrievalProfileConflict,
)


def test_fingerprint_binds_health_requiredness_revision_and_index_profile() -> None:
    state = {"healthy": True}

    async def health():
        return state["healthy"]

    service = LocatorRetrievalService(
        lanes=(RetrievalLaneRuntime("postgres_keyword", _Provider(), health, True),),
        canonical_reader=_Reader(),
        service_revision="1" * 40,
        index_profile_digest="a" * 64,
        profile_kind="lexical",
    )
    first = asyncio.run(service.descriptor())
    state["healthy"] = False
    drifted = asyncio.run(service.descriptor())
    assert first.capability_fingerprint != drifted.capability_fingerprint
    assert first.profile_id == drifted.profile_id
    payload = first.to_dict()
    assert payload["attribute_schema"] == "document-retrieval-projection.v1"
    assert payload["ranking_policy"] == "weighted_rrf_canonical_preferences.v1"
    assert payload["ranking_parameters"]["contribution_rounding"] == "round_half_even"
    assert payload["provider_lanes"][0]["required"] is True
    assert payload["provider_lanes"][0]["weight_micros"] == 1_000_000
    assert payload["supports_neighbors"] is True
    assert payload["bounds"]["weight_micros"] == [100_000, 10_000_000]
    assert payload["bounds"]["provider_rank"] == [1, 1000]


def test_stale_profile_and_required_health_fail_before_provider_call() -> None:
    provider = _CountingProvider()

    async def healthy():
        return True

    service = LocatorRetrievalService(
        lanes=(RetrievalLaneRuntime("postgres_keyword", provider, healthy, True),),
        canonical_reader=_Reader(),
        service_revision="1" * 40,
        index_profile_digest="b" * 64,
        profile_kind="lexical",
    )
    request = _request("f" * 64, "stale")
    with pytest.raises(RetrievalProfileConflict):
        asyncio.run(service.execute(request))
    assert provider.calls == 0

    async def unhealthy():
        return False

    unavailable = LocatorRetrievalService(
        lanes=(RetrievalLaneRuntime("postgres_keyword", provider, unhealthy, True),),
        canonical_reader=_Reader(),
        service_revision="1" * 40,
        index_profile_digest="b" * 64,
        profile_kind="lexical",
    )
    descriptor = asyncio.run(unavailable.descriptor())
    result = asyncio.run(
        unavailable.execute(_request(descriptor.capability_fingerprint, descriptor.profile_id))
    )
    assert result.status == "unavailable"
    assert provider.calls == 0


def _request(fingerprint: str, profile: str) -> core.LocatorRetrievalRequest:
    return core.LocatorRetrievalRequest(
        "context-retrieval.v2",
        fingerprint,
        profile,
        core.LocatorRetrievalScope("space", "scope"),
        (core.LocatorQueryVariant("q1", "query"),),
        core.LocatorHardFilters(
            source_generations=(core.LocatorSourceGeneration("source", "generation"),)
        ),
        core.LocatorSoftPreferences(),
        core.LocatorRetrievalBounds(candidate_limit=1, result_limit=1),
    )


class _Provider:
    async def retrieve_locator_candidates(self, request):  # pragma: no cover
        raise AssertionError("descriptor must not call providers")


class _CountingProvider:
    calls = 0

    async def retrieve_locator_candidates(self, request):
        self.calls += 1
        return core.LocatorProviderResult(status="available")


class _Reader:
    async def hydrate_locator_candidates(self, request, identities):  # pragma: no cover
        return ()

    async def hydrate_final_locator_read(self, request, identities, radius):  # pragma: no cover
        raise AssertionError
