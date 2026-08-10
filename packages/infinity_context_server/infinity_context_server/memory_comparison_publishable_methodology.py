"""Sealed provider-neutral methodology required by the publishable keyless lane."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_profiles import (
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    FrozenPublishablePayload,
    freeze_publishable_payload,
    validated_publishable_payload,
)
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format_policy,
    locomo_judge_response_format_policy_sha256,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

LEGACY_PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION = "memory-comparison-publishable-methodology.v2"
LEGACY_PUBLISHABLE_METHODOLOGY_ID = "ic-vs-mem0-oss-keyless-methodology-v2"
LEGACY_PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256 = (
    "02e4bf4bd303d53887ad300a67a17e20923ce45640ffc68833abef81191b3219"
)
PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION = "memory-comparison-publishable-methodology.v3"
PUBLISHABLE_METHODOLOGY_ID = "ic-vs-mem0-oss-keyless-methodology-v3"
PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256 = (
    "78f7fee652c128378f03cbf3e0e8450334d05e70f76e1322ba082ee007fe2ba1"
)
PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION = "memory-comparison-publishable-methodology.v4"
PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID = "ic-vs-mem0-oss-keyless-methodology-v4"
PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256 = (
    "a9b6f12298157aa65d688cd0125b2c857fc0dcb045d6f2c3941b38c7560f8f69"
)
PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS = 4096
RUNTIME_PIN_FILE_SHA256 = "ae90790753549d621ba4f521a2d64026b4d2de7286fd9e683ad195cf1c85c525"
SUBSCRIPTION_RUNTIME_SOURCE_COMMIT = "e904ec95fda4b04c333e5a7613c7729bf7abb125"
SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256 = (
    "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
)


def resolve_publishable_methodology(
    value: str | None = PUBLISHABLE_METHODOLOGY_ID,
) -> FrozenPublishablePayload | None:
    if value is None:
        return None
    if type(value) is not str:
        raise BenchmarkValidationError("publishable methodology must be a string")
    methodology_id = value.strip()
    if not methodology_id:
        return None
    if methodology_id not in {
        LEGACY_PUBLISHABLE_METHODOLOGY_ID,
        PUBLISHABLE_METHODOLOGY_ID,
        PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    }:
        raise BenchmarkValidationError(f"unsupported publishable methodology {value!r}")
    methodology = freeze_publishable_payload(
        profile_id=methodology_id,
        payload=_methodology_payload(methodology_id),
    )
    if methodology.commitment_sha256 != _methodology_commitment(methodology_id):
        raise BenchmarkValidationError("publishable methodology commitment differs")
    return methodology


def publishable_priority_methodology_v4() -> FrozenPublishablePayload:
    """Return the explicitly selected priority-service methodology authority."""

    methodology = resolve_publishable_methodology(PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID)
    if methodology is None:
        raise BenchmarkValidationError("publishable priority methodology v4 is missing")
    return methodology


def public_publishable_methodology(
    methodology: FrozenPublishablePayload,
) -> dict[str, object]:
    methodology_id = (
        methodology.profile_id
        if type(methodology) is FrozenPublishablePayload
        else PUBLISHABLE_METHODOLOGY_ID
    )
    public = validated_publishable_payload(
        methodology,
        profile_id=methodology_id,
        expected=_methodology_payload(methodology_id),
    )
    if methodology.commitment_sha256 != _methodology_commitment(methodology_id):
        raise BenchmarkValidationError("publishable methodology commitment differs")
    return public


def _methodology_commitment(methodology_id: str) -> str:
    if methodology_id == PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID:
        return PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
    if methodology_id == PUBLISHABLE_METHODOLOGY_ID:
        return PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256
    if methodology_id == LEGACY_PUBLISHABLE_METHODOLOGY_ID:
        return LEGACY_PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256
    raise BenchmarkValidationError(f"unsupported publishable methodology {methodology_id!r}")


def _methodology_payload(methodology_id: str) -> dict[str, object]:
    if methodology_id == PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID:
        schema_version = PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION
        extraction_output_tokens = PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
        service_tier = "priority"
    elif methodology_id == PUBLISHABLE_METHODOLOGY_ID:
        schema_version = PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION
        extraction_output_tokens = PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
        service_tier = "default"
    elif methodology_id == LEGACY_PUBLISHABLE_METHODOLOGY_ID:
        schema_version = LEGACY_PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION
        extraction_output_tokens = 512
        service_tier = "default"
    else:
        raise BenchmarkValidationError(f"unsupported publishable methodology {methodology_id!r}")
    return {
        "schema_version": schema_version,
        "methodology_id": methodology_id,
        "mem0_mode": "pinned_oss_subscription_llm",
        "mem0_api_key_policy": "forbidden",
        "loopback_auth_mode": "managed_auth_disabled_allowlisted_ipv4",
        "official_harness_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "runtime_pin_file_sha256": RUNTIME_PIN_FILE_SHA256,
        "required_provider_kind": "subscription-runtime",
        "required_provider_trust": "codex_subscription_runtime",
        "required_model": "gpt-5.6-sol",
        "required_reasoning_effort": "high",
        "required_service_tier": service_tier,
        "required_transport_contract_id": "subscription-runtime-openai-codex-bridge.v4",
        "required_system_fingerprint_prefix": "subscription-runtime-codex-bridge-v4:",
        "required_runtime_receipt_schema": "subscription-runtime-codex-execution-receipt.v2",
        "required_execution_profile": "stateless-completion",
        "required_base_instructions_sha256": SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        "required_runtime_source_commit": SUBSCRIPTION_RUNTIME_SOURCE_COMMIT,
        "required_usage_accounting": "provider_observed_post_call",
        "required_output_limit_enforcement": "requested_not_provider_enforced",
        "required_extraction_scope": "shared_full_run",
        "required_extraction_binding": "run_attested_loopback_route",
        "required_judge_response_format_normalization": {
            **locomo_judge_response_format_policy(),
            "canonical_policy_sha256": locomo_judge_response_format_policy_sha256(),
        },
        "required_full_run_extraction_equivalence": {
            "activation_policy": "fail_closed",
            "required": True,
            "required_capacity": "attested_full_run",
            "required_route": "run_attested_loopback_route",
            "required_usage_ledger": "attested_full_run_usage_ledger",
            "current_runtime_capability": "isolated_single_add",
            "current_capability_satisfies_requirement": False,
        },
        "single_pass": True,
        "hard_token_budget_claimed": False,
        "generation": {
            "answer": {
                "temperature": 0,
                "requested_max_output_tokens": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
            },
            "judge": {
                "temperature": 0,
                "requested_max_output_tokens": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
            },
            "extraction": {
                "temperature": 0,
                "requested_max_output_tokens": extraction_output_tokens,
            },
        },
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "prompt_file_sha256": {
            "locomo": MEM0_OFFICIAL_PROMPT_FILE_SHA256["locomo"],
            "longmemeval": MEM0_OFFICIAL_PROMPT_FILE_SHA256["longmemeval"],
        },
        "retrieval_top_k": 200,
        "answer_cutoff": 50,
        "chronological_reorder": True,
        "gold_blind": True,
        "judge_evidence": False,
    }


__all__ = (
    "LEGACY_PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256",
    "LEGACY_PUBLISHABLE_METHODOLOGY_ID",
    "LEGACY_PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION",
    "PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256",
    "PUBLISHABLE_METHODOLOGY_ID",
    "PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION",
    "PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256",
    "PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID",
    "PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION",
    "PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS",
    "RUNTIME_PIN_FILE_SHA256",
    "SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256",
    "SUBSCRIPTION_RUNTIME_SOURCE_COMMIT",
    "publishable_priority_methodology_v4",
    "public_publishable_methodology",
    "resolve_publishable_methodology",
)
