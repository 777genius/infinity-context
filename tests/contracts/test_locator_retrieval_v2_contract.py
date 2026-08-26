from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

import pytest
from infinity_context_contracts.features.context_building import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    RetrievalV2AppliedBoundsDto,
    RetrievalV2BoundsDto,
    RetrievalV2CandidateDto,
    RetrievalV2ContributionDto,
    RetrievalV2HardFiltersDto,
    RetrievalV2NeighborDto,
    RetrievalV2ProviderOutcomeDto,
    RetrievalV2QueryDto,
    RetrievalV2RelativeTimeIntervalDto,
    RetrievalV2ScopeDto,
    RetrievalV2SoftPreferencesDto,
    RetrievalV2SourceGenerationDto,
    RetrievalV2TimeIntervalDto,
    RetrievalV2WeightedKeyDto,
    RetrieveContextV2RequestDto,
    RetrieveContextV2ResponseDto,
    decode_retrieve_context_v2_request,
)

FINGERPRINT = "a" * 64

FORBIDDEN_RESPONSE_KEYS = {
    "alias",
    "aliases",
    "authorization",
    "citation",
    "citations",
    "content",
    "metadata",
    "quote",
    "rendered_context",
    "snippet",
    "text",
}


def test_raw_decoder_rejects_duplicate_keys_before_mapping_loss() -> None:
    with pytest.raises(ValueError, match="duplicate key: profile_id"):
        decode_retrieve_context_v2_request(b'{"profile_id":"first","profile_id":"second"}')


def test_wire_rejects_non_sha_fingerprints_and_invalid_unicode() -> None:
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        RetrieveContextV2ResponseDto(
            "unqualified",
            "A" * 64,
            "profile",
            RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 0, 0),
            (),
            (),
        )
    with pytest.raises(ValueError, match="invalid Unicode"):
        RetrievalV2QueryDto("q1", "\ud800")


@pytest.mark.parametrize("value", [-1, 1.5, True, 9_007_199_254_740_992])
def test_relative_milliseconds_reject_noncanonical_values(value: object) -> None:
    with pytest.raises(ValueError):
        RetrievalV2RelativeTimeIntervalDto(value, 10)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [99_999, 10_000_001, True, 1.0])
def test_soft_preference_weights_require_exact_integer_millionths(value: object) -> None:
    with pytest.raises(ValueError, match="weight_micros"):
        RetrievalV2WeightedKeyDto("source", value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="time_weight_micros"):
        RetrievalV2SoftPreferencesDto(
            time_interval=RetrievalV2TimeIntervalDto(
                "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
            ),
            time_weight_micros=value,  # type: ignore[arg-type]
        )


def test_source_generation_pairs_are_exact_sorted_and_non_cartesian() -> None:
    pairs = (
        RetrievalV2SourceGenerationDto("a", "ga"),
        RetrievalV2SourceGenerationDto("b", "gb"),
    )
    filters = RetrievalV2HardFiltersDto(pairs)
    assert {
        (item.source_key, item.projection_generation) for item in filters.source_generations
    } == {
        ("a", "ga"),
        ("b", "gb"),
    }
    with pytest.raises(ValueError, match="unique source keys"):
        RetrievalV2HardFiltersDto(
            (
                RetrievalV2SourceGenerationDto("a", "ga"),
                RetrievalV2SourceGenerationDto("a", "gb"),
            )
        )
    with pytest.raises(ValueError, match="sorted"):
        RetrievalV2HardFiltersDto(tuple(reversed(pairs)))


@pytest.mark.parametrize("version", [True, 9_007_199_254_740_992])
def test_wire_canonical_versions_reject_non_lossless_integers(version: object) -> None:
    with pytest.raises(ValueError):
        RetrievalV2NeighborDto(
            "locator", "source", "document", "chunk", "identity", version, "active"
        )  # type: ignore[arg-type]


def test_locator_only_response_has_no_text_like_key_at_any_depth() -> None:
    contribution = RetrievalV2ContributionDto(
        provider_id="dense",
        query_id="q1",
        provider_rank=2,
        provider_weight_micros=1_000_000,
        query_weight_micros=1_000_000,
        contribution_score_picos=16_129_032_258,
        provider_weight=1.0,
        query_weight=1.0,
        contribution=0.016129032258,
        raw_score_kind="similarity",
        raw_score_value=0.9,
    )
    neighbor = RetrievalV2NeighborDto(
        locator="opaque:neighbor",
        source_key="source-1",
        document_key="document-1",
        chunk_key="chunk-2",
        canonical_identity="canonical-2",
        canonical_version=3,
        lifecycle_status="active",
        relation="neighbor",
        distance=1,
    )
    candidate = RetrievalV2CandidateDto(
        locator="opaque:seed",
        source_key="source-1",
        document_key="document-1",
        chunk_key="chunk-1",
        canonical_identity="canonical-1",
        canonical_version=4,
        lifecycle_status="active",
        provider_rank=2,
        fused_score=0.016129032258,
        matched_query_ids=("q1",),
        contributions=(contribution,),
        base_score_picos=contribution.contribution_score_picos,
        neighbors=(neighbor,),
    )
    response = RetrieveContextV2ResponseDto(
        status="available",
        capability_fingerprint=FINGERPRINT,
        profile_id="hybrid-general-v2",
        applied_bounds=RetrievalV2AppliedBoundsDto(
            candidate_limit=50,
            result_limit=20,
            neighbor_radius=1,
            response_byte_limit=500_000,
            deadline_ms=2_000,
            returned_seeds=1,
            returned_neighbors=1,
        ),
        candidates=(candidate,),
        provider_outcomes=(RetrievalV2ProviderOutcomeDto("dense", "available"),),
    )

    payload = response.to_dict()
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload
    assert payload["contract_version"] == LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2
    _assert_no_forbidden_keys(payload)


@pytest.mark.parametrize(
    "payload,path",
    [
        ({"metadata": {}}, "metadata"),
        ({"filters": {"free_form": "x"}}, "filters.free_form"),
        ({"soft_preferences": {"speaker_aliases": ["Ada"]}}, "soft_preferences.speaker_aliases"),
        ({"bounds": {"neighbor_radius": 3}}, "bounds.neighbor_radius"),
        ({"queries": [{"query_id": "q1", "query": "x", "boost": 2}]}, "queries.0.boost"),
    ],
)
def test_request_parser_rejects_unknown_or_out_of_bounds_fields(
    payload: dict[str, object], path: str
) -> None:
    base: dict[str, object] = {
        "contract_version": LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        "capability_fingerprint": FINGERPRINT,
        "profile_id": "hybrid-general-v2",
        "scope": {"space_id": "space", "memory_scope_id": "scope", "thread_id": None},
        "queries": [{"query_id": "q1", "query": "find this", "weight_micros": 1_000_000}],
        "filters": {
            "source_generations": [
                {"source_key": "source", "projection_generation": "generation-2"}
            ],
            "excluded_source_keys": [],
            "document_keys": [],
            "kinds": [],
            "category": None,
            "tags_any": [],
            "tags_all": [],
            "tags_none": [],
            "actor_keys": [],
            "time_interval": None,
            "relative_time_interval": None,
        },
        "soft_preferences": {
            "source_preferences": [],
            "actor_preferences": [],
            "time_interval": None,
            "relative_time_interval": None,
            "time_weight_micros": None,
        },
        "bounds": {
            "candidate_limit": 150,
            "result_limit": 20,
            "neighbor_radius": 0,
            "response_byte_limit": 1_048_576,
            "deadline_ms": 2_000,
        },
    }
    for key, value in payload.items():
        if key in {"filters", "soft_preferences", "bounds"} and isinstance(value, dict):
            base[key].update(value)  # type: ignore[union-attr]
        elif key == "queries":
            base[key] = value
        else:
            base[key] = value

    with pytest.raises(ValueError, match=path.replace(".", r"\.")):
        RetrieveContextV2RequestDto.from_dict(base)


def test_ranked_neighbors_are_non_recursive_and_response_semantics_fail_closed() -> None:
    contribution = _contribution(0.016393442623)
    with pytest.raises(ValueError, match="candidate.neighbors"):
        RetrievalV2CandidateDto(
            "opaque:seed",
            "source",
            "document",
            "chunk",
            "canonical",
            1,
            "active",
            provider_rank=1,
            fused_score=contribution.contribution,
            matched_query_ids=("q1",),
            contributions=(contribution,),
            base_score_picos=contribution.contribution_score_picos,
            neighbors=(
                RetrievalV2CandidateDto(
                    "opaque:nested-direct",
                    "source",
                    "document",
                    "nested-chunk",
                    "nested",
                    1,
                    "active",
                    provider_rank=1,
                    fused_score=contribution.contribution,
                    matched_query_ids=("q1",),
                    contributions=(contribution,),
                    base_score_picos=contribution.contribution_score_picos,
                ),
            ),
        )

    bounds = RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 0, 0)
    with pytest.raises(ValueError, match="ranking_policy"):
        RetrieveContextV2ResponseDto(
            "unqualified",
            FINGERPRINT,
            "profile",
            bounds,
            (),
            (),
            ranking_policy="arbitrary",
        )
    with pytest.raises(ValueError, match="degradation reason"):
        RetrieveContextV2ResponseDto(
            "unqualified",
            FINGERPRINT,
            "profile",
            bounds,
            (),
            (),
            ("free-form",),
        )


def test_contract_collections_are_immutable_and_nested_types_are_checked() -> None:
    with pytest.raises(ValueError, match="response_byte_limit"):
        RetrievalV2BoundsDto(response_byte_limit=16_383)
    source_generations = [RetrievalV2SourceGenerationDto("source", "generation-2")]
    filters = RetrievalV2HardFiltersDto(source_generations=source_generations)
    source_generations.append(RetrievalV2SourceGenerationDto("late", "generation-2"))
    assert filters.source_generations == (RetrievalV2SourceGenerationDto("source", "generation-2"),)

    queries = [RetrievalV2QueryDto("q1", "query")]
    request = RetrieveContextV2RequestDto(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        FINGERPRINT,
        "profile",
        RetrievalV2ScopeDto("space", "scope"),
        queries,
        RetrievalV2HardFiltersDto((RetrievalV2SourceGenerationDto("source", "generation-2"),)),
    )
    queries.append(RetrievalV2QueryDto("q2", "other"))
    assert tuple(item.query_id for item in request.queries) == ("q1",)
    with pytest.raises(ValueError, match="time_interval"):
        RetrievalV2HardFiltersDto(
            (RetrievalV2SourceGenerationDto("source", "generation-2"),),
            time_interval={"text": "leak"},  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="integer"):
        RetrievalV2AppliedBoundsDto(True, 1, 0, 16_384, 1, 0, 0)  # type: ignore[arg-type]

    neighbor = RetrievalV2NeighborDto(
        "opaque:neighbor", "source", "document", "chunk", "neighbor", 1, "active"
    )
    object.__setattr__(neighbor, "relation", "direct")
    contribution = _contribution(0.016393442623)
    with pytest.raises(ValueError, match="relation=neighbor"):
        RetrievalV2CandidateDto(
            "opaque:seed",
            "source",
            "document",
            "seed-chunk",
            "seed",
            1,
            "active",
            provider_rank=1,
            fused_score=contribution.contribution,
            matched_query_ids=("q1",),
            contributions=(contribution,),
            base_score_picos=contribution.contribution_score_picos,
            neighbors=(neighbor,),
        )


def _contribution(score: float) -> RetrievalV2ContributionDto:
    score_picos = round(score * 1_000_000_000_000)
    return RetrievalV2ContributionDto(
        "dense",
        "q1",
        1,
        1_000_000,
        1_000_000,
        score_picos,
        1.0,
        1.0,
        score_picos / 1_000_000_000_000,
    )


def _direct_candidate(
    *,
    identity: str = "candidate",
    provider_rank: int = 1,
    contribution: float = 0.016393442623,
    fused_score: float | None = None,
    matched_query_ids: tuple[str, ...] = ("q1",),
    contributions: tuple[RetrievalV2ContributionDto, ...] | None = None,
) -> RetrievalV2CandidateDto:
    if contributions is None:
        contributions = (_contribution(contribution),)
    if fused_score is None:
        fused_score = contribution
    return RetrievalV2CandidateDto(
        locator=f"opaque:{identity}",
        source_key="source",
        document_key="document",
        chunk_key=f"chunk:{identity}",
        canonical_identity=identity,
        canonical_version=1,
        lifecycle_status="active",
        provider_rank=provider_rank,
        fused_score=fused_score,
        matched_query_ids=matched_query_ids,
        contributions=contributions,
        base_score_picos=sum(item.contribution_score_picos for item in contributions),
    )


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            lambda: _direct_candidate(fused_score=0.0, matched_query_ids=(), contributions=()),
            "positive finite fused_score",
        ),
        (
            lambda: _direct_candidate(fused_score=0.1, contributions=()),
            "requires contributions",
        ),
        (
            lambda: _direct_candidate(matched_query_ids=()),
            "requires matched_query_ids",
        ),
        (
            lambda: _direct_candidate(provider_rank=2),
            "contribution minimum",
        ),
        (
            lambda: _direct_candidate(fused_score=0.5),
            "must mirror",
        ),
        (
            lambda: _direct_candidate(fused_score=float("inf")),
            "finite",
        ),
    ],
)
def test_direct_candidates_reject_missing_or_invalid_ranking_provenance(
    candidate: Callable[[], RetrievalV2CandidateDto], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        candidate()


@pytest.mark.parametrize(
    "candidates",
    [
        (
            _direct_candidate(identity="a", contribution=0.01),
            _direct_candidate(identity="b", contribution=0.02),
        ),
        (_direct_candidate(identity="b"), _direct_candidate(identity="a")),
    ],
)
def test_available_response_rejects_any_noncanonical_candidate_order(
    candidates: tuple[RetrievalV2CandidateDto, ...],
) -> None:
    with pytest.raises(ValueError, match="rerank_score_picos"):
        RetrieveContextV2ResponseDto(
            status="available",
            capability_fingerprint=FINGERPRINT,
            profile_id="profile",
            applied_bounds=RetrievalV2AppliedBoundsDto(2, 2, 0, 16_384, 1, 2, 0),
            candidates=candidates,
            provider_outcomes=(),
        )


def test_equal_final_score_uses_unsigned_utf8_canonical_identity_tie() -> None:
    ordered = (
        _direct_candidate(identity="\ue000"),
        _direct_candidate(identity="𐀀"),
    )
    response = RetrieveContextV2ResponseDto(
        status="available",
        capability_fingerprint=FINGERPRINT,
        profile_id="profile",
        applied_bounds=RetrievalV2AppliedBoundsDto(2, 2, 0, 16_384, 1, 2, 0),
        candidates=ordered,
        provider_outcomes=(),
    )
    assert tuple(item.canonical_identity for item in response.candidates) == ("\ue000", "𐀀")
    with pytest.raises(ValueError, match="canonical_identity"):
        RetrieveContextV2ResponseDto(
            status="available",
            capability_fingerprint=FINGERPRINT,
            profile_id="profile",
            applied_bounds=RetrievalV2AppliedBoundsDto(2, 2, 0, 16_384, 1, 2, 0),
            candidates=tuple(reversed(ordered)),
            provider_outcomes=(),
        )


def test_non_available_empty_response_remains_valid() -> None:
    response = RetrieveContextV2ResponseDto(
        status="unavailable",
        capability_fingerprint=FINGERPRINT,
        profile_id="profile",
        applied_bounds=RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 0, 0),
        candidates=(),
        provider_outcomes=(
            RetrievalV2ProviderOutcomeDto("dense", "unavailable", "provider_unavailable"),
        ),
    )

    assert response.to_dict()["candidates"] == []


def test_response_preference_evidence_must_reconstruct_and_unknown_fields_reject() -> None:
    candidate = _direct_candidate()
    with pytest.raises(ValueError, match="preference_boost_micros"):
        RetrievalV2CandidateDto(
            locator=candidate.locator,
            source_key=candidate.source_key,
            document_key=candidate.document_key,
            chunk_key=candidate.chunk_key,
            canonical_identity=candidate.canonical_identity,
            canonical_version=candidate.canonical_version,
            lifecycle_status=candidate.lifecycle_status,
            provider_rank=candidate.provider_rank,
            fused_score=candidate.fused_score,
            matched_query_ids=candidate.matched_query_ids,
            contributions=candidate.contributions,
            base_score_picos=candidate.base_score_picos,
            preference_score_micros=1_000_000,
            preference_boost_micros=249_999,
            source_requested_weight_micros=1_000_000,
            source_matched_weight_micros=1_000_000,
        )
    payload = RetrieveContextV2ResponseDto(
        status="available",
        capability_fingerprint=FINGERPRINT,
        profile_id="profile",
        applied_bounds=RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 1, 0),
        candidates=(candidate,),
        provider_outcomes=(),
    ).to_dict()
    payload["candidates"][0]["preference_detail"] = {}  # type: ignore[index]
    with pytest.raises(ValueError, match="canonical contract"):
        RetrieveContextV2ResponseDto.from_dict(payload)


def test_response_preference_evidence_rejects_cross_dimension_weight_swap() -> None:
    with pytest.raises(ValueError, match="dimension evidence"):
        replace(
            _direct_candidate(),
            preference_score_micros=500_000,
            preference_boost_micros=125_000,
            rerank_score_picos=None,
            source_requested_weight_micros=0,
            source_matched_weight_micros=1_000_000,
            actor_requested_weight_micros=2_000_000,
            actor_matched_weight_micros=0,
        )


def test_request_reconstructs_exact_base_copies_of_every_nested_dto() -> None:
    class LeakyScope(RetrievalV2ScopeDto):
        def to_dict(self) -> dict[str, object]:
            return {"space_id": self.space_id, "text": "leak"}

    class LeakyQuery(RetrievalV2QueryDto):
        pass

    class LeakyInterval(RetrievalV2TimeIntervalDto):
        pass

    class LeakyWeightedKey(RetrievalV2WeightedKeyDto):
        pass

    class LeakyFilters(RetrievalV2HardFiltersDto):
        pass

    class LeakyPreferences(RetrievalV2SoftPreferencesDto):
        pass

    class LeakyBounds(RetrievalV2BoundsDto):
        pass

    scope = LeakyScope("space", "scope")
    query = LeakyQuery("q1", "query")
    queries = [query]
    filter_pairs = [RetrievalV2SourceGenerationDto("source", "generation-2")]
    filter_interval = LeakyInterval("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    filters = LeakyFilters(
        source_generations=filter_pairs,
        time_interval=filter_interval,
    )
    object.__setattr__(filters, "source_generations", filter_pairs)
    preference = LeakyWeightedKey("preferred", 2_000_000)
    preference_interval = LeakyInterval("2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z")
    preferences = LeakyPreferences(
        source_preferences=(preference,),
        time_interval=preference_interval,
        time_weight_micros=1_500_000,
    )
    object.__setattr__(preferences, "source_preferences", [preference])
    bounds = LeakyBounds(candidate_limit=10, result_limit=5)
    request = RetrieveContextV2RequestDto(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        FINGERPRINT,
        "profile",
        scope,
        queries,
        filters,
        preferences,
        bounds,
    )

    filter_pairs.append(RetrievalV2SourceGenerationDto("z-late", "generation-2"))
    queries.append(RetrievalV2QueryDto("q2", "other"))
    object.__setattr__(scope, "space_id", False)
    object.__setattr__(query, "query", "changed")
    object.__setattr__(filter_interval, "start_at", "changed")
    object.__setattr__(preference, "key", "changed")
    object.__setattr__(preference_interval, "start_at", "changed")
    object.__setattr__(bounds, "candidate_limit", True)

    assert type(request.scope) is RetrievalV2ScopeDto
    assert type(request.queries[0]) is RetrievalV2QueryDto
    assert type(request.filters) is RetrievalV2HardFiltersDto
    assert type(request.filters.source_generations) is tuple
    assert type(request.filters.time_interval) is RetrievalV2TimeIntervalDto
    assert type(request.soft_preferences) is RetrievalV2SoftPreferencesDto
    assert type(request.soft_preferences.source_preferences) is tuple
    assert type(request.soft_preferences.source_preferences[0]) is RetrievalV2WeightedKeyDto
    assert type(request.soft_preferences.time_interval) is RetrievalV2TimeIntervalDto
    assert type(request.bounds) is RetrievalV2BoundsDto
    payload = request.to_dict()
    assert payload["scope"] == {
        "space_id": "space",
        "memory_scope_id": "scope",
        "thread_id": None,
    }
    assert payload["queries"] == [{"query_id": "q1", "query": "query", "weight_micros": 1_000_000}]
    assert payload["filters"]["source_generations"] == [  # type: ignore[index]
        {"source_key": "source", "projection_generation": "generation-2"}
    ]
    assert payload["soft_preferences"]["source_preferences"] == [  # type: ignore[index]
        {"key": "preferred", "weight_micros": 2_000_000}
    ]
    assert payload["bounds"]["candidate_limit"] == 10  # type: ignore[index]
    _assert_no_forbidden_keys(payload)


@pytest.mark.parametrize("nested_name", ["scope", "bounds"])
def test_request_revalidates_nested_bool_substitution(nested_name: str) -> None:
    scope = RetrievalV2ScopeDto("space", "scope")
    bounds = RetrievalV2BoundsDto()
    if nested_name == "scope":
        object.__setattr__(scope, "space_id", False)
        message = "scope.space_id"
    else:
        object.__setattr__(bounds, "candidate_limit", True)
        message = "bounds.candidate_limit"

    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        RetrieveContextV2RequestDto(
            LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
            FINGERPRINT,
            "profile",
            scope,
            (RetrievalV2QueryDto("q1", "query"),),
            RetrievalV2HardFiltersDto((RetrievalV2SourceGenerationDto("source", "generation-2"),)),
            bounds=bounds,
        )


def test_existing_prompt_context_contract_is_unchanged() -> None:
    from infinity_context_contracts.features.context_building import (  # noqa: PLC0415
        BuildContextRequestDto,
        BuildContextResultDto,
    )

    assert BuildContextRequestDto(query="old", space_id="space").to_dict()["query"] == "old"
    assert BuildContextResultDto(items=()).to_dict() == {
        "data": {
            "items": [],
            "rendered_context": None,
            "budget": None,
            "total_tokens": None,
            "degraded": False,
            "diagnostics": {},
            "built_at": None,
        }
    }


def _assert_no_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_RESPONSE_KEYS)
        for nested in value.values():
            _assert_no_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_forbidden_keys(nested)
