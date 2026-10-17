from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as core
import pytest
from infinity_context_server.config import Settings
from infinity_context_server.retrieval_profile_composition import (
    ProfileAwareLocatorRetrievalService,
)
from pydantic import ValidationError


def test_retrieval_lane_weight_settings_defaults_env_and_bounds(monkeypatch) -> None:
    defaults = Settings(_env_file=None)
    assert defaults.retrieval_postgres_keyword_weight_micros == 1_000_000
    assert defaults.retrieval_qdrant_dense_weight_micros == 1_000_000

    monkeypatch.setenv("MEMORY_RETRIEVAL_POSTGRES_KEYWORD_WEIGHT_MICROS", "250000")
    monkeypatch.setenv("MEMORY_RETRIEVAL_QDRANT_DENSE_WEIGHT_MICROS", "1750000")
    configured = Settings(_env_file=None)
    assert configured.retrieval_postgres_keyword_weight_micros == 250_000
    assert configured.retrieval_qdrant_dense_weight_micros == 1_750_000

    for field, value in (
        ("retrieval_postgres_keyword_weight_micros", 99_999),
        ("retrieval_qdrant_dense_weight_micros", 10_000_001),
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})


def test_composed_weights_change_weighted_rrf_order(monkeypatch) -> None:
    keyword = _Provider("postgres_keyword", "keyword-first", rank=1)
    dense = _Provider("qdrant_dense", "dense-second", rank=2)
    reader = _Reader((_candidate("keyword-first"), _candidate("dense-second")))
    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition.PostgresLocatorCandidateProvider",
        lambda _sessions: keyword,
    )
    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition.QdrantContextCandidateProvider",
        lambda _adapter, _embeddings: dense,
    )
    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition.PostgresCanonicalLocatorReader",
        lambda _sessions: reader,
    )
    active = SimpleNamespace(profile_id="weighted-profile", profile_digest="a" * 64)
    configured = Settings(
        _env_file=None,
        retrieval_postgres_keyword_weight_micros=250_000,
        retrieval_qdrant_dense_weight_micros=1_000_000,
    )

    def composed_service(keyword_weight: int, dense_weight: int):
        return ProfileAwareLocatorRetrievalService(
            registry=SimpleNamespace(),
            projection=SimpleNamespace(adapter_for=lambda _active: object()),
            sessions=object(),
            query_embeddings=object(),
            service_revision="1" * 40,
            postgres_keyword_weight_micros=keyword_weight,
            qdrant_dense_weight_micros=dense_weight,
        )._service_for_active(active, admission_proven=True)

    equal_service = composed_service(1_000_000, 1_000_000)
    equal_descriptor = asyncio.run(equal_service.descriptor())
    equal_response = asyncio.run(
        equal_service.execute(
            _request(equal_descriptor.capability_fingerprint, equal_descriptor.profile_id)
        )
    )
    assert tuple(item.canonical_identity for item in equal_response.candidates) == (
        "keyword-first",
        "dense-second",
    )

    service = composed_service(
        configured.retrieval_postgres_keyword_weight_micros,
        configured.retrieval_qdrant_dense_weight_micros,
    )

    descriptor = asyncio.run(service.descriptor())
    assert {
        lane.provider_id: lane.weight_micros for lane in descriptor.provider_lanes
    } == {"postgres_keyword": 250_000, "qdrant_dense": 1_000_000}
    assert descriptor.capability_fingerprint != equal_descriptor.capability_fingerprint
    response = asyncio.run(
        service.execute(_request(descriptor.capability_fingerprint, descriptor.profile_id))
    )
    assert tuple(item.canonical_identity for item in response.candidates) == (
        "dense-second",
        "keyword-first",
    )


class _Provider:
    def __init__(self, provider_id: str, identity: str, *, rank: int) -> None:
        self.provider_id = provider_id
        self.identity = identity
        self.rank = rank

    async def retrieve_locator_candidates(self, _request):
        return core.LocatorProviderResult(
            hits=(
                core.LocatorProviderHit(
                    self.identity, 1, self.provider_id, "q1", self.rank
                ),
            )
        )


class _Reader:
    def __init__(self, candidates) -> None:
        self.candidates = candidates

    async def hydrate_locator_candidates(self, _request, identities):
        return tuple(item for item in self.candidates if item.canonical_identity in identities)

    async def hydrate_final_locator_read(self, _request, identities, _radius):
        return core.CanonicalLocatorRead(
            tuple(item for item in self.candidates if item.canonical_identity in identities)
        )


def _request(fingerprint: str, profile_id: str) -> core.LocatorRetrievalRequest:
    return core.LocatorRetrievalRequest(
        "context-retrieval.v2",
        fingerprint,
        profile_id,
        core.LocatorRetrievalScope("space", "scope"),
        (core.LocatorQueryVariant("q1", "query"),),
        core.LocatorHardFilters(
            source_generations=(core.LocatorSourceGeneration("source", "generation"),)
        ),
        core.LocatorSoftPreferences(),
        core.LocatorRetrievalBounds(candidate_limit=2, result_limit=2),
    )


def _candidate(identity: str) -> core.CanonicalLocatorCandidate:
    return core.CanonicalLocatorCandidate(
        locator=f"opaque:{identity}",
        canonical_identity=identity,
        canonical_version=1,
        lifecycle_status="active",
        space_id="space",
        memory_scope_id="scope",
        source_key="source",
        document_key="document",
        chunk_key=f"chunk:{identity}",
        projection_generation="generation",
        kind="turn",
        category="generic",
        read_snapshot="snapshot",
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
