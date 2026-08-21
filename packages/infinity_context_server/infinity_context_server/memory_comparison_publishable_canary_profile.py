"""Frozen scope for the non-publishable one-case activation canary."""

from __future__ import annotations

import hashlib

from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_canary_methodology import (
    PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
    PUBLISHABLE_CANARY_METHODOLOGY_ID,
    PUBLISHABLE_CANARY_METHODOLOGY_SCHEMA_VERSION,
    publishable_canary_methodology,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    FrozenPublishablePayload,
    freeze_publishable_payload,
    validated_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

PUBLISHABLE_CANARY_PROFILE_SCHEMA_VERSION = (
    "memory-comparison-publishable-one-case-canary-profile.v1"
)
PUBLISHABLE_CANARY_PROFILE_ID = "ic-vs-mem0-oss-keyless-v4-one-case-canary-v1"
PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256 = (
    "ef6badbd1659a8b3624a5f4e189d301af86f52c83ab562b21ba2638be1ec4a39"
)

PUBLISHABLE_CANARY_BENCHMARK = "locomo"
PUBLISHABLE_CANARY_RUN_INDEX = 0
PUBLISHABLE_CANARY_CASE_INDEX = 0
PUBLISHABLE_CANARY_CASE_ID = "conv-26:qa:1"
PUBLISHABLE_CANARY_CASE_ALIAS = (
    "locomo-case-d35fbfc8bdd80052ab62cf1449b0b9f40530819715231a13d4b0990b370c28c1"
)
PUBLISHABLE_CANARY_DATASET_SHA256 = LOCOMO_OFFICIAL_DATASET_SHA256
PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT = 4
PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES = (
    ("infinity-context", "answer"),
    ("infinity-context", "judge"),
    ("mem0", "answer"),
    ("mem0", "judge"),
)


def publishable_canary_case_alias() -> str:
    """Return the exact alias produced by the installed production policy."""

    material = (f"{PUBLISHABLE_CANARY_BENCHMARK}\0case\0{PUBLISHABLE_CANARY_CASE_ID}").encode()
    alias = f"{PUBLISHABLE_CANARY_BENCHMARK}-case-{hashlib.sha256(material).hexdigest()}"
    if alias != PUBLISHABLE_CANARY_CASE_ALIAS:
        raise BenchmarkValidationError("publishable canary case alias differs")
    return alias


def publishable_canary_profile() -> FrozenPublishablePayload:
    """Return the immutable one-case scope and activation policy."""

    _validate_target_profile()
    publishable_canary_methodology()
    profile = freeze_publishable_payload(
        profile_id=PUBLISHABLE_CANARY_PROFILE_ID,
        payload=_profile_payload(),
    )
    if profile.commitment_sha256 != PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256:
        raise BenchmarkValidationError("publishable canary profile commitment differs")
    return profile


def public_publishable_canary_profile(
    profile: FrozenPublishablePayload,
) -> dict[str, object]:
    """Validate and expose a JSON-safe copy of the frozen canary profile."""

    _validate_target_profile()
    publishable_canary_methodology()
    public = validated_publishable_payload(
        profile,
        profile_id=PUBLISHABLE_CANARY_PROFILE_ID,
        expected=_profile_payload(),
    )
    if profile.commitment_sha256 != PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256:
        raise BenchmarkValidationError("publishable canary profile commitment differs")
    return public


def _validate_target_profile() -> None:
    target = publishable_priority_comparison_profile_v4()
    public = public_publishable_comparison_profile(target)
    methodology = public.get("methodology")
    if (
        target.profile_id != PUBLISHABLE_PRIORITY_PROFILE_V4_ID
        or target.commitment_sha256 != PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
        or public["implementation_status"] != "contract_only"
        or public["execution_enabled"] is not False
        or public["publishable"] is not False
        or type(methodology) is not dict
        or methodology.get("methodology_id") != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID
        or methodology.get("commitment_sha256")
        != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
    ):
        raise BenchmarkValidationError("publishable canary target profile differs")


def _profile_payload() -> dict[str, object]:
    return {
        "schema_version": PUBLISHABLE_CANARY_PROFILE_SCHEMA_VERSION,
        "profile_id": PUBLISHABLE_CANARY_PROFILE_ID,
        "implementation_status": "activation_canary",
        "execution_enabled": True,
        "publishable": False,
        "activation_evidence_only": True,
        "full_receipt_eligible": False,
        "full_profile_admission": "review_required",
        "replay_or_substitution_as_full_receipt": "forbidden",
        "target_full_profile": {
            "profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            "commitment_sha256": PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
            "methodology_id": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
            "methodology_commitment_sha256": (
                PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
            ),
            "implementation_status": "contract_only",
            "execution_enabled": False,
            "publishable": False,
        },
        "methodology": {
            "schema_version": PUBLISHABLE_CANARY_METHODOLOGY_SCHEMA_VERSION,
            "methodology_id": PUBLISHABLE_CANARY_METHODOLOGY_ID,
            "commitment_sha256": PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
        },
        "scope": {
            "benchmark": PUBLISHABLE_CANARY_BENCHMARK,
            "dataset_sha256": PUBLISHABLE_CANARY_DATASET_SHA256,
            "run_index": PUBLISHABLE_CANARY_RUN_INDEX,
            "case_index": PUBLISHABLE_CANARY_CASE_INDEX,
            "case_id": PUBLISHABLE_CANARY_CASE_ID,
            "case_alias": publishable_canary_case_alias(),
            "case_count": 1,
        },
        "provider_call_authority": {
            "expected_provider_call_count": PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
            "caller_override_allowed": False,
            "ordered_calls": [
                {
                    "ordinal": ordinal,
                    "backend_role": backend_role,
                    "stage": stage,
                }
                for ordinal, (backend_role, stage) in enumerate(
                    PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES
                )
            ],
        },
        "claim_policy": {
            "quality_or_superiority_claimed": False,
            "paired_path_required": True,
            "production_input_and_extraction_authority_required": True,
            "production_runtime_and_fleet_authority_required": True,
        },
    }


__all__ = (
    "PUBLISHABLE_CANARY_BENCHMARK",
    "PUBLISHABLE_CANARY_CASE_ALIAS",
    "PUBLISHABLE_CANARY_CASE_ID",
    "PUBLISHABLE_CANARY_CASE_INDEX",
    "PUBLISHABLE_CANARY_DATASET_SHA256",
    "PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT",
    "PUBLISHABLE_CANARY_ORDERED_CALL_SHAPES",
    "PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256",
    "PUBLISHABLE_CANARY_PROFILE_ID",
    "PUBLISHABLE_CANARY_PROFILE_SCHEMA_VERSION",
    "PUBLISHABLE_CANARY_RUN_INDEX",
    "public_publishable_canary_profile",
    "publishable_canary_case_alias",
    "publishable_canary_profile",
)
