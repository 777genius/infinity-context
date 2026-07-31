"""Provider-observed token-budget admission for publishable comparisons."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

TOKEN_BUDGET_POLICY_ID = "same-run-answerer-prompt-parity-v1"
PROVIDER_OBSERVED_USAGE_SOURCE = "provider_observed"
NON_TRUNCATED_FINISH_REASON = "stop"
_INFINITY_BACKEND = "infinity-context"
_MEM0_BACKEND = "mem0"
_BACKENDS = (_INFINITY_BACKEND, _MEM0_BACKEND)
_DIAGNOSTIC_LIMIT = 20
_MAX_TOKEN_COUNT = 1_000_000_000
_MAX_PAIR_COUNT = 1_000_000_000
_MAX_POLICY_RATIO = 1_000.0
_MAX_OBSERVED_RATIO = 1_000_000_000.0
_MAX_ID_LENGTH = 512


@dataclass(frozen=True)
class AnswerTokenBudgetPolicy:
    """Frozen fair-budget policy plus a non-comparable published reference."""

    published_mem0_mean_tokens_reference: int
    max_infinity_to_mem0_mean_prompt_token_ratio: float = 1.0
    max_infinity_to_mem0_p95_prompt_token_ratio: float = 1.0
    max_infinity_to_mem0_per_case_prompt_token_ratio: float = 1.0
    policy_id: str = field(default=TOKEN_BUDGET_POLICY_ID, init=False)

    def __post_init__(self) -> None:
        reference = self.published_mem0_mean_tokens_reference
        if type(reference) is not int or not 0 < reference <= _MAX_TOKEN_COUNT:
            raise ValueError("published Mem0 token reference must be a bounded positive integer")
        for name in (
            "max_infinity_to_mem0_mean_prompt_token_ratio",
            "max_infinity_to_mem0_p95_prompt_token_ratio",
            "max_infinity_to_mem0_per_case_prompt_token_ratio",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or value < 0
                or value > _MAX_POLICY_RATIO
                or (isinstance(value, float) and not math.isfinite(value))
            ):
                raise ValueError(f"{name} must be finite, non-negative, and bounded")


@dataclass(frozen=True)
class _Observation:
    backend: str
    benchmark: str
    case_id: str
    prompt_tokens: int | None
    completion_tokens: int | None
    retrieval_context_tokens: int | None
    usage_source: str
    finish_reason: str
    finish_reason_source: str
    token_reason: str | None

    @property
    def identity(self) -> tuple[str, str]:
        return self.benchmark, self.case_id

    @property
    def token_usage_valid(self) -> bool:
        return self.token_reason is None

    @property
    def usage_source_valid(self) -> bool:
        return self.usage_source == PROVIDER_OBSERVED_USAGE_SOURCE

    @property
    def finish_reason_valid(self) -> bool:
        return (
            self.finish_reason == NON_TRUNCATED_FINISH_REASON
            and self.finish_reason_source == PROVIDER_OBSERVED_USAGE_SOURCE
        )


def answer_token_budget_contract(
    evaluations: Sequence[Mapping[str, object]],
    *,
    expected_pair_count: int,
    policy: AnswerTokenBudgetPolicy,
) -> dict[str, object]:
    """Return a fail-closed same-run paired answerer token contract."""

    grouped: dict[str, dict[tuple[str, str], list[_Observation]]] = {
        backend: {} for backend in _BACKENDS
    }
    token_reasons: Counter[str] = Counter()
    source_reasons: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    invalid_token_samples: list[dict[str, object]] = []
    invalid_source_samples: list[dict[str, object]] = []
    invalid_finish_samples: list[dict[str, object]] = []
    judge_reasons: Counter[str] = Counter()
    invalid_judge_samples: list[dict[str, object]] = []
    unsupported_backend_count = 0
    invalid_identity_count = 0
    unscored_evaluation_count = 0
    evaluation_input_valid = _is_sequence(evaluations)
    evaluation_values = _sequence_values(evaluations)
    invalid_evaluation_count = 0
    scored_status_reasons: Counter[str] = Counter()
    for raw_item in evaluation_values:
        if not isinstance(raw_item, Mapping):
            invalid_evaluation_count += 1
            continue
        item = raw_item
        if item.get("scored") is not True:
            unscored_evaluation_count += 1
            if "scored" not in item:
                scored_status_reasons["missing"] += 1
            elif item.get("scored") is False:
                scored_status_reasons["false"] += 1
            else:
                scored_status_reasons["invalid"] += 1
            continue
        backend = _exact_id(item.get("backend")) or ""
        if backend not in grouped:
            unsupported_backend_count += 1
            continue
        observation = _observation(item, backend=backend)
        if not observation.benchmark or not observation.case_id:
            invalid_identity_count += 1
            continue
        for reason in _provider_call_integrity_issues(item, stage="judgment"):
            judge_reasons[reason] += 1
            _append_sample(
                invalid_judge_samples,
                {
                    **_sample_identity(observation),
                    "reason": reason,
                },
            )
        grouped[backend].setdefault(observation.identity, []).append(observation)
        sample_identity = _sample_identity(observation)
        if observation.token_reason is not None:
            token_reasons[observation.token_reason] += 1
            _append_sample(
                invalid_token_samples,
                {**sample_identity, "reason": observation.token_reason},
            )
        if not observation.usage_source_valid:
            reason = "missing" if not observation.usage_source else "not_provider_observed"
            source_reasons[reason] += 1
            _append_sample(
                invalid_source_samples,
                {**sample_identity, "reason": reason},
            )
        if not observation.finish_reason_valid:
            reason = (
                "untrusted_source"
                if observation.finish_reason == NON_TRUNCATED_FINISH_REASON
                and observation.finish_reason_source != PROVIDER_OBSERVED_USAGE_SOURCE
                else _finish_reason_issue(observation.finish_reason)
            )
            finish_reasons[reason] += 1
            _append_sample(
                invalid_finish_samples,
                {**sample_identity, "reason": reason},
            )

    identities = tuple(sorted(set(grouped[_INFINITY_BACKEND]) | set(grouped[_MEM0_BACKEND])))
    expected = _positive_int(expected_pair_count)
    duplicate_pair_count = sum(
        len(items) > 1 for backend in _BACKENDS for items in grouped[backend].values()
    )
    missing_pair_count = sum(
        identity not in grouped[_INFINITY_BACKEND] or identity not in grouped[_MEM0_BACKEND]
        for identity in identities
    )
    missing_pair_count += max(0, expected - len(identities))
    unexpected_pair_count = max(0, len(identities) - expected) if expected else 0

    prompt_tokens: dict[str, list[int]] = {backend: [] for backend in _BACKENDS}
    retrieval_context_tokens: dict[str, list[int]] = {backend: [] for backend in _BACKENDS}
    retrieval_context_missing: Counter[str] = Counter()
    per_case_violations: list[dict[str, object]] = []
    paired_case_count = 0
    for identity in identities:
        infinity_items = grouped[_INFINITY_BACKEND].get(identity, ())
        mem0_items = grouped[_MEM0_BACKEND].get(identity, ())
        if len(infinity_items) != 1 or len(mem0_items) != 1:
            continue
        paired_case_count += 1
        infinity = infinity_items[0]
        mem0 = mem0_items[0]
        for observation in (infinity, mem0):
            if observation.token_usage_valid and observation.prompt_tokens is not None:
                prompt_tokens[observation.backend].append(observation.prompt_tokens)
            if observation.retrieval_context_tokens is None:
                retrieval_context_missing[observation.backend] += 1
            else:
                retrieval_context_tokens[observation.backend].append(
                    observation.retrieval_context_tokens
                )
        if (
            infinity.token_usage_valid
            and mem0.token_usage_valid
            and infinity.prompt_tokens is not None
            and mem0.prompt_tokens is not None
            and infinity.prompt_tokens
            > mem0.prompt_tokens * policy.max_infinity_to_mem0_per_case_prompt_token_ratio
        ):
            _append_sample(
                per_case_violations,
                {
                    "benchmark": identity[0],
                    "case_id": identity[1],
                    "infinity_context_prompt_tokens": infinity.prompt_tokens,
                    "mem0_prompt_tokens": mem0.prompt_tokens,
                    "delta": infinity.prompt_tokens - mem0.prompt_tokens,
                },
            )

    answerer_prompt = {backend: _distribution(prompt_tokens[backend]) for backend in _BACKENDS}
    retrieval_context = {
        backend: {
            **_distribution(retrieval_context_tokens[backend]),
            "missing_count": _bounded_count(retrieval_context_missing[backend]),
        }
        for backend in _BACKENDS
    }
    ratios = _answerer_prompt_ratios(answerer_prompt)
    exact_pair_complete = (
        expected > 0
        and paired_case_count == expected
        and len(identities) == expected
        and duplicate_pair_count == 0
        and missing_pair_count == 0
        and unexpected_pair_count == 0
        and invalid_identity_count == 0
        and unsupported_backend_count == 0
        and unscored_evaluation_count == 0
        and invalid_evaluation_count == 0
        and evaluation_input_valid
    )
    usage_complete = all(answerer_prompt[backend]["count"] == expected for backend in _BACKENDS)
    mean_ratio = _optional_float(ratios.get("mean"))
    p95_ratio = _optional_float(ratios.get("p95"))
    aggregate_budget_matches = (
        mean_ratio is not None
        and p95_ratio is not None
        and mean_ratio <= policy.max_infinity_to_mem0_mean_prompt_token_ratio
        and p95_ratio <= policy.max_infinity_to_mem0_p95_prompt_token_ratio
    )
    blockers: list[dict[str, object]] = []
    if not exact_pair_complete:
        blockers.append(
            {
                "code": "incomplete_paired_answerer_token_budget",
                "expected_pair_count": expected,
                "paired_case_count": _bounded_count(paired_case_count),
                "missing_pair_count": _bounded_count(missing_pair_count),
                "duplicate_pair_count": _bounded_count(duplicate_pair_count),
                "unexpected_pair_count": _bounded_count(unexpected_pair_count),
                "invalid_identity_count": _bounded_count(invalid_identity_count),
                "unsupported_backend_evaluation_count": _bounded_count(unsupported_backend_count),
                "unscored_evaluation_count": _bounded_count(unscored_evaluation_count),
                "invalid_evaluation_count": _bounded_count(invalid_evaluation_count),
                "evaluation_input_valid": evaluation_input_valid,
                "scored_status_reason_counts": {
                    key: _bounded_count(value)
                    for key, value in sorted(scored_status_reasons.items())
                },
            }
        )
    if token_reasons or not usage_complete:
        blockers.append(
            {
                "code": "invalid_answerer_token_usage",
                **_bounded_diagnostics(token_reasons, invalid_token_samples),
                "complete": usage_complete,
            }
        )
    if source_reasons:
        blockers.append(
            {
                "code": "untrusted_answerer_token_usage_source",
                **_bounded_diagnostics(source_reasons, invalid_source_samples),
            }
        )
    if finish_reasons:
        blockers.append(
            {
                "code": "truncated_or_unverified_answerer_completion",
                **_bounded_diagnostics(finish_reasons, invalid_finish_samples),
            }
        )
    if judge_reasons:
        blockers.append(
            {
                "code": "invalid_judge_provider_call_integrity",
                **_bounded_diagnostics(judge_reasons, invalid_judge_samples),
            }
        )
    per_case_violation_count = sum(
        1
        for identity in identities
        if _per_case_budget_exceeded(grouped, identity=identity, policy=policy)
    )
    if per_case_violation_count or (usage_complete and not aggregate_budget_matches):
        bounded_per_case_samples = _sorted_bounded_samples(per_case_violations)
        blockers.append(
            {
                "code": "answerer_prompt_token_budget_exceeded",
                "per_case_violation_count": _bounded_count(per_case_violation_count),
                "per_case_violation_samples": bounded_per_case_samples,
                "per_case_violation_samples_truncated": _bounded_count(
                    max(0, per_case_violation_count - len(bounded_per_case_samples))
                ),
                "observed_infinity_to_mem0_ratios": ratios,
                "max_mean_ratio": (policy.max_infinity_to_mem0_mean_prompt_token_ratio),
                "max_p95_ratio": (policy.max_infinity_to_mem0_p95_prompt_token_ratio),
                "max_per_case_ratio": (policy.max_infinity_to_mem0_per_case_prompt_token_ratio),
            }
        )

    return {
        "schema_version": "memory-comparison-token-budget.v1",
        "policy": token_budget_methodology_contract(policy),
        "status": "eligible" if not blockers else "blocked",
        "matches": not blockers,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "expected_pair_count": expected,
        "evaluation_input_valid": evaluation_input_valid,
        "invalid_evaluation_count": _bounded_count(invalid_evaluation_count),
        "paired_case_count": _bounded_count(paired_case_count),
        "answerer_prompt_tokens": answerer_prompt,
        "retrieval_context_tokens": retrieval_context,
        "invalid_scored_status": {
            "count": _bounded_count(unscored_evaluation_count),
            "reason_counts": {
                key: _bounded_count(value) for key, value in sorted(scored_status_reasons.items())
            },
        },
        "infinity_to_mem0_answerer_prompt_token_ratios": ratios,
        "per_case_budget_violation_count": _bounded_count(per_case_violation_count),
        "per_case_budget_violation_samples": _sorted_bounded_samples(per_case_violations),
        "invalid_answerer_token_usage": _bounded_diagnostics(
            token_reasons,
            invalid_token_samples,
        ),
        "untrusted_answerer_token_usage_source": _bounded_diagnostics(
            source_reasons,
            invalid_source_samples,
        ),
        "truncated_or_unverified_answerer_completion": _bounded_diagnostics(
            finish_reasons,
            invalid_finish_samples,
        ),
        "invalid_judge_provider_call_integrity": _bounded_diagnostics(
            judge_reasons,
            invalid_judge_samples,
        ),
        "blockers": blockers,
    }


def token_budget_methodology_contract(
    policy: AnswerTokenBudgetPolicy,
) -> dict[str, object]:
    """Return the frozen metric and honest published-reference semantics."""

    return {
        "policy_id": policy.policy_id,
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "primary_budget_metric": "provider_observed_answerer_prompt_tokens",
        "percentile_method": "nearest_rank",
        "same_run_required_backends": list(_BACKENDS),
        "same_run_max_infinity_to_mem0_mean_ratio": (
            policy.max_infinity_to_mem0_mean_prompt_token_ratio
        ),
        "same_run_max_infinity_to_mem0_p95_ratio": (
            policy.max_infinity_to_mem0_p95_prompt_token_ratio
        ),
        "same_run_max_infinity_to_mem0_per_case_ratio": (
            policy.max_infinity_to_mem0_per_case_prompt_token_ratio
        ),
        "requires_provider_observed_usage": True,
        "requires_provider_observed_finish_reason": True,
        "requires_judge_provider_call_integrity": {
            "positive_exact_token_counts": True,
            "token_usage_source": PROVIDER_OBSERVED_USAGE_SOURCE,
            "finish_reason": NON_TRUNCATED_FINISH_REASON,
            "finish_reason_source": PROVIDER_OBSERVED_USAGE_SOURCE,
        },
        "requires_finish_reason": NON_TRUNCATED_FINISH_REASON,
        "published_mem0_reference": {
            "mean_tokens": policy.published_mem0_mean_tokens_reference,
            "reported_metric": "mean_tokens_per_retrieval_call",
            "source": "https://docs.mem0.ai/core-concepts/memory-evaluation",
            "comparison_role": "reference_only",
            "comparable_to_primary_budget_metric": False,
            "reason": (
                "The pinned upstream harness declares prompt-token fields but its "
                "answer path does not capture provider usage; the later published "
                "retrieval-call mean therefore cannot be mapped exactly."
            ),
        },
    }


def _observation(
    item: Mapping[str, object],
    *,
    backend: str,
) -> _Observation:
    generation = _mapping(item.get("generation"))
    usage = _mapping(generation.get("token_usage"))
    metadata = _mapping(generation.get("metadata"))
    prompt_tokens, prompt_reason = _positive_token_count(
        usage.get("prompt_tokens"),
        label="prompt",
    )
    completion_tokens, completion_reason = _positive_token_count(
        usage.get("completion_tokens"),
        label="completion",
    )
    retrieval = _mapping(item.get("retrieval"))
    return _Observation(
        backend=backend,
        benchmark=_exact_id(item.get("benchmark")) or "",
        case_id=_exact_id(item.get("case_id")) or "",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        retrieval_context_tokens=_nonnegative_token_count(retrieval.get("context_token_count")),
        usage_source=str(metadata.get("token_usage_source") or "").strip().casefold(),
        finish_reason=str(metadata.get("finish_reason") or "").strip().casefold(),
        finish_reason_source=str(metadata.get("finish_reason_source") or "").strip().casefold(),
        token_reason=prompt_reason or completion_reason,
    )


def _provider_call_integrity_issues(
    item: Mapping[str, object],
    *,
    stage: str,
) -> tuple[str, ...]:
    payload = _mapping(item.get(stage))
    usage = _mapping(payload.get("token_usage"))
    metadata = _mapping(payload.get("metadata"))
    issues: list[str] = []
    for label in ("prompt", "completion"):
        _, reason = _positive_token_count(
            usage.get(f"{label}_tokens"),
            label=label,
        )
        if reason is not None:
            issues.append(reason)
    usage_source = str(metadata.get("token_usage_source") or "").strip().casefold()
    if usage_source != PROVIDER_OBSERVED_USAGE_SOURCE:
        issues.append("untrusted_usage_source")
    finish_reason = str(metadata.get("finish_reason") or "").strip().casefold()
    if finish_reason != NON_TRUNCATED_FINISH_REASON:
        issues.append(f"finish_reason_{_finish_reason_issue(finish_reason)}")
    finish_source = str(metadata.get("finish_reason_source") or "").strip().casefold()
    if finish_source != PROVIDER_OBSERVED_USAGE_SOURCE:
        issues.append("untrusted_finish_reason_source")
    return tuple(issues)


def _positive_token_count(
    value: object,
    *,
    label: str,
) -> tuple[int | None, str | None]:
    if value is None:
        return None, f"missing_{label}_tokens"
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"invalid_{label}_tokens"
    if value <= 0:
        return None, f"non_positive_{label}_tokens"
    if value > _MAX_TOKEN_COUNT:
        return None, f"excessive_{label}_tokens"
    return value, None


def _nonnegative_token_count(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_TOKEN_COUNT
    ):
        return None
    return value


def _distribution(values: Sequence[int]) -> dict[str, object]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "count": _bounded_count(len(ordered)),
        "mean": round(sum(ordered) / len(ordered), 4),
        "p50": _nearest_rank(ordered, 0.50),
        "p95": _nearest_rank(ordered, 0.95),
        "max": ordered[-1],
    }


def _nearest_rank(ordered: Sequence[int], probability: float) -> int:
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def _answerer_prompt_ratios(
    distributions: Mapping[str, Mapping[str, object]],
) -> dict[str, float | None]:
    infinity = distributions[_INFINITY_BACKEND]
    mem0 = distributions[_MEM0_BACKEND]
    return {
        metric: _safe_ratio(infinity.get(metric), mem0.get(metric))
        for metric in ("mean", "p50", "p95", "max")
    }


def _safe_ratio(numerator: object, denominator: object) -> float | None:
    if not isinstance(numerator, int | float) or isinstance(numerator, bool):
        return None
    if not isinstance(denominator, int | float) or isinstance(denominator, bool):
        return None
    if denominator <= 0:
        return None
    return round(min(_MAX_OBSERVED_RATIO, float(numerator) / float(denominator)), 6)


def _per_case_budget_exceeded(
    grouped: Mapping[str, Mapping[tuple[str, str], Sequence[_Observation]]],
    *,
    identity: tuple[str, str],
    policy: AnswerTokenBudgetPolicy,
) -> bool:
    infinity_items = grouped[_INFINITY_BACKEND].get(identity, ())
    mem0_items = grouped[_MEM0_BACKEND].get(identity, ())
    if len(infinity_items) != 1 or len(mem0_items) != 1:
        return False
    infinity = infinity_items[0]
    mem0 = mem0_items[0]
    return bool(
        infinity.token_usage_valid
        and mem0.token_usage_valid
        and infinity.prompt_tokens is not None
        and mem0.prompt_tokens is not None
        and infinity.prompt_tokens
        > mem0.prompt_tokens * policy.max_infinity_to_mem0_per_case_prompt_token_ratio
    )


def _finish_reason_issue(value: str) -> str:
    if not value:
        return "missing"
    if value == "length":
        return "length"
    if value == "content_filter":
        return "content_filter"
    return "unsupported"


def _sample_identity(observation: _Observation) -> dict[str, object]:
    return {
        "backend": observation.backend,
        "benchmark": observation.benchmark,
        "case_id": observation.case_id,
    }


def _append_sample(samples: list[dict[str, object]], sample: dict[str, object]) -> None:
    samples.append(sample)


def _bounded_diagnostics(
    reasons: Mapping[str, int],
    samples: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    raw_count = sum(reasons.values())
    count = _bounded_count(raw_count)
    bounded_samples = _sorted_bounded_samples(samples)
    return {
        "count": count,
        "reason_counts": {key: _bounded_count(value) for key, value in sorted(reasons.items())},
        "sample_limit": _DIAGNOSTIC_LIMIT,
        "samples": bounded_samples,
        "truncated_count": _bounded_count(max(0, raw_count - len(bounded_samples))),
    }


def _sorted_bounded_samples(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ordered = sorted(
        (dict(item) for item in samples),
        key=lambda item: json.dumps(
            item,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    return ordered[:_DIAGNOSTIC_LIMIT]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _is_sequence(value: object) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, Sequence)
        and not isinstance(value, str | bytes | bytearray)
    )


def _sequence_values(value: object) -> tuple[object, ...]:
    return tuple(value) if _is_sequence(value) else ()  # type: ignore[arg-type]


def _exact_id(value: object) -> str | None:
    if type(value) is not str or not value or len(value) > _MAX_ID_LENGTH or value != value.strip():
        return None
    return value


def _positive_int(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAX_PAIR_COUNT
    ):
        return 0
    return value


def _bounded_count(value: int) -> int:
    return min(_MAX_PAIR_COUNT, max(0, value))


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
