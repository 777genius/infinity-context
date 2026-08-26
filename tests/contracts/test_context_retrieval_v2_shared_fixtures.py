from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_contracts.features.context_building import (
    CONTEXT_RETRIEVAL_ERROR_SPECS_V2,
    ContextRetrievalV2ErrorEnvelopeDto,
    RetrievalV2AppliedBoundsDto,
    RetrievalV2CandidateDto,
    RetrievalV2CapabilityDto,
    RetrievalV2ContributionDto,
    RetrievalV2HardFiltersDto,
    RetrievalV2NeighborDto,
    RetrievalV2ProviderOutcomeDto,
    RetrievalV2SourceGenerationDto,
    RetrieveContextV2RequestDto,
    RetrieveContextV2ResponseDto,
    capability_fingerprint_v2,
    decode_context_retrieval_v2_json,
)
from infinity_context_contracts.features.document_ingestion import (
    DocumentRetrievalProjectionV1Dto,
)
from infinity_context_core.features.context_building import public as core_context
from infinity_context_core.features.context_building.public import (
    rrf_contribution_score_picos_v2,
)
from infinity_context_core.features.document_ingestion import public as core_ingestion

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "fixtures"
    / "context_retrieval_v2"
)
FIXTURE_NAMES = {
    "capability.json",
    "request.json",
    "success.json",
    "errors.json",
    "document_projection.json",
    "cases.json",
    "scoring_golden.json",
    "hostile_responses.json",
    "transport_outcomes.json",
}
FIXTURE_SHA256 = {
    "capability.json": "22f34e9e49abf16a8fd6fbe0328bc3f4af08433e93a2ce32d9d2ace148089ddc",
    "cases.json": "cf94c7f8628778712d09ddf2879d5cb04dc79a612b604962a1100aa3009289c9",
    "document_projection.json": "4f6baae9e328535c28f2d22eba4153481a38ce337a9c31cf5c5d1ae1dd9546b0",
    "errors.json": "4f689df00e84aa032c00f43d85ad1737dd7e92a51c0fe73225756d7c5277db41",
    "request.json": "c219dd4da0588460205b95f7b0380df335a08a48fb33f9a1c0b9eac2df1a5672",
    "success.json": "bba0c5b8b53f50c8408150e3c1be3c75bda1c5262ed58615650bf082da17b8c1",
    "scoring_golden.json": "65b68e3a3076955c0295d193492137779d616b3dfee3669ab8cd26b5d9de6a4a",
    "hostile_responses.json": "b7ff6fb07815d2906e645b963acbaea49a46d3868e3157999839218f53ef7c86",
    "transport_outcomes.json": "ede8e57d2dfc44765b370a2b4a53c2c1944cb30c5c4e347775f4eed5b058fb04",
}
CASE_MATRIX = {
    "wire_exact_accept": ("wire", "accept"),
    "unknown_or_text_field_reject": ("wire", "reject"),
    "capability_shape_or_fingerprint_drift_reject": ("capability", "reject"),
    "required_lane_missing_unhealthy_unqualified_reject": ("capability", "reject"),
    "bounds_changed_or_response_oversize_reject": ("retrieval", "unavailable"),
    "duplicate_locator_or_identity_reject": ("response", "reject"),
    "cross_source_neighbor_reject": ("neighbor", "reject"),
    "same_source_cross_document_neighbor_accept": ("neighbor", "accept"),
    "projection_absent_not_eligible": ("projection", "not_eligible"),
    "projection_partial_unknown_or_caller_version_reject": ("projection", "reject"),
    "locator_owner_conflict_reject": ("ownership", "locator_conflict"),
    "ordinal_owner_conflict_reject": ("ownership", "ordinal_conflict"),
    "same_content_distinct_locator_accept": ("ownership", "accept"),
    "exact_projection_retry_idempotent": ("ownership", "idempotent"),
    "wrong_scope_generation_lifecycle_or_version_drop": ("hydration", "drop"),
    "profile_digest_generation_or_membership_drift_unavailable": (
        "profile",
        "unavailable",
    ),
    "delete_both_profiles_without_serving": ("lifecycle", "accepted_deferred"),
    "legacy_ingest_and_context_search_unchanged": ("legacy", "compatible"),
    "local_locator_zero_or_multiple_owner_drop_and_reauthorize": (
        "hydration",
        "drop",
    ),
}


def test_fixture_set_and_capability_fingerprint_are_canonical() -> None:
    assert {path.name for path in FIXTURES.iterdir() if path.is_file()} == FIXTURE_NAMES
    assert {
        name: hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        for name in sorted(FIXTURE_NAMES)
    } == FIXTURE_SHA256
    capability = _load("capability.json")
    parsed = RetrievalV2CapabilityDto.from_dict(capability)

    assert parsed.to_dict() == capability
    assert capability_fingerprint_v2(capability) == (
        "522cf13b82d20b8cf8f37b6e9fb3f4dc5752e24c9802c35b0f2fc30482083fae"
    )
    compact = json.dumps(
        {key: value for key, value in capability.items() if key != "capability_fingerprint"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(compact).hexdigest() == capability["capability_fingerprint"]


def test_shared_scoring_golden_reconstructs_all_authoritative_integers() -> None:
    golden = _load("scoring_golden.json")
    for case in golden["contribution_cases"]:
        assert 100_000 <= case["provider_weight_micros"] <= 10_000_000
        assert 100_000 <= case["query_weight_micros"] <= 10_000_000
        assert case["query_weight_micros"] <= case["total_query_weight_micros"]
        assert 1 <= case["provider_rank"] <= 1_000
        assert (
            rrf_contribution_score_picos_v2(
                case["provider_weight_micros"],
                case["query_weight_micros"],
                case["total_query_weight_micros"],
                case["provider_rank"],
            )
            == case["contribution_score_picos"]
        )
    for case in golden["composite_cases"]:
        base = sum(case["contribution_score_picos"])
        requested = sum(
            case[name]
            for name in (
                "source_requested_weight_micros",
                "actor_requested_weight_micros",
                "time_requested_weight_micros",
            )
        )
        matched = sum(
            case[name]
            for name in (
                "source_matched_weight_micros",
                "actor_matched_weight_micros",
                "time_matched_weight_micros",
            )
        )
        preference = 0 if requested == 0 else matched * 1_000_000 // requested
        boost = preference * 250_000 // 1_000_000
        assert base == case["base_score_picos"]
        assert preference == case["preference_score_micros"]
        assert boost == case["preference_boost_micros"]
        assert base * (1_000_000 + boost) // 1_000_000 == case["rerank_score_picos"]
    assert golden["utf8_tie_order"] == sorted(
        golden["utf8_tie_order"], key=lambda value: value.encode("utf-8")
    )


def test_shared_scoring_golden_matches_independent_javascript_bigint_oracle() -> None:
    cases = _load("scoring_golden.json")["contribution_cases"]
    script = r"""
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
function score(item) {
  const numerator = BigInt(item.provider_weight_micros)
    * BigInt(item.query_weight_micros) * 1000000n;
  const denominator = BigInt(item.total_query_weight_micros)
    * BigInt(60 + item.provider_rank);
  const quotient = numerator / denominator;
  const doubledRemainder = (numerator % denominator) * 2n;
  return (doubledRemainder > denominator
    || (doubledRemainder === denominator && quotient % 2n === 1n))
    ? quotient + 1n : quotient;
}
process.stdout.write(JSON.stringify(cases.map(item => score(item).toString())));
"""
    actual = json.loads(
        subprocess.run(
            ["node", "-e", script],
            input=json.dumps(cases).encode(),
            check=True,
            capture_output=True,
        ).stdout
    )
    assert actual == [str(case["contribution_score_picos"]) for case in cases]


@pytest.mark.parametrize(
    "weight_micros",
    [100_000, 100_001, 333_333, 999_999, 1_000_000, 1_250_000, 9_999_999, 10_000_000],
)
def test_capability_fingerprint_matches_independent_node_oracle(
    weight_micros: int,
) -> None:
    capability = _load("capability.json")
    capability["provider_lanes"][0]["weight_micros"] = weight_micros
    expected = capability_fingerprint_v2(capability)
    script = r"""
const crypto = require('crypto');
const fs = require('fs');
const value = JSON.parse(fs.readFileSync(0, 'utf8'));
delete value.capability_fingerprint;
function canonical(v) {
  if (Array.isArray(v)) return v.map(canonical);
  if (v !== null && typeof v === 'object') {
    const utf8 = (a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
    return Object.fromEntries(Object.keys(v).sort(utf8).map(k => [k, canonical(v[k])]));
  }
  return v;
}
process.stdout.write(crypto.createHash('sha256')
  .update(JSON.stringify(canonical(value)), 'utf8').digest('hex'));
"""
    actual = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(capability, ensure_ascii=False).encode(),
        check=True,
        capture_output=True,
    ).stdout.decode()
    assert actual == expected


@pytest.mark.parametrize("value", [True, 0.1, 99_999, 10_000_001])
def test_capability_wire_weight_micros_rejects_bool_float_and_range_drift(
    value: object,
) -> None:
    capability = _load("capability.json")
    capability["provider_lanes"][0]["weight_micros"] = value
    with pytest.raises(ValueError, match="weight_micros"):
        RetrievalV2CapabilityDto.from_dict(capability)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("rank_constant", 61),
        ("score_scale_picos", 999_999_999_999),
        ("max_preference_boost_micros", 249_999),
        ("contribution_rounding", "floor"),
        ("canonical_signal_match_policy", "derived_payload.v1"),
    ],
)
def test_ranking_parameter_mutation_changes_fingerprint_and_is_rejected(
    name: str, value: object
) -> None:
    capability = _load("capability.json")
    old_fingerprint = capability["capability_fingerprint"]
    capability["ranking_parameters"][name] = value
    assert capability_fingerprint_v2(capability) != old_fingerprint
    capability["capability_fingerprint"] = capability_fingerprint_v2(capability)
    with pytest.raises(ValueError, match="ranking_parameters"):
        RetrievalV2CapabilityDto.from_dict(capability)


def test_utf8_byte_order_matches_independent_node_oracle_for_unicode_and_duplicates() -> None:
    values = ["\U00010000", "\ue000", "é", "e\u0301", "Ж", "é"]
    expected_order = sorted(values, key=lambda value: value.encode("utf-8"))
    payload = {
        "\U00010000": {"é": 1, "e\u0301": 2},
        "\ue000": {"Ж": 3},
    }
    expected_fingerprint = capability_fingerprint_v2(payload)
    script = r"""
const crypto = require('crypto');
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const utf8 = (a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
function canonical(v) {
  if (Array.isArray(v)) return v.map(canonical);
  if (v !== null && typeof v === 'object') {
    return Object.fromEntries(Object.keys(v).sort(utf8).map(k => [k, canonical(v[k])]));
  }
  return v;
}
const digest = crypto.createHash('sha256')
  .update(JSON.stringify(canonical(input.payload)), 'utf8').digest('hex');
process.stdout.write(JSON.stringify({digest, ordered: input.values.sort(utf8)}));
"""
    actual = json.loads(
        subprocess.run(
            ["node", "-e", script],
            input=json.dumps({"values": values, "payload": payload}, ensure_ascii=False).encode(
                "utf-8"
            ),
            check=True,
            capture_output=True,
        ).stdout
    )

    assert actual == {"digest": expected_fingerprint, "ordered": expected_order}
    assert expected_order.index("\ue000") < expected_order.index("\U00010000")

    ordered_unique = tuple(dict.fromkeys(expected_order))
    RetrievalV2HardFiltersDto(
        tuple(RetrievalV2SourceGenerationDto(value, "generation") for value in ordered_unique)
    )
    core_context.LocatorHardFiltersV2(
        tuple(
            core_context.LocatorSourceGenerationV2(value, "generation") for value in ordered_unique
        )
    )
    unicode_outcomes = tuple(
        RetrievalV2ProviderOutcomeDto(value, "available") for value in ("\ue000", "\U00010000")
    )
    RetrieveContextV2ResponseDto(
        "unqualified",
        "a" * 64,
        "profile",
        RetrievalV2AppliedBoundsDto(1, 1, 0, 16_384, 1, 0, 0),
        (),
        unicode_outcomes,
    )
    core_response = asyncio.run(
        _core_retriever(candidates=(), provider_ids=("\ue000", "\U00010000")).execute(
            _core_request()
        )
    )
    assert tuple(item.provider_id for item in core_response.provider_outcomes) == (
        "\ue000",
        "\U00010000",
    )

    duplicate_projection = dict(_load("document_projection.json")["retrieval_projection"])
    duplicate_projection["tags"] = ["é", "é"]
    with pytest.raises(ValueError, match="sorted, unique"):
        DocumentRetrievalProjectionV1Dto.from_dict(duplicate_projection)


def test_capability_supports_neighbors_false_and_all_optional_lanes() -> None:
    capability = _load("capability.json")
    capability["supports_neighbors"] = False
    capability["required_provider_lanes"] = []
    for lane in capability["provider_lanes"]:
        lane["required"] = False
    capability["capability_fingerprint"] = capability_fingerprint_v2(capability)
    parsed = RetrievalV2CapabilityDto.from_dict(capability)
    assert parsed.supports_neighbors is False
    assert parsed.required_provider_lanes == ()


def test_request_success_and_projection_fixtures_serialize_exactly() -> None:
    request = _load("request.json")
    success = _load("success.json")
    projection = _load("document_projection.json")["retrieval_projection"]

    assert RetrieveContextV2RequestDto.from_dict(request).to_dict() == request
    assert RetrieveContextV2ResponseDto.from_dict(success).to_dict() == success
    assert _success_dto(success).to_dict() == success
    assert DocumentRetrievalProjectionV1Dto.from_dict(projection).to_dict() == projection
    _assert_locator_only(success)


@pytest.mark.parametrize(
    "forbidden",
    [
        "canonical_version",
        "provider_id",
        "text",
        "citations",
        "aliases",
        "authorization",
        "document_key",
        "chunk_key",
        "unknown",
    ],
)
def test_projection_boundary_rejects_caller_owned_or_unknown_fields(
    forbidden: str,
) -> None:
    projection = dict(_load("document_projection.json")["retrieval_projection"])
    projection[forbidden] = 1

    with pytest.raises(ValueError, match="exactly the canonical fields"):
        DocumentRetrievalProjectionV1Dto.from_dict(projection)


def test_projection_boundary_rejects_partial_unsorted_and_non_utc_values() -> None:
    projection = dict(_load("document_projection.json")["retrieval_projection"])
    projection.pop("kind")
    with pytest.raises(ValueError):
        DocumentRetrievalProjectionV1Dto.from_dict(projection)

    projection = dict(_load("document_projection.json")["retrieval_projection"])
    projection["tags"] = ["launch", "approved"]
    with pytest.raises(ValueError, match="sorted, unique"):
        DocumentRetrievalProjectionV1Dto.from_dict(projection)

    projection = dict(_load("document_projection.json")["retrieval_projection"])
    projection["time_interval"] = {
        "start_at": "2026-01-01T00:07:00+00:00",
        "end_at": "2026-01-01T00:08:00+00:00",
    }
    with pytest.raises(ValueError, match="using Z"):
        DocumentRetrievalProjectionV1Dto.from_dict(projection)


def test_error_fixture_is_the_exact_framework_neutral_envelope_and_code_table() -> None:
    errors = _load("errors.json")
    envelope = ContextRetrievalV2ErrorEnvelopeDto.from_dict(errors["envelope"])
    actual = {item["code"]: (item["http_status"], item["retryable"]) for item in errors["cases"]}

    assert envelope.to_dict() == errors["envelope"]
    assert envelope.http_status == 400
    assert actual == CONTEXT_RETRIEVAL_ERROR_SPECS_V2


@pytest.mark.parametrize("case_id", tuple(CASE_MATRIX))
def test_shared_cases_matrix_executes_unchanged(case_id: str) -> None:
    matrix = _load("cases.json")
    assert matrix["schema_version"] == "context-retrieval-v2-cases.v1"
    cases = {item["id"]: (item["subject"], item["expect"]) for item in matrix["cases"]}
    assert cases == CASE_MATRIX
    assert _execute_shared_case(case_id) == cases[case_id][1]


@pytest.mark.parametrize("duplicate_field", ("locator", "canonical_identity"))
def test_duplicate_locator_and_identity_reach_global_uniqueness_guard(
    duplicate_field: str,
) -> None:
    success = _load("success.json")
    original = success["candidates"][0]
    duplicate = copy.deepcopy(original)
    duplicate["neighbors"] = []
    duplicate["locator"] = f"{original['locator']}-z"
    duplicate["canonical_identity"] = f"{original['canonical_identity']}-z"
    duplicate["chunk_key"] = f"{original['chunk_key']}-z"
    duplicate[duplicate_field] = original[duplicate_field]
    success["candidates"].append(duplicate)
    success["applied_bounds"]["returned_seeds"] = 2

    with pytest.raises(ValueError, match="Locator response candidates must be globally unique"):
        RetrieveContextV2ResponseDto.from_dict(success)


def _execute_shared_case(case_id: str) -> str:
    request = _load("request.json")
    success = _load("success.json")
    projection = _load("document_projection.json")["retrieval_projection"]
    if case_id == "wire_exact_accept":
        RetrieveContextV2RequestDto.from_dict(request)
        return "accept"
    if case_id == "unknown_or_text_field_reject":
        request["text"] = "forbidden"
        return _typed_rejection(lambda: RetrieveContextV2RequestDto.from_dict(request))
    if case_id == "capability_shape_or_fingerprint_drift_reject":
        capability = _load("capability.json")
        capability["profile_id"] = "drifted-profile"
        return _typed_rejection(lambda: RetrievalV2CapabilityDto.from_dict(capability))
    if case_id == "required_lane_missing_unhealthy_unqualified_reject":
        capability = _load("capability.json")
        capability["provider_lanes"][0]["healthy"] = False
        capability["capability_fingerprint"] = capability_fingerprint_v2(capability)
        parsed = RetrievalV2CapabilityDto.from_dict(capability)
        response = asyncio.run(
            _core_retriever(
                capability=_core_capability(parsed),
                candidates=(_core_candidate("candidate"),),
            ).execute(_core_request(parsed.capability_fingerprint, parsed.profile_id))
        )
        return "reject" if response.status == "unavailable" else "accept"
    if case_id == "bounds_changed_or_response_oversize_reject":
        candidates = tuple(
            _core_candidate(f"candidate-{index}-" + "x" * 180, ordinal=index)
            for index in range(1, 51)
        )
        response = asyncio.run(
            _core_retriever(candidates=candidates).execute(
                _core_request(
                    bounds=core_context.LocatorRetrievalBoundsV2(
                        candidate_limit=50,
                        result_limit=50,
                        response_byte_limit=16_384,
                    )
                )
            )
        )
        return response.status
    if case_id == "duplicate_locator_or_identity_reject":
        success["candidates"].append(dict(success["candidates"][0]))
        success["applied_bounds"]["returned_seeds"] += 1
        success["applied_bounds"]["returned_neighbors"] += len(
            success["candidates"][-1]["neighbors"]
        )
        return _typed_rejection(lambda: RetrieveContextV2ResponseDto.from_dict(success))
    if case_id == "cross_source_neighbor_reject":
        success["candidates"][0]["neighbors"][0]["source_key"] = "other-source"
        return _typed_rejection(lambda: RetrieveContextV2ResponseDto.from_dict(success))
    if case_id == "same_source_cross_document_neighbor_accept":
        RetrieveContextV2ResponseDto.from_dict(success)
        return "accept"
    if case_id == "projection_absent_not_eligible":
        draft = core_ingestion.SourceDocumentDraft.create(
            scope=core_ingestion.DocumentIngestionScope("space", "scope"),
            title="title",
            origin=core_ingestion.SourceDocumentOrigin("test", "source"),
            text="content",
        )
        return "not_eligible" if draft.retrieval_projection is None else "accept"
    if case_id == "projection_partial_unknown_or_caller_version_reject":
        partial = dict(projection)
        partial.pop("locator")
        return _typed_rejection(lambda: DocumentRetrievalProjectionV1Dto.from_dict(partial))
    if case_id == "locator_owner_conflict_reject":
        ownership, handler = _ingestion_handler()
        asyncio.run(handler.execute(_ingest("one", "locator", 1)))
        try:
            asyncio.run(handler.execute(_ingest("changed", "locator", 2)))
        except core_ingestion.DocumentProjectionLocatorConflictError:
            return "locator_conflict"
        return "accept"
    if case_id == "ordinal_owner_conflict_reject":
        ownership, handler = _ingestion_handler()
        asyncio.run(handler.execute(_ingest("one", "locator-one", 1)))
        try:
            asyncio.run(handler.execute(_ingest("two", "locator-two", 1)))
        except core_ingestion.DocumentProjectionOrdinalConflictError:
            return "ordinal_conflict"
        return "accept"
    if case_id == "same_content_distinct_locator_accept":
        ownership, handler = _ingestion_handler()
        first = asyncio.run(handler.execute(_ingest("same", "one", 1)))
        second = asyncio.run(handler.execute(_ingest("same", "two", 2)))
        return (
            "accept"
            if first.document.content_hash == second.document.content_hash
            and first.document.identity != second.document.identity
            else "reject"
        )
    if case_id == "exact_projection_retry_idempotent":
        ownership, handler = _ingestion_handler()
        command = _ingest("same", "locator", 1, idempotency_key="retry")
        first = asyncio.run(handler.execute(command))
        ownership.document_ids["locator"] = first.document.identity.document_id
        retry = asyncio.run(handler.execute(command))
        return "idempotent" if retry.document == first.document else "reject"
    if case_id == "wrong_scope_generation_lifecycle_or_version_drop":
        candidates = (
            _core_candidate("wrong-scope", space_id="other"),
            _core_candidate("wrong-generation", generation="stale"),
            _core_candidate("deleted", lifecycle="deleted"),
            _core_candidate("stale-version", version=2),
        )
        response = asyncio.run(
            _core_retriever(candidates=candidates, hit_version=1).execute(_core_request())
        )
        return "drop" if not response.candidates else "accept"
    if case_id == "profile_digest_generation_or_membership_drift_unavailable":
        parsed = RetrievalV2CapabilityDto.from_dict(_load("capability.json"))
        capability = _core_capability(parsed)
        response = asyncio.run(
            _core_retriever(
                capability=capability,
                provider_ids=("postgres_keyword",),
                candidates=(_core_candidate("candidate"),),
            ).execute(_core_request(capability.capability_fingerprint, capability.profile_id))
        )
        return response.status
    if case_id == "delete_both_profiles_without_serving":
        deleted = (_core_candidate("deleted", lifecycle="deleted"),)
        statuses = tuple(
            asyncio.run(
                _core_retriever(
                    profile_id=profile_id,
                    candidates=deleted,
                ).execute(_core_request(profile_id=profile_id))
            ).status
            for profile_id in ("profile-a", "profile-b")
        )
        return "accepted_deferred" if statuses == ("unqualified", "unqualified") else "reject"
    if case_id == "legacy_ingest_and_context_search_unchanged":
        from infinity_context_contracts.features.context_building import BuildContextRequestDto

        legacy_dto = BuildContextRequestDto(query="legacy")
        _ownership, handler = _ingestion_handler(projected=False)
        ingested = asyncio.run(handler.execute(_legacy_ingest()))
        built = asyncio.run(
            core_context.BuildContextHandler(_LegacyCandidateProvider()).execute(
                core_context.BuildContextQuery(
                    query=core_context.ContextQuery(
                        core_context.ContextScope("space", "scope"), legacy_dto.query
                    ),
                    budget=core_context.ContextBudget(
                        max_prompt_tokens=32, reserved_response_tokens=8
                    ),
                )
            )
        )
        return (
            "compatible"
            if ingested.document.retrieval_projection is None
            and built.bundle.query.text == "legacy"
            else "reject"
        )
    if case_id == "local_locator_zero_or_multiple_owner_drop_and_reauthorize":
        candidates = (
            _core_candidate("zero-owner"),
            _core_candidate("multiple-owner", ordinal=2),
            _core_candidate("lost-authorization", ordinal=3),
        )
        reader = _OwnershipFilteringReader(
            candidates,
            owner_counts={"zero-owner": 0, "multiple-owner": 2, "lost-authorization": 1},
            final_authorized=frozenset(),
        )
        response = asyncio.run(
            _core_retriever(candidates=candidates, reader=reader).execute(_core_request())
        )
        return "drop" if not response.candidates and reader.final_reads == 1 else "accept"
    raise AssertionError(f"missing shared-case executor: {case_id}")


def _typed_rejection(action) -> str:
    with pytest.raises(ValueError):
        action()
    return "reject"


def _core_projection(locator: str) -> core_ingestion.DocumentRetrievalProjectionV1:
    return core_ingestion.DocumentRetrievalProjectionV1(
        locator, "source", "generation", 1, (), None, "record_block", "unclassified", ()
    )


@dataclass
class _LocatorProvider:
    provider_id: str
    candidates: tuple[core_context.CanonicalLocatorCandidateV2, ...]
    hit_version: int | None = None

    async def retrieve_locator_candidates(
        self, _request: core_context.LocatorRetrievalRequestV2
    ) -> core_context.LocatorProviderResultV2:
        return core_context.LocatorProviderResultV2(
            tuple(
                core_context.LocatorProviderHitV2(
                    item.canonical_identity,
                    item.canonical_version if self.hit_version is None else self.hit_version,
                    self.provider_id,
                    "q1",
                    rank,
                )
                for rank, item in enumerate(self.candidates, 1)
            )
        )


@dataclass
class _CanonicalReader:
    candidates: tuple[core_context.CanonicalLocatorCandidateV2, ...]

    async def hydrate_locator_candidates(
        self,
        _request: core_context.LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
    ) -> tuple[core_context.CanonicalLocatorCandidateV2, ...]:
        selected = set(canonical_identities)
        return tuple(item for item in self.candidates if item.canonical_identity in selected)

    async def hydrate_final_locator_read(
        self,
        _request: core_context.LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
        _radius: int,
    ) -> core_context.CanonicalLocatorReadV2:
        selected = set(canonical_identities)
        return core_context.CanonicalLocatorReadV2(
            tuple(item for item in self.candidates if item.canonical_identity in selected)
        )


class _OwnershipFilteringReader(_CanonicalReader):
    def __init__(
        self,
        candidates: tuple[core_context.CanonicalLocatorCandidateV2, ...],
        *,
        owner_counts: dict[str, int],
        final_authorized: frozenset[str],
    ) -> None:
        super().__init__(candidates)
        self.owner_counts = owner_counts
        self.final_authorized = final_authorized
        self.final_reads = 0

    async def hydrate_locator_candidates(
        self,
        request: core_context.LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
    ) -> tuple[core_context.CanonicalLocatorCandidateV2, ...]:
        rows = await super().hydrate_locator_candidates(request, canonical_identities)
        return tuple(row for row in rows if self.owner_counts[row.canonical_identity] == 1)

    async def hydrate_final_locator_read(
        self,
        request: core_context.LocatorRetrievalRequestV2,
        canonical_identities: tuple[str, ...],
        radius: int,
    ) -> core_context.CanonicalLocatorReadV2:
        self.final_reads += 1
        read = await super().hydrate_final_locator_read(request, canonical_identities, radius)
        return core_context.CanonicalLocatorReadV2(
            tuple(
                row
                for row in read.seeds
                if row.canonical_identity in self.final_authorized
                and self.owner_counts[row.canonical_identity] == 1
            )
        )


def _core_retriever(
    *,
    candidates: tuple[core_context.CanonicalLocatorCandidateV2, ...],
    capability: core_context.LocatorRetrievalCapabilityV2 | None = None,
    profile_id: str = "profile",
    provider_ids: tuple[str, ...] | None = None,
    hit_version: int | None = None,
    reader: _CanonicalReader | None = None,
) -> core_context.RetrieveLocatorsV2:
    descriptor = capability or core_context.LocatorRetrievalCapabilityV2("a" * 64, profile_id)
    lane_ids = tuple(lane.provider_id for lane in descriptor.provider_lanes)
    ids = provider_ids or lane_ids or ("dense",)
    providers = tuple(
        core_context.LocatorProviderRegistrationV2(
            provider_id,
            _LocatorProvider(provider_id, candidates, hit_version),
            weight_micros=(
                next(
                    (
                        lane.weight_micros
                        for lane in descriptor.provider_lanes
                        if lane.provider_id == provider_id
                    ),
                    1_000_000,
                )
            ),
            required=any(
                lane.provider_id == provider_id and lane.required
                for lane in descriptor.provider_lanes
            ),
        )
        for provider_id in ids
    )
    return core_context.RetrieveLocatorsV2(
        providers, reader or _CanonicalReader(candidates), descriptor
    )


def _core_request(
    fingerprint: str = "a" * 64,
    profile_id: str = "profile",
    *,
    bounds: core_context.LocatorRetrievalBoundsV2 | None = None,
) -> core_context.LocatorRetrievalRequestV2:
    return core_context.LocatorRetrievalRequestV2(
        core_context.LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        fingerprint,
        profile_id,
        core_context.LocatorRetrievalScopeV2("space", "scope"),
        (core_context.LocatorQueryVariantV2("q1", "query"),),
        core_context.LocatorHardFiltersV2(
            (core_context.LocatorSourceGenerationV2("source", "generation"),)
        ),
        core_context.LocatorSoftPreferencesV2(),
        bounds or core_context.LocatorRetrievalBoundsV2(),
    )


def _core_candidate(
    identity: str,
    *,
    ordinal: int = 1,
    space_id: str = "space",
    generation: str = "generation",
    lifecycle: str = "active",
    version: int = 1,
) -> core_context.CanonicalLocatorCandidateV2:
    return core_context.CanonicalLocatorCandidateV2(
        locator=f"locator:{identity}",
        canonical_identity=identity,
        canonical_version=version,
        lifecycle_status=lifecycle,
        space_id=space_id,
        memory_scope_id="scope",
        source_key="source",
        document_key=f"document:{identity}",
        chunk_key=f"chunk:{identity}",
        projection_generation=generation,
        kind="record_block",
        category="unclassified",
        read_snapshot="snapshot",
        sequence_ordinal=ordinal,
    )


def _core_capability(
    dto: RetrievalV2CapabilityDto,
) -> core_context.LocatorRetrievalCapabilityV2:
    return core_context.LocatorRetrievalCapabilityV2(
        capability_fingerprint=dto.capability_fingerprint,
        profile_id=dto.profile_id,
        supports_neighbors=dto.supports_neighbors,
        service_revision=dto.service_revision,
        sdk_revision=dto.sdk_revision,
        index_profile_digest=dto.index_profile_digest,
        provider_lanes=tuple(
            core_context.LocatorProviderLaneCapabilityV2(
                lane.provider_id,
                lane.required,
                lane.healthy,
                lane.weight_micros,
                lane.profile_qualified,
            )
            for lane in dto.provider_lanes
        ),
        required_provider_lanes=tuple(dto.required_provider_lanes),
    )


class _Documents:
    def __init__(self) -> None:
        self.values: list[core_ingestion.SourceDocument] = []

    async def create(
        self, document: core_ingestion.SourceDocument
    ) -> core_ingestion.SourceDocument:
        self.values.append(document)
        return document

    async def get(self, identity: str) -> core_ingestion.SourceDocument | None:
        return next(
            (document for document in self.values if document.identity.document_id == identity),
            None,
        )

    async def find_active_by_content_hash(
        self,
        *,
        scope: core_ingestion.DocumentIngestionScope,
        content_hash: str,
    ) -> core_ingestion.SourceDocument | None:
        return next(
            (
                document
                for document in self.values
                if document.identity.scope == scope
                and document.content_hash == content_hash
                and document.status == "active"
            ),
            None,
        )


class _Chunks:
    def __init__(self) -> None:
        self.values: list[core_ingestion.DocumentChunk] = []

    async def upsert(
        self, chunk: core_ingestion.DocumentChunk
    ) -> core_ingestion.DocumentChunkUpsertResult:
        self.values.append(chunk)
        return core_ingestion.DocumentChunkUpsertResult(chunk)

    async def list_for_document(
        self, document_id: str, *, limit: int | None = None
    ) -> tuple[core_ingestion.DocumentChunk, ...]:
        values = tuple(item for item in self.values if item.identity.document_id == document_id)
        return values if limit is None else values[:limit]


class _ProjectionOwnership:
    def __init__(self) -> None:
        self.claims: dict[str, core_ingestion.DocumentProjectionOwnershipClaimV1] = {}
        self.ordinals: dict[tuple[object, ...], str] = {}
        self.document_ids: dict[str, str] = {}

    async def claim_document_projection(
        self, claim: core_ingestion.DocumentProjectionOwnershipClaimV1
    ) -> core_ingestion.DocumentProjectionOwnershipDecisionV1:
        locator = claim.projection.locator
        prior = self.claims.get(locator)
        if prior is not None:
            if prior != claim:
                raise core_ingestion.DocumentProjectionLocatorConflictError(locator)
            return core_ingestion.DocumentProjectionOwnershipDecisionV1(
                "idempotent", self.document_ids[locator]
            )
        ordinal = (
            claim.scope.space_id,
            claim.scope.memory_scope_id,
            claim.scope.thread_id,
            claim.projection.source_key,
            claim.projection.projection_generation,
            claim.projection.sequence_ordinal,
        )
        if ordinal in self.ordinals:
            raise core_ingestion.DocumentProjectionOrdinalConflictError(locator)
        self.claims[locator] = claim
        self.ordinals[ordinal] = locator
        return core_ingestion.DocumentProjectionOwnershipDecisionV1("acquired")


def _ingestion_handler(
    *, projected: bool = True
) -> tuple[_ProjectionOwnership, core_ingestion.IngestDocumentHandler]:
    ownership = _ProjectionOwnership()
    return ownership, core_ingestion.IngestDocumentHandler(
        source_documents=_Documents(),
        chunks=_Chunks(),
        projection_ownership=ownership if projected else None,
    )


def _ingest(
    text: str,
    locator: str,
    ordinal: int,
    *,
    idempotency_key: str | None = None,
) -> core_ingestion.IngestDocumentCommand:
    return core_ingestion.IngestDocumentCommand(
        scope=core_ingestion.DocumentIngestionScope("space", "scope"),
        title="title",
        origin=core_ingestion.SourceDocumentOrigin("test", locator),
        text=text,
        retrieval_projection=core_ingestion.DocumentRetrievalProjectionV1(
            locator,
            "source",
            "generation",
            ordinal,
            (),
            None,
            "record_block",
            "unclassified",
            (),
        ),
        idempotency_key=idempotency_key,
    )


def _legacy_ingest() -> core_ingestion.IngestDocumentCommand:
    return core_ingestion.IngestDocumentCommand(
        scope=core_ingestion.DocumentIngestionScope("space", "scope"),
        title="legacy",
        origin=core_ingestion.SourceDocumentOrigin("legacy", "legacy-id"),
        text="legacy content",
    )


class _LegacyCandidateProvider:
    async def find_candidates(self, _request) -> tuple:
        return ()


def _success_dto(payload: dict[str, object]) -> RetrieveContextV2ResponseDto:
    bounds = payload["applied_bounds"]
    candidate = payload["candidates"][0]
    assert isinstance(bounds, dict) and isinstance(candidate, dict)
    contributions = tuple(RetrievalV2ContributionDto(**item) for item in candidate["contributions"])
    neighbors = tuple(RetrievalV2NeighborDto(**item) for item in candidate["neighbors"])
    direct = RetrievalV2CandidateDto(
        **{
            key: value
            for key, value in candidate.items()
            if key not in {"contributions", "neighbors"}
        },
        contributions=contributions,
        neighbors=neighbors,
    )
    outcomes = tuple(RetrievalV2ProviderOutcomeDto(**item) for item in payload["provider_outcomes"])
    return RetrieveContextV2ResponseDto(
        status=payload["status"],
        capability_fingerprint=payload["capability_fingerprint"],
        profile_id=payload["profile_id"],
        applied_bounds=RetrievalV2AppliedBoundsDto(**bounds),
        candidates=(direct,),
        provider_outcomes=outcomes,
        degradation_reason_codes=tuple(payload["degradation_reason_codes"]),
        contract_version=payload["contract_version"],
        ranking_policy=payload["ranking_policy"],
        coverage=payload["coverage"],
    )


def _load(name: str) -> dict[str, object]:
    return dict(decode_context_retrieval_v2_json((FIXTURES / name).read_bytes()))


def _assert_locator_only(value: object) -> None:
    forbidden = {"text", "citations", "metadata", "authorization", "aliases"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value)
        for nested in value.values():
            _assert_locator_only(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_locator_only(nested)
