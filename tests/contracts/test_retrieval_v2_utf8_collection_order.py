from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from infinity_context_contracts.features.context_building import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    RetrievalV2AppliedBoundsDto,
    RetrievalV2CandidateDto,
    RetrievalV2CapabilityDto,
    RetrievalV2ContributionDto,
    RetrievalV2HardFiltersDto,
    RetrievalV2ProviderOutcomeDto,
    RetrievalV2QueryDto,
    RetrievalV2ScopeDto,
    RetrievalV2SoftPreferencesDto,
    RetrievalV2SourceGenerationDto,
    RetrievalV2WeightedKeyDto,
    RetrieveContextV2RequestDto,
    RetrieveContextV2ResponseDto,
    capability_fingerprint_v2,
    decode_context_retrieval_v2_json,
    decode_retrieval_v2_capability,
    decode_retrieve_context_v2_request,
    decode_retrieve_context_v2_response,
)
from infinity_context_contracts.features.document_ingestion import (
    DocumentRetrievalProjectionV1Dto,
    decode_document_retrieval_projection_v1,
)
from infinity_context_core.features.context_building import public as core
from infinity_context_core.features.document_ingestion import public as ingestion

FINGERPRINT = "a" * 64
CANONICAL_PROBES = (
    pytest.param(("\ue000", "\U00010000"), id="bmp-before-supplementary"),
    pytest.param(("e\u0301", "é"), id="combining-before-precomposed"),
)
HARD_FILTER_FIELDS = (
    "excluded_source_keys",
    "document_keys",
    "kinds",
    "tags_any",
    "tags_all",
    "tags_none",
    "actor_keys",
)
PREFERENCE_FIELDS = ("source_preferences", "actor_preferences")
FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "fixtures"
    / "context_retrieval_v2"
)


def test_raw_json_recursively_decodes_surrogate_pairs_as_unicode_scalars() -> None:
    decoded = decode_context_retrieval_v2_json(
        b'{"\\ud83d\\ude00":{"nested":["\\ud83d\\ude00",{"value":"e\\u0301"}]}}'
    )
    assert decoded == {"😀": {"nested": ["😀", {"value": "e\u0301"}]}}


@pytest.mark.parametrize(
    "raw",
    (
        b'{"\\ud800":1}',
        b'{"\\udc00":1}',
        b'{"value":"\\ud800"}',
        b'{"value":"\\udc00"}',
        b'{"value":"\\ud800x"}',
        b'{"value":"\\udc00\\ud800"}',
        b'{"nested":[{"value":"\\ud800"}]}',
    ),
)
def test_raw_json_rejects_unpaired_or_reversed_surrogates_with_value_error(
    raw: bytes,
) -> None:
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        decode_context_retrieval_v2_json(raw)


def test_scalar_decoding_precedes_duplicate_key_detection() -> None:
    raw = b'{"\\ud83d\\ude00":1,"' + "😀".encode() + b'":2}'
    with pytest.raises(ValueError, match="duplicate key: 😀"):
        decode_context_retrieval_v2_json(raw)


def test_raw_json_preserves_normalization_distinct_keys_and_values() -> None:
    decoded = decode_context_retrieval_v2_json(
        json.dumps({"e\u0301": ["e\u0301"], "é": ["é"]}, ensure_ascii=False).encode("utf-8")
    )
    assert decoded == {"e\u0301": ["e\u0301"], "é": ["é"]}
    assert len(decoded) == 2


def test_valid_supplementary_root_string_reaches_object_shape_guard() -> None:
    with pytest.raises(ValueError, match="must contain one object"):
        decode_context_retrieval_v2_json(b'"\\ud83d\\ude00"')
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        decode_context_retrieval_v2_json(b'"\\ud800"')


@pytest.mark.parametrize(
    "decoder",
    (
        decode_retrieve_context_v2_request,
        decode_retrieval_v2_capability,
        decode_document_retrieval_projection_v1,
        decode_retrieve_context_v2_response,
    ),
)
def test_public_contract_decoders_never_leak_unicode_encode_error(decoder) -> None:
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        decoder(b'{"\\ud800":1}')


def test_capability_fingerprint_scalar_decoding_and_duplicate_detection() -> None:
    escaped_form = {"key": "\ud83d\ude00"}
    scalar_form = {"key": "😀"}
    assert capability_fingerprint_v2(escaped_form) == capability_fingerprint_v2(scalar_form)
    with pytest.raises(ValueError, match="duplicate key: 😀"):
        capability_fingerprint_v2({"\ud83d\ude00": 1, "😀": 2})
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        capability_fingerprint_v2({"nested": ["\ud800"]})


def test_escaped_and_raw_supplementary_scalars_match_node_json_parse() -> None:
    escaped = b'{"key":"\\ud83d\\ude00"}'
    raw = json.dumps({"key": "😀"}, ensure_ascii=False).encode("utf-8")
    script = """
const fs = require('fs');
const value = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(Buffer.from(value.key, 'utf8').toString('hex'));
"""
    python_values = [decode_context_retrieval_v2_json(item)["key"] for item in (escaped, raw)]
    node_values = [
        subprocess.run(
            ["node", "-e", script], input=item, check=True, capture_output=True
        ).stdout.decode("ascii")
        for item in (escaped, raw)
    ]
    assert python_values == ["😀", "😀"]
    assert node_values == ["f09f9880", "f09f9880"]


@pytest.mark.parametrize("values", CANONICAL_PROBES)
@pytest.mark.parametrize("field", HARD_FILTER_FIELDS)
def test_every_dto_hard_filter_array_requires_utf8_canonical_input(
    field: str, values: tuple[str, str]
) -> None:
    accepted = _dto_filters(**{field: values})
    assert getattr(accepted, field) == values
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        _dto_filters(**{field: tuple(reversed(values))})
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        _dto_filters(**{field: (values[0], values[0])})


@pytest.mark.parametrize("values", CANONICAL_PROBES)
@pytest.mark.parametrize("field", HARD_FILTER_FIELDS)
def test_every_core_hard_filter_array_requires_utf8_canonical_input(
    field: str, values: tuple[str, str]
) -> None:
    accepted = _core_filters(**{field: values})
    assert getattr(accepted, field) == values
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        _core_filters(**{field: tuple(reversed(values))})
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        _core_filters(**{field: (values[0], values[0])})


@pytest.mark.parametrize("values", CANONICAL_PROBES)
@pytest.mark.parametrize("field", PREFERENCE_FIELDS)
def test_every_dto_preference_key_array_requires_utf8_canonical_input(
    field: str, values: tuple[str, str]
) -> None:
    weighted = tuple(RetrievalV2WeightedKeyDto(value) for value in values)
    accepted = RetrievalV2SoftPreferencesDto(**{field: weighted})
    assert tuple(item.key for item in getattr(accepted, field)) == values
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        RetrievalV2SoftPreferencesDto(**{field: tuple(reversed(weighted))})
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        RetrievalV2SoftPreferencesDto(**{field: (weighted[0], weighted[0])})


@pytest.mark.parametrize("values", CANONICAL_PROBES)
@pytest.mark.parametrize("field", PREFERENCE_FIELDS)
def test_every_core_preference_key_array_requires_utf8_canonical_input(
    field: str, values: tuple[str, str]
) -> None:
    weighted = tuple(core.LocatorWeightedKeyV2(value) for value in values)
    accepted = core.LocatorSoftPreferencesV2(**{field: weighted})
    assert tuple(item.key for item in getattr(accepted, field)) == values
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        core.LocatorSoftPreferencesV2(**{field: tuple(reversed(weighted))})
    with pytest.raises(ValueError, match="UTF-8 sorted unique"):
        core.LocatorSoftPreferencesV2(**{field: (weighted[0], weighted[0])})


@pytest.mark.parametrize("values", CANONICAL_PROBES)
def test_dto_and_core_source_generation_pair_keys_use_utf8_order(values: tuple[str, str]) -> None:
    dto_pairs = tuple(RetrievalV2SourceGenerationDto(value, f"g-{value}") for value in values)
    core_pairs = tuple(core.LocatorSourceGenerationV2(value, f"g-{value}") for value in values)
    assert RetrievalV2HardFiltersDto(dto_pairs).source_generations == dto_pairs
    assert core.LocatorHardFiltersV2(core_pairs).source_generations == core_pairs
    with pytest.raises(ValueError, match="sorted"):
        RetrievalV2HardFiltersDto(tuple(reversed(dto_pairs)))
    with pytest.raises(ValueError, match="sorted"):
        core.LocatorHardFiltersV2(tuple(reversed(core_pairs)))

    dto_same_source = tuple(RetrievalV2SourceGenerationDto("source", value) for value in values)
    core_same_source = tuple(core.LocatorSourceGenerationV2("source", value) for value in values)
    with pytest.raises(ValueError, match="sorted"):
        RetrievalV2HardFiltersDto(tuple(reversed(dto_same_source)))
    with pytest.raises(ValueError, match="sorted"):
        core.LocatorHardFiltersV2(tuple(reversed(core_same_source)))
    with pytest.raises(ValueError, match="unique source keys"):
        RetrievalV2HardFiltersDto((dto_same_source[0], dto_same_source[0]))
    with pytest.raises(ValueError, match="unique source keys"):
        core.LocatorHardFiltersV2((core_same_source[0], core_same_source[0]))


@pytest.mark.parametrize("values", CANONICAL_PROBES)
def test_request_query_ids_are_utf8_sorted_distinct_and_not_normalized(
    values: tuple[str, str],
) -> None:
    dto_queries = tuple(RetrievalV2QueryDto(value, f"query {value}") for value in values)
    core_queries = tuple(core.LocatorQueryVariantV2(value, f"query {value}") for value in values)
    assert tuple(item.query_id for item in _dto_request(dto_queries).queries) == values
    assert tuple(item.query_id for item in _core_request(core_queries).queries) == values
    for queries, build in (
        (tuple(reversed(dto_queries)), _dto_request),
        ((dto_queries[0], dto_queries[0]), _dto_request),
        (tuple(reversed(core_queries)), _core_request),
        ((core_queries[0], core_queries[0]), _core_request),
    ):
        with pytest.raises(ValueError, match="UTF-8 sorted and unique"):
            build(queries)  # type: ignore[arg-type]


@pytest.mark.parametrize("values", CANONICAL_PROBES)
@pytest.mark.parametrize("field", ("actor_keys", "tags"))
def test_projection_dto_core_and_hydration_collections_preserve_distinct_unicode(
    field: str, values: tuple[str, str]
) -> None:
    dto = _dto_projection(**{field: values})
    domain = _core_projection(**{field: values})
    hydrated = _canonical_candidate(**{field: values})
    assert getattr(dto, field) == values
    assert getattr(domain, field) == values
    assert getattr(hydrated, field) == values
    for candidate in (tuple(reversed(values)), (values[0], values[0])):
        with pytest.raises(ValueError, match="sorted"):
            _dto_projection(**{field: candidate})
        with pytest.raises(Exception, match="sorted"):
            _core_projection(**{field: candidate})
        with pytest.raises(ValueError, match="sorted"):
            _canonical_candidate(**{field: candidate})


def test_response_keyed_collections_fail_closed_without_changing_rank_order() -> None:
    first = _dto_contribution("\ue000", "e\u0301", 0.01)
    second = _dto_contribution("\U00010000", "é", 0.02)
    candidate = _dto_candidate((first, second), ("e\u0301", "é"))
    assert tuple(item.provider_id for item in candidate.contributions) == (
        "\ue000",
        "\U00010000",
    )
    for contributions in ((second, first), (first, first)):
        with pytest.raises(ValueError, match="contributions must be"):
            _dto_candidate(
                contributions, tuple(sorted({item.query_id for item in contributions}, key=_key))
            )
    for matched in (("é", "e\u0301"), ("e\u0301", "e\u0301")):
        with pytest.raises(ValueError, match="matched_query_ids must be sorted and unique"):
            _dto_candidate((first, second), matched)

    outcomes = (
        RetrievalV2ProviderOutcomeDto("\ue000", "unavailable", "provider_unavailable"),
        RetrievalV2ProviderOutcomeDto("\U00010000", "unavailable", "provider_unavailable"),
    )
    response = _dto_empty_response(outcomes=outcomes)
    assert tuple(item.provider_id for item in response.provider_outcomes) == (
        "\ue000",
        "\U00010000",
    )
    for invalid in (tuple(reversed(outcomes)), (outcomes[0], outcomes[0])):
        with pytest.raises(ValueError, match="provider outcomes must be sorted and unique"):
            _dto_empty_response(outcomes=invalid)
    for invalid_reasons in (
        ("response_byte_limit_exceeded", "optional_provider_failed"),
        ("optional_provider_failed", "optional_provider_failed"),
    ):
        with pytest.raises(ValueError, match="reason codes must be sorted and unique"):
            _dto_empty_response(reasons=invalid_reasons)


def test_core_response_keyed_collections_match_dto_guards() -> None:
    first = _core_contribution("\ue000", "e\u0301", 0.01)
    second = _core_contribution("\U00010000", "é", 0.02)
    candidate = _core_result_candidate((first, second), ("e\u0301", "é"))
    assert tuple(item.provider_id for item in candidate.contributions) == (
        "\ue000",
        "\U00010000",
    )
    for contributions in ((second, first), (first, first)):
        with pytest.raises(ValueError, match="contributions must be"):
            _core_result_candidate(
                contributions,
                tuple(sorted({item.query_id for item in contributions}, key=_key)),
            )
    for matched in (("é", "e\u0301"), ("e\u0301", "e\u0301")):
        with pytest.raises(ValueError, match="matched_query_ids must be sorted and unique"):
            _core_result_candidate((first, second), matched)

    outcomes = (
        core.LocatorProviderOutcomeV2("\ue000", "unavailable", "provider_unavailable"),
        core.LocatorProviderOutcomeV2("\U00010000", "unavailable", "provider_unavailable"),
    )
    assert _core_empty_response(outcomes=outcomes).provider_outcomes == outcomes
    for invalid in (tuple(reversed(outcomes)), (outcomes[0], outcomes[0])):
        with pytest.raises(ValueError, match="provider outcomes must be sorted and unique"):
            _core_empty_response(outcomes=invalid)
    for invalid_reasons in (
        ("response_byte_limit_exceeded", "optional_provider_failed"),
        ("optional_provider_failed", "optional_provider_failed"),
    ):
        with pytest.raises(ValueError, match="reason codes must be sorted and unique"):
            _core_empty_response(reasons=invalid_reasons)


@pytest.mark.parametrize("values", CANONICAL_PROBES)
def test_capability_provider_ids_are_utf8_sorted_in_dto_and_core(values: tuple[str, str]) -> None:
    payload = json.loads((FIXTURES / "capability.json").read_text(encoding="utf-8"))
    for lane, provider_id in zip(payload["provider_lanes"], values, strict=True):
        lane["provider_id"] = provider_id
    payload["required_provider_lanes"] = list(values)
    payload["capability_fingerprint"] = capability_fingerprint_v2(payload)
    assert (
        tuple(
            lane.provider_id for lane in RetrievalV2CapabilityDto.from_dict(payload).provider_lanes
        )
        == values
    )

    lanes = tuple(
        core.LocatorProviderLaneCapabilityV2(value, True, True, 1_000_000, True) for value in values
    )
    capability = core.LocatorRetrievalCapabilityV2(
        FINGERPRINT,
        "profile",
        service_revision="b" * 40,
        index_profile_digest="c" * 64,
        provider_lanes=lanes,
        required_provider_lanes=values,
    )
    assert tuple(lane.provider_id for lane in capability.provider_lanes) == values

    for invalid in (tuple(reversed(values)), (values[0], values[0])):
        invalid_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        for lane, provider_id in zip(invalid_payload["provider_lanes"], invalid, strict=True):
            lane["provider_id"] = provider_id
        invalid_payload["required_provider_lanes"] = list(invalid)
        invalid_payload["capability_fingerprint"] = capability_fingerprint_v2(invalid_payload)
        with pytest.raises(ValueError, match="provider_lanes must be sorted and unique"):
            RetrievalV2CapabilityDto.from_dict(invalid_payload)
        invalid_lanes = tuple(
            core.LocatorProviderLaneCapabilityV2(value, True, True, 1_000_000, True)
            for value in invalid
        )
        with pytest.raises(ValueError, match="provider lanes must be sorted and unique"):
            core.LocatorRetrievalCapabilityV2(
                FINGERPRINT,
                "profile",
                service_revision="b" * 40,
                index_profile_digest="c" * 64,
                provider_lanes=invalid_lanes,
                required_provider_lanes=invalid,
            )


@pytest.mark.parametrize("values", CANONICAL_PROBES)
def test_utf8_order_has_independent_node_parity(values: tuple[str, str]) -> None:
    probes = [values[1], values[0], values[0]]
    script = r"""
const fs = require('fs');
const values = JSON.parse(fs.readFileSync(0, 'utf8'));
const utf8 = (a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
process.stdout.write(JSON.stringify(values.sort(utf8)));
"""
    actual = json.loads(
        subprocess.run(
            ["node", "-e", script],
            input=json.dumps(probes, ensure_ascii=False).encode("utf-8"),
            check=True,
            capture_output=True,
        ).stdout
    )
    assert actual == sorted(probes, key=_key)


def _key(value: str) -> bytes:
    return value.encode("utf-8")


def _dto_filters(**changes: tuple[str, ...]) -> RetrievalV2HardFiltersDto:
    return RetrievalV2HardFiltersDto(
        (RetrievalV2SourceGenerationDto("source", "generation"),), **changes
    )


def _core_filters(**changes: tuple[str, ...]) -> core.LocatorHardFiltersV2:
    return core.LocatorHardFiltersV2(
        (core.LocatorSourceGenerationV2("source", "generation"),), **changes
    )


def _dto_request(queries: tuple[RetrievalV2QueryDto, ...]) -> RetrieveContextV2RequestDto:
    return RetrieveContextV2RequestDto(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        FINGERPRINT,
        "profile",
        RetrievalV2ScopeDto("space", "scope"),
        queries,
        _dto_filters(),
    )


def _core_request(
    queries: tuple[core.LocatorQueryVariantV2, ...],
) -> core.LocatorRetrievalRequestV2:
    return core.LocatorRetrievalRequestV2(
        LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        FINGERPRINT,
        "profile",
        core.LocatorRetrievalScopeV2("space", "scope"),
        queries,
        _core_filters(),
        core.LocatorSoftPreferencesV2(),
        core.LocatorRetrievalBoundsV2(),
    )


def _dto_projection(**changes: tuple[str, ...]) -> DocumentRetrievalProjectionV1Dto:
    values: dict[str, object] = {
        "locator": "locator",
        "source_key": "source",
        "projection_generation": "generation",
        "sequence_ordinal": 1,
        "actor_keys": (),
        "time_interval": None,
        "kind": "kind",
        "category": "category",
        "tags": (),
    }
    values.update(changes)
    return DocumentRetrievalProjectionV1Dto(**values)  # type: ignore[arg-type]


def _core_projection(**changes: tuple[str, ...]) -> ingestion.DocumentRetrievalProjectionV1:
    values: dict[str, object] = {
        "locator": "locator",
        "source_key": "source",
        "projection_generation": "generation",
        "sequence_ordinal": 1,
        "actor_keys": (),
        "time_interval": None,
        "kind": "kind",
        "category": "category",
        "tags": (),
    }
    values.update(changes)
    return ingestion.DocumentRetrievalProjectionV1(**values)  # type: ignore[arg-type]


def _canonical_candidate(**changes: tuple[str, ...]) -> core.CanonicalLocatorCandidateV2:
    values: dict[str, object] = {
        "locator": "locator",
        "canonical_identity": "identity",
        "canonical_version": 1,
        "lifecycle_status": "active",
        "space_id": "space",
        "memory_scope_id": "scope",
        "source_key": "source",
        "document_key": "document",
        "chunk_key": "chunk",
        "projection_generation": "generation",
        "kind": "kind",
        "category": "category",
        "read_snapshot": "snapshot",
    }
    values.update(changes)
    return core.CanonicalLocatorCandidateV2(**values)  # type: ignore[arg-type]


def _dto_contribution(provider: str, query: str, score: float) -> RetrievalV2ContributionDto:
    picos = round(score * 1_000_000_000_000)
    return RetrievalV2ContributionDto(
        provider, query, 1, 1_000_000, 1_000_000, picos, 1.0, 1.0, picos / 1e12
    )


def _dto_candidate(
    contributions: tuple[RetrievalV2ContributionDto, ...], queries: tuple[str, ...]
) -> RetrievalV2CandidateDto:
    return RetrievalV2CandidateDto(
        "locator",
        "source",
        "document",
        "chunk",
        "identity",
        1,
        "active",
        provider_rank=1,
        fused_score=round(sum(item.contribution for item in contributions), 12),
        matched_query_ids=queries,
        contributions=contributions,
        base_score_picos=sum(item.contribution_score_picos for item in contributions),
    )


def _dto_empty_response(
    *,
    outcomes: tuple[RetrievalV2ProviderOutcomeDto, ...] = (),
    reasons: tuple[str, ...] = (),
) -> RetrieveContextV2ResponseDto:
    return RetrieveContextV2ResponseDto(
        "unavailable",
        FINGERPRINT,
        "profile",
        RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 0, 0),
        (),
        outcomes,
        reasons,
    )


def _core_contribution(provider: str, query: str, score: float) -> core.LocatorScoreContributionV2:
    return core.LocatorScoreContributionV2(
        provider, query, 1, 1_000_000, 1_000_000, round(score * 1_000_000_000_000)
    )


def _core_result_candidate(
    contributions: tuple[core.LocatorScoreContributionV2, ...], queries: tuple[str, ...]
) -> core.LocatorResultCandidateV2:
    return core.LocatorResultCandidateV2(
        "locator",
        "source",
        "document",
        "chunk",
        "identity",
        1,
        "active",
        1,
        round(sum(item.contribution for item in contributions), 12),
        queries,
        contributions,
        sum(item.contribution_score_picos for item in contributions),
    )


def _core_empty_response(
    *,
    outcomes: tuple[core.LocatorProviderOutcomeV2, ...] = (),
    reasons: tuple[str, ...] = (),
) -> core.LocatorRetrievalResponseV2:
    return core.LocatorRetrievalResponseV2(
        "unavailable",
        FINGERPRINT,
        "profile",
        core.LocatorAppliedBoundsV2(1, 1, 0, 16_384, 1, 0, 0),
        (),
        outcomes,
        reasons,
    )
