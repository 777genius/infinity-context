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
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION = "memory-comparison-publishable-methodology.v1"
PUBLISHABLE_METHODOLOGY_ID = "ic-vs-mem0-oss-keyless-methodology-v1"
RUNTIME_PIN_FILE_SHA256 = "ae90790753549d621ba4f521a2d64026b4d2de7286fd9e683ad195cf1c85c525"


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
    if methodology_id != PUBLISHABLE_METHODOLOGY_ID:
        raise BenchmarkValidationError(f"unsupported publishable methodology {value!r}")
    return freeze_publishable_payload(
        profile_id=methodology_id,
        payload=_methodology_payload(),
    )


def public_publishable_methodology(
    methodology: FrozenPublishablePayload,
) -> dict[str, object]:
    return validated_publishable_payload(
        methodology,
        profile_id=PUBLISHABLE_METHODOLOGY_ID,
        expected=_methodology_payload(),
    )


def _methodology_payload() -> dict[str, object]:
    return {
        "schema_version": PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION,
        "methodology_id": PUBLISHABLE_METHODOLOGY_ID,
        "mem0_mode": "pinned_oss_subscription_llm",
        "mem0_api_key_policy": "forbidden",
        "loopback_auth_mode": "managed_auth_disabled_allowlisted_ipv4",
        "official_harness_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        "runtime_pin_file_sha256": RUNTIME_PIN_FILE_SHA256,
        "required_provider_kind": "subscription-runtime",
        "required_provider_trust": "codex_subscription_runtime",
        "required_model": "gpt-5.6-sol",
        "required_reasoning_effort": "high",
        "required_service_tier": "default",
        "required_transport_contract_id": "subscription-runtime-openai-codex-bridge.v2",
        "required_runtime_receipt_schema": "subscription-runtime-codex-execution-receipt.v1",
        "required_usage_accounting": "provider_observed_post_call",
        "required_output_limit_enforcement": "requested_not_provider_enforced",
        "required_extraction_scope": "shared_full_run",
        "required_extraction_binding": "run_attested_loopback_route",
        "single_pass": True,
        "hard_token_budget_claimed": False,
        "generation": {
            "answer": {"temperature": 0, "requested_max_output_tokens": 4096},
            "judge": {"temperature": 0, "requested_max_output_tokens": 4096},
            "extraction": {"temperature": 0, "requested_max_output_tokens": 512},
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
    "PUBLISHABLE_METHODOLOGY_ID",
    "PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION",
    "RUNTIME_PIN_FILE_SHA256",
    "public_publishable_methodology",
    "resolve_publishable_methodology",
)
