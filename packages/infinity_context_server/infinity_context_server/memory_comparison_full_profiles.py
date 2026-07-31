"""Frozen primitive profile specifications for official full comparisons."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

from infinity_context_server.memory_comparison_token_budget_contract import (
    TOKEN_BUDGET_POLICY_ID,
    AnswerTokenBudgetPolicy,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)

MEM0_BENCHMARK_UPSTREAM_COMMIT = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
MEM0_OFFICIAL_PROMPT_POLICY = "mem0-official-qa-v1"
INFINITY_PROMPT_POLICY = "infinity-evidence-policy-v1"
MEM0_OFFICIAL_MODEL = "gpt-5"
INFINITY_COMPARISON_BACKEND = "infinity-context"
REQUIRED_FULL_COMPARISON_BACKENDS = (INFINITY_COMPARISON_BACKEND, "mem0")
LOCOMO_OFFICIAL_PROMPT_FILE_SHA256 = (
    "8ebac1ef60e9ab5caf99079fdaac038b85472e81491ed35e2d2655f3927c76c2"
)
LONGMEMEVAL_OFFICIAL_PROMPT_FILE_SHA256 = (
    "ba8cf60d26f1390ecbef0f07b3e950556fe3bc5a37ba4b5343f28217f18c144f"
)
MEM0_OFFICIAL_PROMPT_FILE_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "locomo": LOCOMO_OFFICIAL_PROMPT_FILE_SHA256,
        "longmemeval": LONGMEMEVAL_OFFICIAL_PROMPT_FILE_SHA256,
    }
)
LOCOMO_OFFICIAL_DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
LONGMEMEVAL_OFFICIAL_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
PROFILE_LOCOMO_TOP_200 = "mem0-locomo-top200-v1"
PROFILE_LOCOMO_TOP_50 = "mem0-locomo-top50-v1"
PROFILE_LONGMEMEVAL_TOP_200 = "mem0-longmemeval-top200-v1"
PROFILE_LONGMEMEVAL_TOP_50 = "mem0-longmemeval-top50-v1"


class _ProfileSpec(NamedTuple):
    profile_id: str
    benchmark: str
    expected_dataset_hash: str
    expected_case_count: int
    expected_distribution: tuple[tuple[str, int], ...]
    distribution_field: str
    answer_cutoff: int
    token_reference: int
    expected_corpus_count: int | None
    required_locomo_ingest_mode: str | None


# Only primitive immutable values are authoritative. DTO instances never are.
_PROFILE_SPECS = (
    _ProfileSpec(
        PROFILE_LOCOMO_TOP_200,
        "locomo",
        LOCOMO_OFFICIAL_DATASET_SHA256,
        1540,
        (("multi-hop", 282), ("temporal", 321), ("open-domain", 96), ("single-hop", 841)),
        "locomo_category",
        200,
        6956,
        10,
        "official-turns",
    ),
    _ProfileSpec(
        PROFILE_LOCOMO_TOP_50,
        "locomo",
        LOCOMO_OFFICIAL_DATASET_SHA256,
        1540,
        (("multi-hop", 282), ("temporal", 321), ("open-domain", 96), ("single-hop", 841)),
        "locomo_category",
        50,
        6956,
        10,
        "official-turns",
    ),
    _ProfileSpec(
        PROFILE_LONGMEMEVAL_TOP_200,
        "longmemeval",
        LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
        500,
        (
            ("knowledge-update", 78),
            ("multi-session", 133),
            ("single-session-assistant", 56),
            ("single-session-preference", 30),
            ("single-session-user", 70),
            ("temporal", 133),
        ),
        "longmemeval_question_type",
        200,
        6787,
        None,
        None,
    ),
    _ProfileSpec(
        PROFILE_LONGMEMEVAL_TOP_50,
        "longmemeval",
        LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
        500,
        (
            ("knowledge-update", 78),
            ("multi-session", 133),
            ("single-session-assistant", 56),
            ("single-session-preference", 30),
            ("single-session-user", 70),
            ("temporal", 133),
        ),
        "longmemeval_question_type",
        50,
        6787,
        None,
        None,
    ),
)
FULL_COMPARISON_PROFILES = tuple(spec.profile_id for spec in _PROFILE_SPECS)


@dataclass(frozen=True, slots=True)
class FullComparisonProfile:
    """Immutable projection; authority remains the independent primitive spec."""

    profile_id: str
    benchmark: str
    expected_dataset_hash: str
    expected_case_count: int
    expected_distribution: Mapping[str, int]
    distribution_field: str
    retrieval_top_k: int
    answer_cutoff: int
    answer_token_budget_policy: AnswerTokenBudgetPolicy
    required_mem0_runtime_mode: str
    expected_corpus_count: int | None
    required_locomo_ingest_mode: str | None

    def __post_init__(self) -> None:
        if type(self.expected_distribution) is not MappingProxyType:
            if type(self.expected_distribution) is not dict:
                raise ValueError("expected_distribution must be an exact dict")
            object.__setattr__(
                self,
                "expected_distribution",
                MappingProxyType(dict(self.expected_distribution)),
            )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonProfile is sealed")


def resolve_full_comparison_profile(value: str | None) -> FullComparisonProfile | None:
    if value is None:
        return None
    if type(value) is not str:
        raise BenchmarkValidationError("full comparison profile must be a string")
    profile_id = value.strip()
    if not profile_id:
        return None
    spec = _spec_for_id(profile_id)
    if spec is None:
        choices = ", ".join(FULL_COMPARISON_PROFILES)
        raise BenchmarkValidationError(
            f"unsupported full comparison profile {value!r}; choose one of: {choices}"
        )
    return _profile_from_spec(spec)


def frozen_full_comparison_profile(profile: FullComparisonProfile) -> FullComparisonProfile:
    """Revalidate every exact field, then return a fresh trusted projection."""

    if type(profile) is not FullComparisonProfile:
        raise BenchmarkValidationError("full comparison profile must have the exact sealed type")
    profile_id = _exact_string(profile.profile_id)
    spec = _spec_for_id(profile_id) if profile_id is not None else None
    if spec is None or not _profile_matches_spec(profile, spec):
        raise BenchmarkValidationError("full comparison profile differs from frozen primitives")
    return _profile_from_spec(spec)


def public_full_comparison_profile(profile: FullComparisonProfile) -> dict[str, object]:
    """Return a fresh JSON-safe profile after exact primitive revalidation."""

    trusted = frozen_full_comparison_profile(profile)
    policy = trusted.answer_token_budget_policy
    return {
        "profile_id": trusted.profile_id,
        "benchmark": trusted.benchmark,
        "expected_dataset_hash": trusted.expected_dataset_hash,
        "expected_case_count": trusted.expected_case_count,
        "expected_distribution": dict(trusted.expected_distribution),
        "distribution_field": trusted.distribution_field,
        "retrieval_top_k": trusted.retrieval_top_k,
        "answer_cutoff": trusted.answer_cutoff,
        "answer_token_budget_policy": {
            "policy_id": policy.policy_id,
            "published_mem0_mean_tokens_reference": policy.published_mem0_mean_tokens_reference,
            "max_infinity_to_mem0_mean_prompt_token_ratio": (
                policy.max_infinity_to_mem0_mean_prompt_token_ratio
            ),
            "max_infinity_to_mem0_p95_prompt_token_ratio": (
                policy.max_infinity_to_mem0_p95_prompt_token_ratio
            ),
            "max_infinity_to_mem0_per_case_prompt_token_ratio": (
                policy.max_infinity_to_mem0_per_case_prompt_token_ratio
            ),
        },
        "required_mem0_runtime_mode": trusted.required_mem0_runtime_mode,
        "expected_corpus_count": trusted.expected_corpus_count,
        "required_locomo_ingest_mode": trusted.required_locomo_ingest_mode,
    }


def select_full_comparison_profile_cases(
    *,
    profile: FullComparisonProfile,
    cases: Sequence[PublicBenchmarkCase],
) -> tuple[PublicBenchmarkCase, ...]:
    trusted = frozen_full_comparison_profile(profile)
    if type(cases) not in {tuple, list} or any(
        type(case) is not PublicBenchmarkCase for case in cases
    ):
        raise BenchmarkValidationError("cases must contain exact PublicBenchmarkCase values")
    return tuple(
        case
        for case in cases
        if case.benchmark == trusted.benchmark
        and not (
            trusted.benchmark == "locomo" and _exact_category(case.metadata.get("category")) == 5
        )
    )


def resolve_retrieval_and_answer_cutoff(
    *,
    profile: FullComparisonProfile | None,
    legacy_top_k: int,
    retrieval_top_k: int | None,
    answer_cutoff: int | None,
    legacy_cutoffs: Sequence[int],
) -> tuple[int, int, tuple[int, ...]]:
    if profile is not None:
        trusted = frozen_full_comparison_profile(profile)
        if retrieval_top_k is not None and (
            type(retrieval_top_k) is not int or retrieval_top_k != trusted.retrieval_top_k
        ):
            raise BenchmarkValidationError(
                "retrieval_top_k conflicts with the frozen full comparison profile"
            )
        if answer_cutoff is not None and (
            type(answer_cutoff) is not int or answer_cutoff != trusted.answer_cutoff
        ):
            raise BenchmarkValidationError(
                "answer_cutoff conflicts with the frozen full comparison profile"
            )
        return trusted.retrieval_top_k, trusted.answer_cutoff, (trusted.answer_cutoff,)

    resolved_retrieval = _positive_int(
        legacy_top_k if retrieval_top_k is None else retrieval_top_k,
        name="retrieval_top_k",
    )
    resolved_answer = _positive_int(
        legacy_top_k if answer_cutoff is None else answer_cutoff,
        name="answer_cutoff",
    )
    if resolved_answer > resolved_retrieval:
        raise BenchmarkValidationError("answer_cutoff cannot exceed retrieval_top_k")
    if type(legacy_cutoffs) not in {tuple, list}:
        raise BenchmarkValidationError("top_k_cutoffs must be an exact list or tuple")
    cutoffs = tuple(
        sorted(
            {_positive_int(item, name="top_k_cutoffs") for item in legacy_cutoffs}
            | {resolved_answer}
        )
    )
    if any(item > resolved_retrieval for item in cutoffs):
        raise BenchmarkValidationError("top_k_cutoffs cannot exceed retrieval_top_k")
    return resolved_retrieval, resolved_answer, cutoffs


def _profile_from_spec(spec: _ProfileSpec) -> FullComparisonProfile:
    return FullComparisonProfile(
        profile_id=spec.profile_id,
        benchmark=spec.benchmark,
        expected_dataset_hash=spec.expected_dataset_hash,
        expected_case_count=spec.expected_case_count,
        expected_distribution=MappingProxyType(dict(spec.expected_distribution)),
        distribution_field=spec.distribution_field,
        retrieval_top_k=200,
        answer_cutoff=spec.answer_cutoff,
        answer_token_budget_policy=AnswerTokenBudgetPolicy(
            published_mem0_mean_tokens_reference=spec.token_reference,
        ),
        required_mem0_runtime_mode="managed_platform",
        expected_corpus_count=spec.expected_corpus_count,
        required_locomo_ingest_mode=spec.required_locomo_ingest_mode,
    )


def _profile_matches_spec(profile: FullComparisonProfile, spec: _ProfileSpec) -> bool:
    policy = profile.answer_token_budget_policy
    return bool(
        _exact_string(profile.profile_id) == spec.profile_id
        and _exact_string(profile.benchmark) == spec.benchmark
        and _exact_string(profile.expected_dataset_hash) == spec.expected_dataset_hash
        and type(profile.expected_case_count) is int
        and profile.expected_case_count == spec.expected_case_count
        and _exact_distribution(profile.expected_distribution) == spec.expected_distribution
        and _exact_string(profile.distribution_field) == spec.distribution_field
        and type(profile.retrieval_top_k) is int
        and profile.retrieval_top_k == 200
        and type(profile.answer_cutoff) is int
        and profile.answer_cutoff == spec.answer_cutoff
        and type(policy) is AnswerTokenBudgetPolicy
        and type(policy.published_mem0_mean_tokens_reference) is int
        and policy.published_mem0_mean_tokens_reference == spec.token_reference
        and type(policy.max_infinity_to_mem0_mean_prompt_token_ratio) is float
        and policy.max_infinity_to_mem0_mean_prompt_token_ratio == 1.0
        and type(policy.max_infinity_to_mem0_p95_prompt_token_ratio) is float
        and policy.max_infinity_to_mem0_p95_prompt_token_ratio == 1.0
        and type(policy.max_infinity_to_mem0_per_case_prompt_token_ratio) is float
        and policy.max_infinity_to_mem0_per_case_prompt_token_ratio == 1.0
        and _exact_string(policy.policy_id) == TOKEN_BUDGET_POLICY_ID
        and _exact_string(profile.required_mem0_runtime_mode) == "managed_platform"
        and _exact_optional_positive_int(profile.expected_corpus_count)
        == spec.expected_corpus_count
        and _exact_optional_string(profile.required_locomo_ingest_mode)
        == spec.required_locomo_ingest_mode
    )


def _spec_for_id(profile_id: str | None) -> _ProfileSpec | None:
    return next((spec for spec in _PROFILE_SPECS if spec.profile_id == profile_id), None)


def _exact_distribution(value: object) -> tuple[tuple[str, int], ...] | None:
    if type(value) is not MappingProxyType:
        return None
    items = tuple(value.items())
    if any(type(key) is not str or type(count) is not int for key, count in items):
        return None
    return items


def _exact_string(value: object) -> str | None:
    return value if type(value) is str and value and value == value.strip() else None


def _exact_optional_string(value: object) -> str | None:
    return None if value is None else _exact_string(value)


def _exact_optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    return value if type(value) is int and value > 0 else -1


def _positive_int(value: object, *, name: str) -> int:
    if type(value) is not int or value < 1:
        raise BenchmarkValidationError(f"{name} must contain positive exact integers")
    return value


def _exact_category(value: object) -> int | None:
    return value if type(value) is int else None


__all__ = (
    "FULL_COMPARISON_PROFILES",
    "INFINITY_COMPARISON_BACKEND",
    "INFINITY_PROMPT_POLICY",
    "LOCOMO_OFFICIAL_DATASET_SHA256",
    "LONGMEMEVAL_OFFICIAL_DATASET_SHA256",
    "MEM0_BENCHMARK_UPSTREAM_COMMIT",
    "MEM0_OFFICIAL_MODEL",
    "MEM0_OFFICIAL_PROMPT_FILE_SHA256",
    "MEM0_OFFICIAL_PROMPT_POLICY",
    "PROFILE_LOCOMO_TOP_50",
    "PROFILE_LOCOMO_TOP_200",
    "PROFILE_LONGMEMEVAL_TOP_50",
    "PROFILE_LONGMEMEVAL_TOP_200",
    "REQUIRED_FULL_COMPARISON_BACKENDS",
    "FullComparisonProfile",
    "frozen_full_comparison_profile",
    "public_full_comparison_profile",
    "resolve_full_comparison_profile",
    "resolve_retrieval_and_answer_cutoff",
    "select_full_comparison_profile_cases",
)
