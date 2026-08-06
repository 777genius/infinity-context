from __future__ import annotations

import json
from types import MappingProxyType

import pytest
from infinity_context_server.memory_comparison_full_methodology import (
    OFFICIAL_OPENAI_ENDPOINT_PATH,
    OFFICIAL_OPENAI_ORIGIN,
    OFFICIAL_PROVIDER,
    OFFICIAL_PROVIDER_TRUST,
    OFFICIAL_TRANSPORT,
    backend_set_contract,
    full_comparison_methodology_contract,
    prompt_provenance_issues,
    public_full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    FULL_COMPARISON_PROFILES,
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_MODEL,
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LOCOMO_TOP_200,
    PROFILE_LONGMEMEVAL_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_200,
    frozen_full_comparison_profile,
    public_full_comparison_profile,
    resolve_full_comparison_profile,
    resolve_retrieval_and_answer_cutoff,
    select_full_comparison_profile_cases,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)


def _profile(profile_id: str = PROFILE_LOCOMO_TOP_200):
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    return profile


def _case(benchmark: str, case_id: str, metadata: dict[str, object]) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=case_id,
        question="Question?",
        expected_terms=("answer",),
        metadata=metadata,
    )


def test_resolver_constructs_fresh_profiles_from_primitive_specs() -> None:
    assert FULL_COMPARISON_PROFILES == (
        PROFILE_LOCOMO_TOP_200,
        PROFILE_LOCOMO_TOP_50,
        PROFILE_LONGMEMEVAL_TOP_200,
        PROFILE_LONGMEMEVAL_TOP_50,
    )
    first = _profile()
    second = _profile()
    assert first is not second
    assert first.answer_token_budget_policy is not second.answer_token_budget_policy
    assert first.required_mem0_runtime_mode == "managed_platform"
    assert first.required_locomo_ingest_mode == "official-turns"
    assert first.retrieval_top_k == 200
    assert first.answer_cutoff == 200
    assert first.expected_case_count == 1540
    assert sum(first.expected_distribution.values()) == 1540
    assert type(first.expected_distribution) is MappingProxyType
    with pytest.raises(TypeError):
        first.expected_distribution["multi-hop"] = 0  # type: ignore[index]


def test_profile_and_nested_token_policy_mutation_are_rejected_against_primitives() -> None:
    profile = _profile()
    object.__setattr__(profile, "retrieval_top_k", 50)
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        frozen_full_comparison_profile(profile)

    profile = _profile()
    object.__setattr__(profile, "expected_case_count", 1540.0)
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        frozen_full_comparison_profile(profile)

    profile = _profile()
    object.__setattr__(
        profile.answer_token_budget_policy, "published_mem0_mean_tokens_reference", 1
    )
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        full_comparison_methodology_contract(profile)

    profile = _profile()
    object.__setattr__(
        profile.answer_token_budget_policy,
        "max_infinity_to_mem0_mean_prompt_token_ratio",
        1,
    )
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        frozen_full_comparison_profile(profile)

    profile = _profile()
    object.__setattr__(profile.answer_token_budget_policy, "policy_id", "forged")
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        public_full_comparison_profile(profile)


@pytest.mark.parametrize("invalid", (True, 200.0, "200"))
def test_widths_reject_bool_float_and_string_values(invalid: object) -> None:
    with pytest.raises(BenchmarkValidationError):
        resolve_retrieval_and_answer_cutoff(
            profile=None,
            legacy_top_k=200,
            retrieval_top_k=invalid,  # type: ignore[arg-type]
            answer_cutoff=50,
            legacy_cutoffs=(50,),
        )
    with pytest.raises(BenchmarkValidationError):
        resolve_retrieval_and_answer_cutoff(
            profile=None,
            legacy_top_k=200,
            retrieval_top_k=200,
            answer_cutoff=50,
            legacy_cutoffs=(invalid,),  # type: ignore[arg-type]
        )


def test_profile_cutoffs_and_case_selection_remain_exact() -> None:
    profile = _profile(PROFILE_LONGMEMEVAL_TOP_50)
    assert profile.expected_corpus_count == profile.expected_case_count == 500
    assert resolve_retrieval_and_answer_cutoff(
        profile=profile,
        legacy_top_k=17,
        retrieval_top_k=None,
        answer_cutoff=None,
        legacy_cutoffs=(3, 17),
    ) == (200, 50, (50,))
    with pytest.raises(BenchmarkValidationError, match="conflicts"):
        resolve_retrieval_and_answer_cutoff(
            profile=profile,
            legacy_top_k=200,
            retrieval_top_k=50,
            answer_cutoff=None,
            legacy_cutoffs=(50,),
        )

    locomo = _profile()
    one = _case("locomo", "one", {"category": 1})
    five = _case("locomo", "five", {"category": 5})
    other = _case("longmemeval", "other", {})
    assert select_full_comparison_profile_cases(
        profile=locomo,
        cases=(one, five, other),
    ) == (one,)
    with pytest.raises(BenchmarkValidationError, match="exact PublicBenchmarkCase"):
        select_full_comparison_profile_cases(
            profile=locomo,
            cases=(one, object()),  # type: ignore[arg-type]
        )


def test_methodology_is_deeply_immutable_and_has_safe_exact_projection() -> None:
    methodology = full_comparison_methodology_contract(_profile(PROFILE_LOCOMO_TOP_50))
    assert methodology["answerer_model"] == "gpt-5"
    assert methodology["retrieval_top_k"] == 200
    assert methodology["answer_cutoff"] == 50
    assert methodology["locomo_transport"] == {
        "required": True,
        "ingest_mode": "official-turns",
        "timestamps_required": True,
        "evidence_schema_version": "locomo-timestamp-transport-evidence.v5",
        "request_projection_schema_version": "locomo-add-request-producer-projection.v1",
        "request_observation": "producer_observed_canonical_projection",
        "expected_turn_contract": "sealed_loader_projection_exact_match",
        "expected_turn_authenticity": "deferred_to_dataset_composite_proof",
        "expected_loader_metadata": "speaker_session_date_trigger_case_id_exact",
        "trigger_case_id_role": "non_authoritative_ingestion_routing_observation",
        "trigger_case_id_receipt_binding": "sha256",
        "trigger_case_id_in_logical_turn_identity": False,
        "corpus_receipt_reuse": "permitted_after_corpus_reuse_proof",
        "serialized_expected_mapping_is_admission": False,
        "benchmark_user_identity_policy": "mem0-benchmark-user-id-sha256.v1",
        "runtime_http_identity_wiring": "required_before_full_preflight",
        "runtime_source_timestamp_wiring": "required_before_full_preflight",
        "provider_wire_bytes_attested": False,
        "counts_derived_from_projection": True,
    }
    assert methodology["official_provider_route"] == {
        "schema_version": "memory-comparison-official-provider-route.v1",
        "provider": "openai-compatible",
        "transport": "chat-completions",
        "trust": "official_openai",
        "origin": "https://api.openai.com",
        "endpoint_path": "/v1/chat/completions",
    }
    with pytest.raises(TypeError):
        methodology["locomo_transport"]["ingest_mode"] = "rich-documents"  # type: ignore[index]
    public = public_full_comparison_methodology_contract(methodology)
    assert json.loads(json.dumps(public)) == public
    assert public["answer_token_budget"]["published_mem0_reference"]["mean_tokens"] == 6956

    object.__setattr__(methodology, "_commitment_sha256", "0" * 64)
    with pytest.raises(BenchmarkValidationError, match="frozen primitives"):
        public_full_comparison_methodology_contract(methodology)

    methodology = full_comparison_methodology_contract(_profile(PROFILE_LOCOMO_TOP_50))
    mutable_public = public_full_comparison_methodology_contract(methodology)
    object.__setattr__(methodology, "_payload", MappingProxyType(mutable_public))
    with pytest.raises(BenchmarkValidationError, match="exact sealed type"):
        public_full_comparison_methodology_contract(methodology)


def _provider_provenance() -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-provider-call.v1",
        "trust": OFFICIAL_PROVIDER_TRUST,
        "origin": OFFICIAL_OPENAI_ORIGIN,
        "endpoint_path": OFFICIAL_OPENAI_ENDPOINT_PATH,
        "credential_bound": True,
        "credential_binding_id": "binding-1",
        "requested_model": MEM0_OFFICIAL_MODEL,
        "observed_model": MEM0_OFFICIAL_MODEL,
        "response_id": "chatcmpl-1",
        "system_fingerprint": "fp_1",
        "request_sha256": "a" * 64,
    }


def _stage(benchmark: str, stage: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider": OFFICIAL_PROVIDER,
        "transport": OFFICIAL_TRANSPORT,
        "stage": stage,
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "prompt_source_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "prompt_file_sha256": MEM0_OFFICIAL_PROMPT_FILE_SHA256[benchmark],
        "prompt_template": benchmark,
        "context_selection": "raw_retrieval_slice",
        "memory_order": "chronological_ascending",
        "temperature_policy": "zero_or_reasoning_model_default",
        "max_completion_tokens": 4096,
        "locomo_ingest_mode": "official-turns" if benchmark == "locomo" else None,
        "provider_provenance": _provider_provenance(),
    }
    if stage == "answerer":
        metadata["answer_postprocess"] = (
            "last_answer_marker"
            if benchmark == "locomo"
            else "strip_mem_thinking_then_last_answer_marker"
        )
    else:
        metadata["judge_evidence_mode"] = "none"
        metadata["judge_parser"] = "json_correct_wrong" if benchmark == "locomo" else "final_yes_no"
    return {"model": MEM0_OFFICIAL_MODEL, "metadata": metadata}


def _evaluation(benchmark: str = "locomo") -> dict[str, object]:
    return {
        "benchmark": benchmark,
        "execution_telemetry": {
            "context_selection": "raw_retrieval_slice",
            "answer_case_gold_blind": True,
            "locomo_ingest_mode": "official-turns" if benchmark == "locomo" else None,
        },
        "generation": _stage(benchmark, "answerer"),
        "judgment": _stage(benchmark, "judge"),
    }


def test_prompt_provenance_accepts_only_exact_official_route_and_prompt() -> None:
    evaluation = _evaluation()
    assert prompt_provenance_issues((evaluation,)) == {}
    assert backend_set_contract(("infinity-context", "mem0"))["matches"] is True


@pytest.mark.parametrize(
    ("mutation", "issue"),
    (
        (lambda item: item.update(benchmark="unknown"), "unknown_benchmark"),
        (
            lambda item: item["execution_telemetry"].update(locomo_ingest_mode="rich-documents"),
            "execution_telemetry_schema",
        ),
        (
            lambda item: item["generation"]["metadata"].update(prompt_policy_id="forged"),
            "answerer_prompt_policy_id",
        ),
        (
            lambda item: item["generation"]["metadata"].update(extra="unknown"),
            "answerer_metadata_keys",
        ),
        (
            lambda item: item["judgment"]["metadata"]["provider_provenance"].update(
                origin="https://proxy.invalid"
            ),
            "judge_provider_provenance",
        ),
    ),
)
def test_prompt_provenance_fails_closed_on_missing_unknown_or_forged_fields(
    mutation,
    issue: str,
) -> None:
    evaluation = _evaluation()
    mutation(evaluation)
    assert prompt_provenance_issues((evaluation,))[issue] == 1


def test_prompt_provenance_rejects_mapping_subclasses_without_calling_forged_get() -> None:
    class Forged(dict):
        def get(self, key, default=None):
            raise AssertionError("forged get must not be called")

    assert prompt_provenance_issues((Forged(_evaluation()),)) == {"invalid_evaluation_schema": 1}


def test_prompt_provenance_rejects_missing_hash_and_route_provenance() -> None:
    missing_hash = _evaluation()
    missing_hash["generation"]["metadata"].pop("prompt_file_sha256")
    issues = prompt_provenance_issues((missing_hash,))
    assert issues["answerer_metadata_keys"] == 1
    assert issues["answerer_prompt_file_sha256"] == 1

    missing_route = _evaluation()
    missing_route["judgment"]["metadata"].pop("provider_provenance")
    issues = prompt_provenance_issues((missing_route,))
    assert issues["judge_metadata_keys"] == 1
    assert issues["judge_provider_provenance"] == 1
