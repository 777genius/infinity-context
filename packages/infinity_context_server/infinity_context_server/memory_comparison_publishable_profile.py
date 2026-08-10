"""Contract-only profile for a future publishable Infinity versus pinned Mem0 OSS run."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_profiles import (
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_50,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    BenchmarkSpec,
    FrozenPublishablePayload,
    freeze_publishable_payload,
    validated_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    LEGACY_PUBLISHABLE_METHODOLOGY_ID,
    LEGACY_PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION,
    PUBLISHABLE_METHODOLOGY_ID,
    PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION,
    PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
    resolve_publishable_methodology,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

LEGACY_PUBLISHABLE_PROFILE_SCHEMA_VERSION = "memory-comparison-publishable-profile.v2"
LEGACY_PUBLISHABLE_PROFILE_ID = "ic-vs-mem0-oss-keyless-v2"
LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256 = (
    "9256c235cb5e90a8954caebd26a92011c67dc78772e8403233df5d4ebbfbce32"
)
PUBLISHABLE_PROFILE_SCHEMA_VERSION = "memory-comparison-publishable-profile.v3"
PUBLISHABLE_PROFILE_ID = "ic-vs-mem0-oss-keyless-v3"
PUBLISHABLE_PROFILE_COMMITMENT_SHA256 = (
    "f5f754847bd25ad43feab2ff6325af04c7f760dec690f30ede121dd629c0b8e1"
)
PUBLISHABLE_PRIORITY_PROFILE_V4_SCHEMA_VERSION = "memory-comparison-publishable-profile.v4"
PUBLISHABLE_PRIORITY_PROFILE_V4_ID = "ic-vs-mem0-oss-keyless-v4"
PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256 = (
    "a25c0b9a5cf51aa968872c94729cd02e8f0af7eb74b0f9d1930d4aa4ae9353c2"
)
PUBLISHABLE_COMPARISON_BACKENDS = ("infinity-context", "mem0")
PUBLISHABLE_COMPARABLE_METRICS = ("paired_answer_accuracy",)
PUBLISHABLE_NON_COMPARABLE_METRICS = ("latency", "provider_cost", "mem0_platform_score")
PUBLISHABLE_ACTIVATION_BLOCKERS = (
    "sealed_full_composition",
    "attested_runtime_v2",
    "checkpoint_resume",
    "cleanup_verifier",
    "one_plus_eight_gate",
    "full_run_extraction_equivalence",
)

# The pinned source has 246,750 messages across sessions, 1,940 of which have
# odd length. Pairing that source produces 124,345 slots. Normalization removes
# 12 invalid messages (leaving 246,738 and 1,944 odd sessions), but only one
# original slot is fully invalid and skipped by ingestion.
LONGMEMEVAL_RAW_MESSAGE_COUNT = 246_750
LONGMEMEVAL_INVALID_MESSAGE_COUNT = 12
LONGMEMEVAL_EXPECTED_MESSAGE_COUNT = (
    LONGMEMEVAL_RAW_MESSAGE_COUNT - LONGMEMEVAL_INVALID_MESSAGE_COUNT
)
LONGMEMEVAL_RAW_ODD_SESSION_COUNT = 1_940
LONGMEMEVAL_NORMALIZED_ODD_SESSION_COUNT = 1_944
LONGMEMEVAL_ORIGINAL_PAIR_SLOT_COUNT = (
    LONGMEMEVAL_RAW_MESSAGE_COUNT + LONGMEMEVAL_RAW_ODD_SESSION_COUNT
) // 2
LONGMEMEVAL_FULLY_INVALID_PAIR_COUNT = 1
LONGMEMEVAL_EXTRACTION_CALL_BUDGET = (
    LONGMEMEVAL_ORIGINAL_PAIR_SLOT_COUNT - LONGMEMEVAL_FULLY_INVALID_PAIR_COUNT
)
LOCOMO_EXTRACTION_CALL_BUDGET = 5_882
LOCOMO_ANSWER_JUDGE_CALL_BUDGET = 6_160
LONGMEMEVAL_ANSWER_JUDGE_CALL_BUDGET = 2_000
PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET = (
    LOCOMO_EXTRACTION_CALL_BUDGET + LONGMEMEVAL_EXTRACTION_CALL_BUDGET
)
PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET = (
    LOCOMO_ANSWER_JUDGE_CALL_BUDGET + LONGMEMEVAL_ANSWER_JUDGE_CALL_BUDGET
)
PUBLISHABLE_FULL_TOTAL_CALL_BUDGET = (
    PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET + PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET
)
PUBLISHABLE_FULL_EXTRACTION_REQUESTED_OUTPUT_TOKEN_RESERVATION = (
    PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET * PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
)
PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION = (
    PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET * PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
)
PUBLISHABLE_FULL_REQUESTED_OUTPUT_TOKEN_RESERVATION = (
    PUBLISHABLE_FULL_TOTAL_CALL_BUDGET * PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS
)


def resolve_publishable_comparison_profile(
    value: str | None = PUBLISHABLE_PROFILE_ID,
) -> FrozenPublishablePayload | None:
    if value is None:
        return None
    if type(value) is not str:
        raise BenchmarkValidationError("publishable comparison profile must be a string")
    profile_id = value.strip()
    if not profile_id:
        return None
    if profile_id not in {
        LEGACY_PUBLISHABLE_PROFILE_ID,
        PUBLISHABLE_PROFILE_ID,
        PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    }:
        raise BenchmarkValidationError(f"unsupported publishable comparison profile {value!r}")
    profile = freeze_publishable_payload(
        profile_id=profile_id,
        payload=_profile_payload(profile_id),
    )
    if profile.commitment_sha256 != _profile_commitment(profile_id):
        raise BenchmarkValidationError("publishable comparison profile commitment differs")
    return profile


def publishable_priority_comparison_profile_v4() -> FrozenPublishablePayload:
    """Return the explicitly selected priority-service comparison authority."""

    profile = resolve_publishable_comparison_profile(PUBLISHABLE_PRIORITY_PROFILE_V4_ID)
    if profile is None:
        raise BenchmarkValidationError("publishable priority comparison profile v4 is missing")
    return profile


def frozen_publishable_comparison_profile(
    profile: FrozenPublishablePayload,
) -> FrozenPublishablePayload:
    public_publishable_comparison_profile(profile)
    frozen = freeze_publishable_payload(
        profile_id=profile.profile_id,
        payload=_profile_payload(profile.profile_id),
    )
    if frozen.commitment_sha256 != _profile_commitment(profile.profile_id):
        raise BenchmarkValidationError("publishable comparison profile commitment differs")
    return frozen


def public_publishable_comparison_profile(
    profile: FrozenPublishablePayload,
) -> dict[str, object]:
    profile_id = (
        profile.profile_id if type(profile) is FrozenPublishablePayload else PUBLISHABLE_PROFILE_ID
    )
    public = validated_publishable_payload(
        profile,
        profile_id=profile_id,
        expected=_profile_payload(profile_id),
    )
    if profile.commitment_sha256 != _profile_commitment(profile_id):
        raise BenchmarkValidationError("publishable comparison profile commitment differs")
    return public


def _profile_commitment(profile_id: str) -> str:
    if profile_id == PUBLISHABLE_PRIORITY_PROFILE_V4_ID:
        return PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
    if profile_id == PUBLISHABLE_PROFILE_ID:
        return PUBLISHABLE_PROFILE_COMMITMENT_SHA256
    if profile_id == LEGACY_PUBLISHABLE_PROFILE_ID:
        return LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256
    raise BenchmarkValidationError(f"unsupported publishable comparison profile {profile_id!r}")


def _profile_payload(profile_id: str) -> dict[str, object]:
    if profile_id == PUBLISHABLE_PRIORITY_PROFILE_V4_ID:
        schema_version = PUBLISHABLE_PRIORITY_PROFILE_V4_SCHEMA_VERSION
        methodology_schema = PUBLISHABLE_PRIORITY_METHODOLOGY_V4_SCHEMA_VERSION
        methodology_id = PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID
    elif profile_id == PUBLISHABLE_PROFILE_ID:
        schema_version = PUBLISHABLE_PROFILE_SCHEMA_VERSION
        methodology_schema = PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION
        methodology_id = PUBLISHABLE_METHODOLOGY_ID
    elif profile_id == LEGACY_PUBLISHABLE_PROFILE_ID:
        schema_version = LEGACY_PUBLISHABLE_PROFILE_SCHEMA_VERSION
        methodology_schema = LEGACY_PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION
        methodology_id = LEGACY_PUBLISHABLE_METHODOLOGY_ID
    else:
        raise BenchmarkValidationError(f"unsupported publishable comparison profile {profile_id!r}")
    methodology = resolve_publishable_methodology(methodology_id)
    if methodology is None:
        raise BenchmarkValidationError("publishable methodology is missing")
    specs = _benchmark_specs()
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "profile_id": profile_id,
        "implementation_status": "contract_only",
        "execution_enabled": False,
        "publishable": False,
        "claim_scope": "same_run_pinned_oss_only",
        "comparison_scope": "same_host_pinned_mem0_oss",
        "backends": list(PUBLISHABLE_COMPARISON_BACKENDS),
        "activation_blockers": list(PUBLISHABLE_ACTIVATION_BLOCKERS),
        "methodology": {
            "schema_version": methodology_schema,
            "methodology_id": methodology_id,
            "commitment_sha256": methodology.commitment_sha256,
            "observed": False,
        },
        "primary_metric_id": "paired_answer_accuracy",
        "comparable_metrics": list(PUBLISHABLE_COMPARABLE_METRICS),
        "non_comparable_metrics": list(PUBLISHABLE_NON_COMPARABLE_METRICS),
        "vendor_reference_publishable": False,
        "benchmarks": {
            spec.benchmark: {
                **spec.payload(),
                "commitment_sha256": spec.commitment_sha256,
                "execution_enabled": False,
            }
            for spec in specs
        },
    }
    if profile_id in {PUBLISHABLE_PROFILE_ID, PUBLISHABLE_PRIORITY_PROFILE_V4_ID}:
        payload["full_run_call_budget"] = {
            "extraction_call_budget": PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET,
            "answer_judge_call_budget": PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET,
            "total_call_budget": PUBLISHABLE_FULL_TOTAL_CALL_BUDGET,
        }
        payload["full_run_requested_output_token_reservation"] = {
            "requested_max_output_tokens_per_call": (PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS),
            "extraction_requested_output_tokens": (
                PUBLISHABLE_FULL_EXTRACTION_REQUESTED_OUTPUT_TOKEN_RESERVATION
            ),
            "answer_judge_requested_output_tokens": (
                PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION
            ),
            "total_requested_output_tokens": (PUBLISHABLE_FULL_REQUESTED_OUTPUT_TOKEN_RESERVATION),
            "output_limit_enforcement": "requested_not_provider_enforced",
            "hard_token_budget_claimed": False,
        }
    return payload


def _benchmark_specs() -> tuple[BenchmarkSpec, BenchmarkSpec]:
    locomo = _legacy_profile(PROFILE_LOCOMO_TOP_50)
    longmemeval = _legacy_profile(PROFILE_LONGMEMEVAL_TOP_50)
    return (
        BenchmarkSpec(
            benchmark="locomo",
            dataset_sha256=locomo.expected_dataset_hash,
            prompt_file_sha256=_prompt_hash("locomo"),
            expected_case_count=locomo.expected_case_count,
            expected_corpus_count=_required_count(locomo.expected_corpus_count),
            expected_message_count=LOCOMO_EXTRACTION_CALL_BUDGET,
            grouping_field=locomo.distribution_field,
            expected_grouping=tuple(locomo.expected_distribution.items()),
            ingestion_contract="official-turns",
            extraction_call_budget=LOCOMO_EXTRACTION_CALL_BUDGET,
            answer_judge_call_budget=LOCOMO_ANSWER_JUDGE_CALL_BUDGET,
            total_call_budget=(LOCOMO_EXTRACTION_CALL_BUDGET + LOCOMO_ANSWER_JUDGE_CALL_BUDGET),
        ),
        BenchmarkSpec(
            benchmark="longmemeval",
            dataset_sha256=longmemeval.expected_dataset_hash,
            prompt_file_sha256=_prompt_hash("longmemeval"),
            expected_case_count=longmemeval.expected_case_count,
            expected_corpus_count=_required_count(longmemeval.expected_corpus_count),
            expected_message_count=LONGMEMEVAL_EXPECTED_MESSAGE_COUNT,
            grouping_field=longmemeval.distribution_field,
            expected_grouping=tuple(longmemeval.expected_distribution.items()),
            ingestion_contract="official_user_assistant_pairs",
            extraction_call_budget=LONGMEMEVAL_EXTRACTION_CALL_BUDGET,
            answer_judge_call_budget=LONGMEMEVAL_ANSWER_JUDGE_CALL_BUDGET,
            total_call_budget=(
                LONGMEMEVAL_EXTRACTION_CALL_BUDGET + LONGMEMEVAL_ANSWER_JUDGE_CALL_BUDGET
            ),
        ),
    )


def _legacy_profile(profile_id: str) -> FullComparisonProfile:
    profile = resolve_full_comparison_profile(profile_id)
    if profile is None:
        raise BenchmarkValidationError("authoritative full comparison profile is missing")
    return frozen_full_comparison_profile(profile)


def _prompt_hash(benchmark: str) -> str:
    return MEM0_OFFICIAL_PROMPT_FILE_SHA256[benchmark]


def _required_count(value: int | None) -> int:
    if type(value) is not int or value < 1:
        raise BenchmarkValidationError("authoritative corpus count is missing")
    return value


__all__ = (
    "LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256",
    "LEGACY_PUBLISHABLE_PROFILE_ID",
    "LEGACY_PUBLISHABLE_PROFILE_SCHEMA_VERSION",
    "LOCOMO_ANSWER_JUDGE_CALL_BUDGET",
    "LOCOMO_EXTRACTION_CALL_BUDGET",
    "LONGMEMEVAL_ANSWER_JUDGE_CALL_BUDGET",
    "LONGMEMEVAL_EXTRACTION_CALL_BUDGET",
    "PUBLISHABLE_ACTIVATION_BLOCKERS",
    "PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET",
    "PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION",
    "PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET",
    "PUBLISHABLE_FULL_EXTRACTION_REQUESTED_OUTPUT_TOKEN_RESERVATION",
    "PUBLISHABLE_FULL_REQUESTED_OUTPUT_TOKEN_RESERVATION",
    "PUBLISHABLE_FULL_TOTAL_CALL_BUDGET",
    "PUBLISHABLE_PROFILE_ID",
    "PUBLISHABLE_PROFILE_COMMITMENT_SHA256",
    "PUBLISHABLE_PROFILE_SCHEMA_VERSION",
    "PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256",
    "PUBLISHABLE_PRIORITY_PROFILE_V4_ID",
    "PUBLISHABLE_PRIORITY_PROFILE_V4_SCHEMA_VERSION",
    "frozen_publishable_comparison_profile",
    "publishable_priority_comparison_profile_v4",
    "public_publishable_comparison_profile",
    "resolve_publishable_comparison_profile",
)
