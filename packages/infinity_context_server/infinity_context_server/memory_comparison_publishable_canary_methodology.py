"""Frozen same-lane methodology for the one-case activation canary."""

from __future__ import annotations

from infinity_context_server.memory_comparison_publishable_contracts import (
    FrozenPublishablePayload,
    freeze_publishable_payload,
    validated_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
    public_publishable_methodology,
    publishable_priority_methodology_v4,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

PUBLISHABLE_CANARY_METHODOLOGY_SCHEMA_VERSION = (
    "memory-comparison-publishable-one-case-canary-methodology.v1"
)
PUBLISHABLE_CANARY_METHODOLOGY_ID = "ic-vs-mem0-oss-keyless-v4-one-case-canary-methodology-v1"
PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256 = (
    "931fc50aaacbd100b5714cf318aaabf75e356cec4c326ea04d2e1b21cfe2dc17"
)


def publishable_canary_methodology() -> FrozenPublishablePayload:
    """Return the immutable activation-only methodology authority."""

    _validate_target_methodology()
    methodology = freeze_publishable_payload(
        profile_id=PUBLISHABLE_CANARY_METHODOLOGY_ID,
        payload=_methodology_payload(),
    )
    if methodology.commitment_sha256 != PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256:
        raise BenchmarkValidationError("publishable canary methodology commitment differs")
    return methodology


def public_publishable_canary_methodology(
    methodology: FrozenPublishablePayload,
) -> dict[str, object]:
    """Validate and expose a JSON-safe copy of the frozen methodology."""

    _validate_target_methodology()
    public = validated_publishable_payload(
        methodology,
        profile_id=PUBLISHABLE_CANARY_METHODOLOGY_ID,
        expected=_methodology_payload(),
    )
    if methodology.commitment_sha256 != PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256:
        raise BenchmarkValidationError("publishable canary methodology commitment differs")
    return public


def _validate_target_methodology() -> None:
    target = publishable_priority_methodology_v4()
    public = public_publishable_methodology(target)
    if (
        target.profile_id != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID
        or target.commitment_sha256 != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        or public["required_model"] != "gpt-5.6-sol"
        or public["required_reasoning_effort"] != "high"
        or public["required_service_tier"] != "priority"
        or public["required_provider_kind"] != "subscription-runtime"
        or public["required_provider_trust"] != "codex_subscription_runtime"
        or public["required_extraction_scope"] != "shared_full_run"
        or public["required_extraction_binding"] != "run_attested_loopback_route"
        or public["generation"]
        != {
            stage: {
                "temperature": 0,
                "requested_max_output_tokens": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
            }
            for stage in ("answer", "judge", "extraction")
        }
    ):
        raise BenchmarkValidationError("publishable canary target methodology differs")


def _methodology_payload() -> dict[str, object]:
    return {
        "schema_version": PUBLISHABLE_CANARY_METHODOLOGY_SCHEMA_VERSION,
        "methodology_id": PUBLISHABLE_CANARY_METHODOLOGY_ID,
        "purpose": "authenticated_activation_evidence_only",
        "publishable": False,
        "full_receipt_eligible": False,
        "full_profile_admission": "review_required",
        "target_full_methodology": {
            "methodology_id": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
            "commitment_sha256": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
        },
        "same_lane": {
            "required_provider_kind": "subscription-runtime",
            "required_provider_trust": "codex_subscription_runtime",
            "required_model": "gpt-5.6-sol",
            "required_reasoning_effort": "high",
            "required_service_tier": "priority",
            "requested_max_output_tokens": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
            "required_runtime_authority": "production_fleet_readiness_and_runtime_provenance",
            "required_input_authority": "production_official_case_and_retrieval_authorities",
            "required_extraction_authority": "production_shared_full_run_extraction_terminal",
            "required_answer_judge_path": "production_paired_infinity_vs_mem0",
        },
        "evidence_policy": {
            "activation_only": True,
            "quality_or_superiority_claimed": False,
            "replay_or_substitution_as_full_receipt": "forbidden",
            "full_profile_review_required": True,
        },
    }


__all__ = (
    "PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256",
    "PUBLISHABLE_CANARY_METHODOLOGY_ID",
    "PUBLISHABLE_CANARY_METHODOLOGY_SCHEMA_VERSION",
    "public_publishable_canary_methodology",
    "publishable_canary_methodology",
)
