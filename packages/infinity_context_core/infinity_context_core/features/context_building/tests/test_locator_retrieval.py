"""Provider-free contracts for locator-only Retrieval."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import pytest

from infinity_context_core.features.context_building.public import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION,
    CanonicalHydrationInvariantError,
    CanonicalLocatorCandidate,
    CanonicalLocatorRead,
    LocatorHardFilters,
    LocatorProviderHit,
    LocatorProviderLaneCapability,
    LocatorProviderRegistration,
    LocatorProviderResult,
    LocatorQueryVariant,
    LocatorRelativeTimeInterval,
    LocatorRetrievalBounds,
    LocatorRetrievalCapability,
    LocatorRetrievalRequest,
    LocatorRetrievalScope,
    LocatorSoftPreferences,
    LocatorSourceGeneration,
    LocatorTimeInterval,
    LocatorWeightedKey,
    RetrieveLocators,
)

FINGERPRINT = "a" * 64


@dataclass
class _Provider:
    hits: tuple[LocatorProviderHit, ...] = ()
    error: BaseException | None = None

    async def retrieve_locator_candidates(
        self, request: LocatorRetrievalRequest
    ) -> LocatorProviderResult:
        self.requests = (*getattr(self, "requests", ()), request)
        if self.error is not None:
            raise self.error
        return LocatorProviderResult(hits=self.hits)


@dataclass
class _Hydrator:
    candidates: tuple[CanonicalLocatorCandidate, ...]
    neighbors: tuple[CanonicalLocatorCandidate, ...] = ()
    final_candidates: tuple[CanonicalLocatorCandidate, ...] | None = None

    async def hydrate_locator_candidates(
        self,
        _request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
    ) -> tuple[CanonicalLocatorCandidate, ...]:
        selected = set(canonical_identities)
        return tuple(
            item
            for item in self.candidates
            if not isinstance(item, CanonicalLocatorCandidate)
            or item.canonical_identity in selected
        )

    async def hydrate_final_locator_read(
        self,
        _request: LocatorRetrievalRequest,
        canonical_identities: tuple[str, ...],
        _radius: int,
    ) -> CanonicalLocatorRead:
        selected = set(canonical_identities)
        source = self.candidates if self.final_candidates is None else self.final_candidates
        seeds = tuple(item for item in source if item.canonical_identity in selected)
        return CanonicalLocatorRead(seeds, self.neighbors)


def test_request_bounds_and_unknown_signals_fail_closed() -> None:
    with pytest.raises(ValueError, match="1..6"):
        _request(queries=())
    with pytest.raises(ValueError, match="1..6"):
        _request(queries=tuple(_query(str(index)) for index in range(7)))
    with pytest.raises(ValueError, match="weight"):
        _query("q", weight=0.0)
    with pytest.raises(ValueError, match="neighbor_radius"):
        _request(bounds=LocatorRetrievalBounds(neighbor_radius=3))
    with pytest.raises(ValueError, match="response_byte_limit"):
        _request(bounds=LocatorRetrievalBounds(response_byte_limit=0))
    with pytest.raises(ValueError, match="response_byte_limit"):
        _request(bounds=LocatorRetrievalBounds(response_byte_limit=16_383))
    with pytest.raises(ValueError, match="score kind"):
        _hit("a", score_kind="provider_magic")


def test_capability_collections_and_bounds_are_deeply_detached() -> None:
    default = LocatorRetrievalCapability(FINGERPRINT, "profile")
    hard = list(default.hard_filter_signals)
    soft = list(default.soft_preference_signals)
    bounds_values = {name: list(getattr(default.bounds, name)) for name in default.bounds.__slots__}
    bounds = default.bounds.__class__(**bounds_values)
    capability = LocatorRetrievalCapability(
        FINGERPRINT,
        "profile",
        bounds=bounds,
        hard_filter_signals=hard,  # type: ignore[arg-type]
        soft_preference_signals=soft,  # type: ignore[arg-type]
    )

    hard.clear()
    soft.clear()
    for values in bounds_values.values():
        values.clear()

    assert capability.hard_filter_signals == default.hard_filter_signals
    assert capability.soft_preference_signals == default.soft_preference_signals
    assert all(
        isinstance(getattr(capability.bounds, name), tuple) for name in capability.bounds.__slots__
    )

    lanes = [
        LocatorProviderLaneCapability("postgres", True, True, 1_000_000, True),
        LocatorProviderLaneCapability("qdrant", True, True, 1_250_000, True),
    ]
    required = ["postgres", "qdrant"]
    full = LocatorRetrievalCapability(
        FINGERPRINT,
        "profile",
        service_revision="a" * 40,
        index_profile_digest="b" * 64,
        provider_lanes=lanes,  # type: ignore[arg-type]
        required_provider_lanes=required,  # type: ignore[arg-type]
    )
    lanes.clear()
    required.clear()
    assert tuple(lane.provider_id for lane in full.provider_lanes) == (
        "postgres",
        "qdrant",
    )
    assert full.required_provider_lanes == ("postgres", "qdrant")


def test_provider_weight_micros_are_converted_only_for_rrf_execution() -> None:
    provider = _Provider((_hit("candidate"),))
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", provider, weight_micros=1_250_000),),
            _Hydrator((_canonical("candidate"),)),
        ).execute(_request())
    )

    contribution = response.candidates[0].contributions[0]
    assert contribution.provider_weight == 1.25
    assert contribution.contribution == round(1.25 / 61, 12)


def test_weighted_rrf_is_deterministic_under_provider_hit_and_registration_shuffle() -> None:
    hits = [
        _hit("tie-b", provider="dense", query="q1", rank=1),
        _hit("tie-a", provider="dense", query="q1", rank=1),
        _hit("tie-b", provider="lexical", query="q2", rank=1),
        _hit("tie-a", provider="lexical", query="q2", rank=1),
    ]
    expected: tuple[tuple[str, float], ...] | None = None
    for seed in range(100):
        shuffled = hits.copy()
        random.Random(seed).shuffle(shuffled)
        dense = _Provider(tuple(hit for hit in shuffled if hit.provider_id == "dense"))
        lexical = _Provider(tuple(hit for hit in shuffled if hit.provider_id == "lexical"))
        registrations = [
            LocatorProviderRegistration("dense", dense),
            LocatorProviderRegistration("lexical", lexical),
        ]
        random.Random(seed + 100).shuffle(registrations)
        response = asyncio.run(
            _retrieve(
                tuple(registrations),
                _Hydrator((_canonical("tie-a"), _canonical("tie-b"))),
            ).execute(
                _request(
                    queries=(
                        _query("q1", weight=0.5),
                        _query("q2", weight=2.0),
                    ),
                    preferences=LocatorSoftPreferences(
                        actor_preferences=(LocatorWeightedKey("actor-ok", 1_000_000),)
                    ),
                )
            )
        )
        actual = tuple((item.canonical_identity, item.fused_score) for item in response.candidates)
        expected = actual if expected is None else expected
        assert actual == expected
    assert tuple(identity for identity, _score in expected or ()) == ("tie-a", "tie-b")


def test_no_preferences_preserve_base_order_and_zero_rerank_evidence() -> None:
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", _Provider((_hit("b"), _hit("a")))),),
            _Hydrator((_canonical("a"), _canonical("b"))),
        ).execute(_request())
    )
    assert tuple(item.canonical_identity for item in response.candidates) == ("a", "b")
    for item in response.candidates:
        assert item.preference_score_micros == 0
        assert item.preference_boost_micros == 0
        assert item.rerank_score_picos == round(item.fused_score * 1_000_000_000_000)


def test_source_preference_match_reranks_but_miss_does_not() -> None:
    request = _request(
        filters=LocatorHardFilters(
            (
                LocatorSourceGeneration("source-ok", "generation-2"),
                LocatorSourceGeneration("source-preferred", "generation-2"),
            )
        ),
        preferences=LocatorSoftPreferences(
            source_preferences=(LocatorWeightedKey("source-preferred", 1_000_000),)
        ),
    )
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "dense", _Provider((_hit("semantic-first", rank=1), _hit("preferred", rank=2)))
                ),
            ),
            _Hydrator(
                (
                    _canonical("semantic-first"),
                    _canonical("preferred", source_key="source-preferred"),
                )
            ),
        ).execute(request)
    )
    assert tuple(item.canonical_identity for item in response.candidates) == (
        "preferred",
        "semantic-first",
    )
    assert response.candidates[0].preference_score_micros == 1_000_000
    assert response.candidates[0].preference_boost_micros == 250_000
    assert response.candidates[1].preference_score_micros == 0


def test_actor_preferences_sum_all_requested_matches_for_multi_actor_candidate() -> None:
    request = _request(
        preferences=LocatorSoftPreferences(
            actor_preferences=(
                LocatorWeightedKey("actor-a", 1_000_000),
                LocatorWeightedKey("actor-b", 3_000_000),
                LocatorWeightedKey("actor-miss", 4_000_000),
            )
        )
    )
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", _Provider((_hit("multi"),))),),
            _Hydrator((_canonical("multi", actor_keys=("actor-a", "actor-b")),)),
        ).execute(request)
    )
    candidate = response.candidates[0]
    assert candidate.preference_score_micros == 500_000
    assert candidate.preference_boost_micros == 125_000


@pytest.mark.parametrize(
    ("preferences", "matching", "nonmatching", "missing"),
    (
        (
            LocatorSoftPreferences(
                time_interval=LocatorTimeInterval(
                    datetime(2026, 1, 1, 10, tzinfo=UTC),
                    datetime(2026, 1, 1, 20, tzinfo=UTC),
                ),
                time_weight_micros=1_000_000,
            ),
            {
                "start_at": datetime(2026, 1, 1, 20, tzinfo=UTC),
                "end_at": datetime(2026, 1, 1, 21, tzinfo=UTC),
            },
            {
                "start_at": datetime(2026, 1, 1, 21, tzinfo=UTC),
                "end_at": datetime(2026, 1, 1, 22, tzinfo=UTC),
            },
            {"start_at": None, "end_at": None},
        ),
        (
            LocatorSoftPreferences(
                relative_time_interval=LocatorRelativeTimeInterval(10, 20),
                time_weight_micros=1_000_000,
            ),
            {"relative_start_ms": 20, "relative_end_ms": 21},
            {"relative_start_ms": 21, "relative_end_ms": 22},
            {"relative_start_ms": None, "relative_end_ms": None},
        ),
    ),
)
def test_time_preferences_match_only_the_explicit_coordinate_and_missing_is_a_miss(
    preferences: LocatorSoftPreferences,
    matching: dict[str, object],
    nonmatching: dict[str, object],
    missing: dict[str, object],
) -> None:
    candidates = (
        _canonical("match", **matching),
        _canonical("nonmatch", **nonmatching),
        _canonical("missing", **missing),
    )
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "dense",
                    _Provider(tuple(_hit(item.canonical_identity) for item in candidates)),
                ),
            ),
            _Hydrator(candidates),
        ).execute(_request(preferences=preferences))
    )
    evidence = {
        item.canonical_identity: item.preference_score_micros for item in response.candidates
    }
    assert evidence == {"match": 1_000_000, "missing": 0, "nonmatch": 0}


def test_combined_extreme_preferences_are_bounded_and_reconstruct_exactly() -> None:
    preferences = LocatorSoftPreferences(
        source_preferences=(LocatorWeightedKey("source-ok", 10_000_000),),
        actor_preferences=(LocatorWeightedKey("actor-ok", 100_000),),
        relative_time_interval=LocatorRelativeTimeInterval(10, 20),
        time_weight_micros=10_000_000,
    )
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", _Provider((_hit("a"),))),),
            _Hydrator((_canonical("a", relative_start_ms=11, relative_end_ms=12),)),
        ).execute(_request(preferences=preferences))
    )
    candidate = response.candidates[0]
    assert candidate.preference_score_micros == 1_000_000
    assert candidate.preference_boost_micros == 250_000
    base_picos = round(candidate.fused_score * 1_000_000_000_000)
    assert candidate.rerank_score_picos == base_picos * 1_250_000 // 1_000_000


def test_inadmissible_candidates_never_receive_preference_evidence() -> None:
    request = _request(
        preferences=LocatorSoftPreferences(
            source_preferences=(LocatorWeightedKey("source-ok", 1_000_000),)
        )
    )
    candidates = (
        _canonical("ok"),
        _canonical("stale", projection_generation="old"),
        _canonical("wrong-scope", memory_scope_id="other"),
        _canonical("deleted", lifecycle_status="deleted"),
    )
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "dense",
                    _Provider(
                        tuple(
                            _hit(item.canonical_identity, rank=index)
                            for index, item in enumerate(candidates, 1)
                        )
                    ),
                ),
            ),
            _Hydrator(candidates),
        ).execute(request)
    )
    assert tuple(item.canonical_identity for item in response.candidates) == ("ok",)


def test_contributions_reconstruct_score_and_duplicate_projection_cannot_amplify() -> None:
    duplicate = _hit("a", provider="dense", query="q1", rank=8)
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "dense", _Provider((duplicate, duplicate, _hit("a", rank=2)))
                ),
            ),
            _Hydrator((_canonical("a"),)),
        ).execute(_request())
    )

    candidate = response.candidates[0]
    assert len(candidate.contributions) == 1
    assert candidate.contributions[0].provider_rank == 2
    assert candidate.fused_score == round(
        sum(item.contribution for item in candidate.contributions), 12
    )
    assert candidate.matched_query_ids == ("q1",)


def test_hard_filters_are_reapplied_after_canonical_hydration() -> None:
    request = _request(
        filters=LocatorHardFilters(
            source_generations=(LocatorSourceGeneration("source-ok", "generation-2"),),
            document_keys=("doc-ok",),
            kinds=("turn",),
            category="generic",
            tags_all=("accepted",),
            tags_none=("private",),
            actor_keys=("actor-ok",),
            time_interval=LocatorTimeInterval(_time(10), _time(20)),
        )
    )
    identities = (
        "ok",
        "wrong-source",
        "wrong-generation",
        "wrong-tag",
        "wrong-actor",
        "wrong-time",
    )
    candidates = (
        _canonical("ok"),
        _canonical("wrong-source", source_key="other"),
        _canonical("wrong-generation", projection_generation="old"),
        _canonical("wrong-tag", tags=("accepted", "private")),
        _canonical("wrong-actor", actor_keys=("someone-else",)),
        _canonical("wrong-time", start_at=_time(30), end_at=_time(31)),
    )
    provider = _Provider(
        tuple(_hit(identity, rank=index) for index, identity in enumerate(identities, 1))
    )

    response = asyncio.run(
        _retrieve((LocatorProviderRegistration("dense", provider),), _Hydrator(candidates)).execute(
            request
        )
    )

    assert tuple(item.canonical_identity for item in response.candidates) == ("ok",)


def test_pair_membership_is_exact_and_never_cartesian() -> None:
    request = _request(
        filters=LocatorHardFilters(
            (
                LocatorSourceGeneration("source-a", "generation-a"),
                LocatorSourceGeneration("source-b", "generation-b"),
            )
        )
    )
    candidates = (
        _canonical("a-ok", source_key="source-a", projection_generation="generation-a"),
        _canonical("b-ok", source_key="source-b", projection_generation="generation-b"),
        _canonical("a-stale", source_key="source-a", projection_generation="generation-b"),
        _canonical("b-stale", source_key="source-b", projection_generation="generation-a"),
    )
    provider = _Provider(
        tuple(_hit(item.canonical_identity, rank=index) for index, item in enumerate(candidates, 1))
    )
    response = asyncio.run(
        _retrieve((LocatorProviderRegistration("dense", provider),), _Hydrator(candidates)).execute(
            request
        )
    )
    assert len(provider.requests) == 1
    assert (
        provider.requests[0].hard_filters.source_generations
        == request.hard_filters.source_generations
    )
    assert {item.canonical_identity for item in response.candidates} == {"a-ok", "b-ok"}


def test_relative_hard_filter_rejects_missing_and_non_overlapping_candidates() -> None:
    request = _request(
        filters=LocatorHardFilters(
            (LocatorSourceGeneration("source-ok", "generation-2"),),
            relative_time_interval=LocatorRelativeTimeInterval(10, 20),
        )
    )
    candidates = (
        _canonical("overlap", relative_start_ms=20, relative_end_ms=25),
        _canonical("missing"),
        _canonical("outside", relative_start_ms=21, relative_end_ms=30),
    )
    provider = _Provider(
        tuple(_hit(item.canonical_identity, rank=index) for index, item in enumerate(candidates, 1))
    )
    response = asyncio.run(
        _retrieve((LocatorProviderRegistration("dense", provider),), _Hydrator(candidates)).execute(
            request
        )
    )
    assert tuple(item.canonical_identity for item in response.candidates) == ("overlap",)


def test_deleted_restricted_expired_and_wrong_scope_candidates_never_return() -> None:
    candidates = (
        _canonical("active"),
        _canonical("deleted", lifecycle_status="deleted"),
        _canonical("restricted", lifecycle_status="restricted"),
        _canonical("expired", lifecycle_status="expired"),
        _canonical("wrong-space", space_id="other"),
        _canonical("wrong-scope", memory_scope_id="other"),
    )
    provider = _Provider(
        tuple(_hit(item.canonical_identity, rank=index) for index, item in enumerate(candidates, 1))
    )

    response = asyncio.run(
        _retrieve((LocatorProviderRegistration("dense", provider),), _Hydrator(candidates)).execute(
            _request()
        )
    )

    assert tuple(item.canonical_identity for item in response.candidates) == ("active",)


def test_neighbors_attach_after_seed_ranking_and_require_same_source_exact_adjacency() -> None:
    seed_a = _canonical("seed-a", sequence_ordinal=10)
    seed_b = _canonical("seed-b", sequence_ordinal=20)
    provider = _Provider((_hit("seed-a", rank=1), _hit("seed-b", rank=2)))
    reader = _Hydrator(
        (seed_a, seed_b),
        neighbors=(
            _canonical("before-a", document_key="doc-other", sequence_ordinal=9),
            _canonical("after-a", sequence_ordinal=11),
            _canonical("gap-a", sequence_ordinal=12),
            _canonical("cross-source", source_key="other", sequence_ordinal=9),
        ),
    )
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", provider),),
            reader,
            supports_neighbors=True,
        ).execute(_request(bounds=LocatorRetrievalBounds(result_limit=2, neighbor_radius=1)))
    )

    assert tuple(item.canonical_identity for item in response.candidates) == ("seed-a", "seed-b")
    assert tuple(item.canonical_identity for item in response.candidates[0].neighbors) == (
        "before-a",
        "after-a",
    )
    assert all(
        item.relation == "neighbor" and abs(item.distance) == 1
        for item in response.candidates[0].neighbors
    )
    assert response.candidates[1].neighbors == ()


def test_cancellation_is_never_converted_to_degradation() -> None:
    class CancellingProvider:
        async def retrieve_locator_candidates(
            self, _request: LocatorRetrievalRequest
        ) -> LocatorProviderResult:
            await asyncio.sleep(0)
            raise asyncio.CancelledError()

    class BlockingProvider:
        cancelled = False

        async def retrieve_locator_candidates(
            self, _request: LocatorRetrievalRequest
        ) -> LocatorProviderResult:
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    blocker = BlockingProvider()
    use_case = _retrieve(
        (
            LocatorProviderRegistration("blocking", blocker),
            LocatorProviderRegistration("cancelling", CancellingProvider()),
        ),
        _Hydrator(()),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(use_case.execute(_request()))
    assert blocker.cancelled is True


def test_optional_provider_failure_is_bounded_and_explicitly_degraded() -> None:
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "canonical",
                    _Provider((_hit("a", provider="canonical"),)),
                    required=True,
                ),
                LocatorProviderRegistration(
                    "graph", _Provider(error=RuntimeError("secret detail"))
                ),
            ),
            _Hydrator((_canonical("a"),)),
        ).execute(_request())
    )

    assert response.status == "available"
    assert response.degradation_reason_codes == ("optional_provider_failed",)
    actual_outcomes = tuple(
        (outcome.provider_id, outcome.status, outcome.reason_code)
        for outcome in response.provider_outcomes
    )
    assert actual_outcomes == (
        ("canonical", "available", None),
        ("graph", "unavailable", "provider_error"),
    )


def test_response_byte_bound_fails_closed_without_partial_candidates() -> None:
    identities = tuple(f"item-{index}" for index in range(50))
    candidates = tuple(
        _canonical(identity, source_key="source-ok", document_key="y" * 256)
        for identity in identities
    )
    response = asyncio.run(
        _retrieve(
            (
                LocatorProviderRegistration(
                    "dense",
                    _Provider(
                        tuple(
                            _hit(identity, rank=index + 1)
                            for index, identity in enumerate(identities)
                        )
                    ),
                ),
            ),
            _Hydrator(candidates),
        ).execute(
            _request(
                bounds=LocatorRetrievalBounds(
                    candidate_limit=50, result_limit=50, response_byte_limit=16_384
                )
            )
        )
    )

    encoded = json.dumps(
        asdict(response), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert len(encoded) <= response.applied_bounds.response_byte_limit
    assert response.status == "unavailable"
    assert response.degradation_reason_codes == ("response_byte_limit_exceeded",)


def test_minimum_byte_limit_holds_maximal_mandatory_error_envelope() -> None:
    capability_fingerprint = FINGERPRINT
    profile_id = "🧩" * 256
    providers = tuple(
        LocatorProviderRegistration(
            "🔎" * 255 + str(index),
            _Provider(error=RuntimeError("hidden")),
            required=True,
        )
        for index in range(4)
    )
    request = LocatorRetrievalRequest(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION,
        capability_fingerprint,
        profile_id,
        LocatorRetrievalScope("space", "scope"),
        (_query("q1"),),
        LocatorHardFilters((LocatorSourceGeneration("source-ok", "generation-2"),)),
        LocatorSoftPreferences(),
        LocatorRetrievalBounds(response_byte_limit=16_384),
    )
    response = asyncio.run(
        RetrieveLocators(
            providers,
            _Hydrator(()),
            LocatorRetrievalCapability(capability_fingerprint, profile_id),
        ).execute(request)
    )
    encoded = json.dumps(
        asdict(response), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert response.status == "unavailable"
    assert len(encoded) <= response.applied_bounds.response_byte_limit


def test_mutable_requests_registrations_and_provider_results_are_defensively_copied() -> None:
    queries = [_query("q1")]
    request = _request(queries=queries)  # type: ignore[arg-type]
    queries.extend(_query(str(index)) for index in range(2, 9))
    assert request.queries == (_query("q1"),)

    hits = [_hit("a")]
    result = LocatorProviderResult(hits=hits)  # type: ignore[arg-type]
    hits.append(_hit("b"))
    assert tuple(item.canonical_identity for item in result.hits) == ("a",)

    registrations = [LocatorProviderRegistration("dense", _Provider(result.hits))]
    use_case = _retrieve(registrations, _Hydrator((_canonical("a"),)))  # type: ignore[arg-type]
    registrations.clear()
    assert asyncio.run(use_case.execute(request)).candidates[0].canonical_identity == "a"


def test_request_is_revalidated_at_use_case_entry() -> None:
    request = _request()
    object.__setattr__(request, "queries", [_query(str(index)) for index in range(7)])
    with pytest.raises(ValueError, match="1..6"):
        asyncio.run(
            _retrieve((LocatorProviderRegistration("dense", _Provider()),), _Hydrator(())).execute(
                request
            )
        )


@pytest.mark.parametrize(
    "case",
    ["mixed", "duplicate", "malformed"],
)
def test_malformed_duplicate_or_mixed_preliminary_hydration_fails_typed(
    case: str,
) -> None:
    rows: tuple[object, ...]
    if case == "mixed":
        rows = (_canonical("a"), _canonical("b", read_snapshot="snapshot-2"))
    elif case == "duplicate":
        rows = (_canonical("a"), _canonical("a"))
    else:
        rows = ("malformed",)
    reader = _Hydrator(rows)  # type: ignore[arg-type]
    provider = _Provider((_hit("a"), _hit("b", rank=2)))
    with pytest.raises(CanonicalHydrationInvariantError):
        asyncio.run(
            _retrieve((LocatorProviderRegistration("dense", provider),), reader).execute(_request())
        )


def test_final_read_mixed_snapshots_fails_typed() -> None:
    reader = _Hydrator(
        (_canonical("a"),),
        neighbors=(_canonical("neighbor", read_snapshot="snapshot-2"),),
    )
    with pytest.raises(CanonicalHydrationInvariantError, match="mixed read snapshots"):
        asyncio.run(
            _retrieve(
                (LocatorProviderRegistration("dense", _Provider((_hit("a"),))),),
                reader,
                supports_neighbors=True,
            ).execute(_request(bounds=LocatorRetrievalBounds(neighbor_radius=1)))
        )


def test_version_change_in_final_neighbor_read_drops_stale_seed() -> None:
    reader = _Hydrator(
        (_canonical("a", canonical_version=1),),
        neighbors=(_canonical("neighbor", sequence_ordinal=11),),
        final_candidates=(_canonical("a", canonical_version=2),),
    )
    response = asyncio.run(
        _retrieve(
            (LocatorProviderRegistration("dense", _Provider((_hit("a"),))),),
            reader,
            supports_neighbors=True,
        ).execute(_request(bounds=LocatorRetrievalBounds(neighbor_radius=1)))
    )
    assert response.status == "unqualified"
    assert response.candidates == ()


def test_unattested_neighbors_and_profile_mismatch_return_before_provider_calls() -> None:
    class CountingProvider(_Provider):
        calls = 0

        async def retrieve_locator_candidates(
            self, request: LocatorRetrievalRequest
        ) -> LocatorProviderResult:
            self.calls += 1
            return await super().retrieve_locator_candidates(request)

    provider = CountingProvider((_hit("a"),))
    use_case = _retrieve(
        (LocatorProviderRegistration("dense", provider),), _Hydrator((_canonical("a"),))
    )
    unsupported = asyncio.run(
        use_case.execute(_request(bounds=LocatorRetrievalBounds(neighbor_radius=1)))
    )
    assert unsupported.degradation_reason_codes == ("neighbor_capability_unavailable",)
    unsupported_size = len(
        json.dumps(
            asdict(unsupported),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    assert unsupported_size <= unsupported.applied_bounds.response_byte_limit
    mismatch = _request()
    object.__setattr__(mismatch, "profile_id", "wrong-profile")
    rejected = asyncio.run(use_case.execute(mismatch))
    assert rejected.degradation_reason_codes == ("capability_profile_mismatch",)
    assert provider.calls == 0


def test_full_capability_requires_exact_healthy_qualified_provider_membership() -> None:
    lanes = (
        LocatorProviderLaneCapability("postgres_keyword", True, True, 1_000_000, True),
        LocatorProviderLaneCapability("qdrant_dense", True, True, 1_000_000, True),
    )
    capability = LocatorRetrievalCapability(
        "b37d034c3879cab546b717d08187f58d9236752f5f569dc55df5410295494233",
        "locator-v2-pairs-relative-22222222",
        True,
        "a" * 40,
        "2" * 64,
        lanes,
        required_provider_lanes=("postgres_keyword", "qdrant_dense"),
    )
    providers = (
        LocatorProviderRegistration(
            "postgres_keyword",
            _Provider((_hit("a", provider="postgres_keyword"),)),
            required=True,
        ),
        LocatorProviderRegistration(
            "qdrant_dense",
            _Provider((_hit("a", provider="qdrant_dense"),)),
            required=True,
        ),
    )
    request = _request()
    object.__setattr__(request, "capability_fingerprint", capability.capability_fingerprint)
    object.__setattr__(request, "profile_id", capability.profile_id)

    accepted = asyncio.run(
        RetrieveLocators(providers, _Hydrator((_canonical("a"),)), capability).execute(request)
    )
    assert accepted.status == "available"

    unhealthy = LocatorRetrievalCapability(
        capability.capability_fingerprint,
        capability.profile_id,
        True,
        "a" * 40,
        "2" * 64,
        (
            lanes[0],
            LocatorProviderLaneCapability("qdrant_dense", True, False, 1_000_000, True),
        ),
        required_provider_lanes=("postgres_keyword", "qdrant_dense"),
    )
    rejected = asyncio.run(
        RetrieveLocators(providers, _Hydrator((_canonical("a"),)), unhealthy).execute(request)
    )
    assert rejected.status == "unavailable"
    assert rejected.degradation_reason_codes == ("capability_profile_mismatch",)


def _retrieve(
    providers: tuple[LocatorProviderRegistration, ...] | list[LocatorProviderRegistration],
    reader: _Hydrator,
    *,
    supports_neighbors: bool = False,
) -> RetrieveLocators:
    return RetrieveLocators(
        providers,  # type: ignore[arg-type]
        reader,
        LocatorRetrievalCapability(FINGERPRINT, "hybrid-general-v2", supports_neighbors),
    )


def _request(
    *,
    queries: tuple[LocatorQueryVariant, ...] | None = None,
    filters: LocatorHardFilters | None = None,
    preferences: LocatorSoftPreferences | None = None,
    bounds: LocatorRetrievalBounds | None = None,
) -> LocatorRetrievalRequest:
    return LocatorRetrievalRequest(
        contract_version=LOCATOR_RETRIEVAL_CONTRACT_VERSION,
        capability_fingerprint=FINGERPRINT,
        profile_id="hybrid-general-v2",
        scope=LocatorRetrievalScope("space", "scope"),
        queries=(_query("q1"),) if queries is None else queries,
        hard_filters=filters
        or LocatorHardFilters((LocatorSourceGeneration("source-ok", "generation-2"),)),
        soft_preferences=preferences or LocatorSoftPreferences(),
        bounds=bounds or LocatorRetrievalBounds(),
    )


def _query(query_id: str, *, weight: float | None = None) -> LocatorQueryVariant:
    weight_micros = 1_000_000 if weight is None else round(weight * 1_000_000)
    return LocatorQueryVariant(
        query_id=query_id,
        query=f"query {query_id}",
        weight_micros=weight_micros,
    )


def _hit(
    identity: str,
    *,
    provider: str = "dense",
    query: str = "q1",
    rank: int = 1,
    score_kind: str | None = "similarity",
) -> LocatorProviderHit:
    return LocatorProviderHit(
        canonical_identity=identity,
        canonical_version=1,
        provider_id=provider,
        query_id=query,
        provider_rank=rank,
        raw_score_kind=score_kind,
        raw_score_value=0.75 if score_kind is not None else None,
    )


def _canonical(
    identity: str,
    *,
    space_id: str = "space",
    memory_scope_id: str = "scope",
    source_key: str = "source-ok",
    document_key: str = "doc-ok",
    projection_generation: str = "generation-2",
    tags: tuple[str, ...] = ("accepted",),
    actor_keys: tuple[str, ...] = ("actor-ok",),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sequence_ordinal: int | None = 10,
    lifecycle_status: str = "active",
    read_snapshot: str = "snapshot-1",
    canonical_version: int = 1,
    relative_start_ms: int | None = None,
    relative_end_ms: int | None = None,
) -> CanonicalLocatorCandidate:
    return CanonicalLocatorCandidate(
        locator=f"opaque:{identity}",
        canonical_identity=identity,
        canonical_version=canonical_version,
        lifecycle_status=lifecycle_status,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        source_key=source_key,
        document_key=document_key,
        chunk_key=f"chunk:{identity}",
        projection_generation=projection_generation,
        kind="turn",
        category="generic",
        read_snapshot=read_snapshot,
        tags=tags,
        actor_keys=actor_keys,
        start_at=start_at or _time(12),
        end_at=end_at or _time(13),
        sequence_ordinal=sequence_ordinal,
        relative_start_ms=relative_start_ms,
        relative_end_ms=relative_end_ms,
    )


def _time(minute: int) -> datetime:
    return datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
