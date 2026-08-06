"""Contract-only profile for a future publishable Infinity versus pinned Mem0 OSS run."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_profiles import (
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
    PUBLISHABLE_METHODOLOGY_ID,
    PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION,
    resolve_publishable_methodology,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

PUBLISHABLE_PROFILE_SCHEMA_VERSION = "memory-comparison-publishable-profile.v2"
PUBLISHABLE_PROFILE_ID = "ic-vs-mem0-oss-keyless-v2"
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
    if profile_id != PUBLISHABLE_PROFILE_ID:
        raise BenchmarkValidationError(f"unsupported publishable comparison profile {value!r}")
    return freeze_publishable_payload(profile_id=profile_id, payload=_profile_payload())


def frozen_publishable_comparison_profile(
    profile: FrozenPublishablePayload,
) -> FrozenPublishablePayload:
    public_publishable_comparison_profile(profile)
    return freeze_publishable_payload(
        profile_id=PUBLISHABLE_PROFILE_ID,
        payload=_profile_payload(),
    )


def public_publishable_comparison_profile(
    profile: FrozenPublishablePayload,
) -> dict[str, object]:
    return validated_publishable_payload(
        profile,
        profile_id=PUBLISHABLE_PROFILE_ID,
        expected=_profile_payload(),
    )


def _profile_payload() -> dict[str, object]:
    methodology = resolve_publishable_methodology()
    if methodology is None:
        raise BenchmarkValidationError("publishable methodology is missing")
    specs = _benchmark_specs()
    return {
        "schema_version": PUBLISHABLE_PROFILE_SCHEMA_VERSION,
        "profile_id": PUBLISHABLE_PROFILE_ID,
        "implementation_status": "contract_only",
        "execution_enabled": False,
        "publishable": False,
        "claim_scope": "same_run_pinned_oss_only",
        "comparison_scope": "same_host_pinned_mem0_oss",
        "backends": list(PUBLISHABLE_COMPARISON_BACKENDS),
        "activation_blockers": list(PUBLISHABLE_ACTIVATION_BLOCKERS),
        "methodology": {
            "schema_version": PUBLISHABLE_METHODOLOGY_SCHEMA_VERSION,
            "methodology_id": PUBLISHABLE_METHODOLOGY_ID,
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
            expected_message_count=5882,
            grouping_field=locomo.distribution_field,
            expected_grouping=tuple(locomo.expected_distribution.items()),
            ingestion_contract="official-turns",
            extraction_call_budget=5882,
            answer_judge_call_budget=6160,
            total_call_budget=12042,
        ),
        BenchmarkSpec(
            benchmark="longmemeval",
            dataset_sha256=longmemeval.expected_dataset_hash,
            prompt_file_sha256=_prompt_hash("longmemeval"),
            expected_case_count=longmemeval.expected_case_count,
            expected_corpus_count=500,
            expected_message_count=246738,
            grouping_field=longmemeval.distribution_field,
            expected_grouping=tuple(longmemeval.expected_distribution.items()),
            ingestion_contract="official_user_assistant_pairs",
            extraction_call_budget=124344,
            answer_judge_call_budget=2000,
            total_call_budget=126344,
        ),
    )


def _legacy_profile(profile_id: str) -> FullComparisonProfile:
    profile = resolve_full_comparison_profile(profile_id)
    if profile is None:
        raise BenchmarkValidationError("authoritative full comparison profile is missing")
    return frozen_full_comparison_profile(profile)


def _prompt_hash(benchmark: str) -> str:
    from infinity_context_server.memory_comparison_full_profiles import (
        MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    )

    return MEM0_OFFICIAL_PROMPT_FILE_SHA256[benchmark]


def _required_count(value: int | None) -> int:
    if type(value) is not int or value < 1:
        raise BenchmarkValidationError("authoritative corpus count is missing")
    return value


__all__ = (
    "PUBLISHABLE_ACTIVATION_BLOCKERS",
    "PUBLISHABLE_PROFILE_ID",
    "PUBLISHABLE_PROFILE_SCHEMA_VERSION",
    "frozen_publishable_comparison_profile",
    "public_publishable_comparison_profile",
    "resolve_publishable_comparison_profile",
)
