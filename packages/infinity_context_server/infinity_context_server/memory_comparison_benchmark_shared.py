"""Shared low-level helpers for memory comparison benchmark modules."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_llm import approximate_token_count
from infinity_context_server.memory_comparison_models import (
    MemoryComparisonBackendPort,
    TokenCostRate,
    TokenUsage,
    token_cost_payload,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError


def _numeric_summary(values: Iterable[float]) -> dict[str, object]:
    sequence = [float(value) for value in values]
    if not sequence:
        return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(sequence),
        "avg": round(sum(sequence) / len(sequence), 4),
        "min": round(min(sequence), 4),
        "max": round(max(sequence), 4),
    }



def _normalize_top_k_cutoffs(*, top_k: int, values: Sequence[int]) -> tuple[int, ...]:
    if isinstance(top_k, bool) or top_k < 1:
        raise BenchmarkValidationError("top_k must be greater than zero")
    normalized = {top_k}
    for raw in values:
        value = int(raw)
        if value < 1:
            raise BenchmarkValidationError("top_k_cutoffs must be greater than zero")
        if value > top_k:
            raise BenchmarkValidationError("top_k_cutoffs cannot exceed top_k")
        normalized.add(value)
    return tuple(sorted(normalized))


def _unique_backend_names(backends: Sequence[MemoryComparisonBackendPort]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for index, backend in enumerate(backends, start=1):
        name = str(backend.name).strip()
        if not name:
            raise BenchmarkValidationError(
                f"comparison backend at position {index} must have a non-empty name"
            )
        if name in seen:
            duplicates.add(name)
        seen.add(name)
        names.append(name)
    if duplicates:
        duplicate_names = ", ".join(sorted(duplicates))
        raise BenchmarkValidationError(
            f"comparison backend names must be unique: {duplicate_names}"
        )
    return tuple(names)


def _evaluation_score(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("judgment")).get("score", 0.0))


def _retrieved_count(item: Mapping[str, object]) -> float:
    retrieval = _mapping(item.get("retrieval"))
    return float(retrieval.get("total_results", 0.0))


def _search_latency(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval")).get("latency_ms", 0.0))


def _ingest_latency(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("ingestion")).get("latency_ms", 0.0))


def _stage_latency(item: Mapping[str, object], stage: str) -> float:
    return float(_mapping(item.get(stage)).get("latency_ms", 0.0))


def _context_tokens(item: Mapping[str, object]) -> float:
    retrieval = _mapping(item.get("retrieval"))
    value = retrieval.get("context_token_count")
    if isinstance(value, int | float):
        return float(value)
    memories = retrieval.get("results")
    if not isinstance(memories, list):
        return 0.0
    return float(
        sum(
            approximate_token_count(str(_mapping(memory).get("memory", "")))
            for memory in memories
        )
    )


def _retrieval_recall(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval_quality")).get("expected_term_recall", 0.0))


def _has_evidence_recall(item: Mapping[str, object]) -> bool:
    return "evidence_term_recall" in _mapping(item.get("retrieval_quality"))


def _evidence_recall(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval_quality")).get("evidence_term_recall", 0.0))


def _metric_delta(
    left: Mapping[str, object],
    right: Mapping[str, object],
    key: str,
) -> float:
    return round(_metric_value(left, key) - _metric_value(right, key), 4)


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _nested_float(item: Mapping[str, object], *keys: str) -> float:
    current: object = item
    for key in keys:
        current = _mapping(current).get(key)
    if isinstance(current, bool):
        return 0.0
    try:
        return float(current)
    except (TypeError, ValueError):
        return 0.0


def _token_usage_summary(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    answerer = _stage_token_usage_summary(items, "generation")
    judge = _stage_token_usage_summary(items, "judgment")
    prompt_tokens = answerer.prompt_tokens + judge.prompt_tokens
    completion_tokens = answerer.completion_tokens + judge.completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "by_stage": {
            "answerer": {
                "prompt_tokens": answerer.prompt_tokens,
                "completion_tokens": answerer.completion_tokens,
                "total_tokens": answerer.total_tokens,
            },
            "judge": {
                "prompt_tokens": judge.prompt_tokens,
                "completion_tokens": judge.completion_tokens,
                "total_tokens": judge.total_tokens,
            },
        },
    }


def _token_cost_summary(
    items: Sequence[Mapping[str, object]],
    *,
    answerer_token_cost_rate: TokenCostRate,
    judge_token_cost_rate: TokenCostRate,
) -> dict[str, object]:
    answerer_usage = _stage_token_usage_summary(items, "generation")
    judge_usage = _stage_token_usage_summary(items, "judgment")
    answerer_cost = token_cost_payload(answerer_usage, answerer_token_cost_rate)
    judge_cost = token_cost_payload(judge_usage, judge_token_cost_rate)
    return {
        "configured": (
            answerer_token_cost_rate.is_configured
            or judge_token_cost_rate.is_configured
        ),
        "scope": "answerer_judge_only",
        "unmeasured_backend_provider_costs": True,
        "currency": "USD",
        "answerer": answerer_cost,
        "judge": judge_cost,
        "total_usd": round(
            float(answerer_cost["total_usd"]) + float(judge_cost["total_usd"]),
            8,
        ),
    }


def _stage_token_usage_summary(
    items: Sequence[Mapping[str, object]],
    stage: str,
) -> TokenUsage:
    prompt_tokens = 0
    completion_tokens = 0
    for item in items:
        usage = _mapping(_mapping(item.get(stage)).get("token_usage"))
        prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens += int(usage.get("completion_tokens", 0) or 0)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _group_by(
    items: Sequence[Mapping[str, object]],
    *,
    key: str,
) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get(key) or "unknown")].append(item)
    return grouped


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: Sequence[float] | object) -> float:
    sequence = tuple(float(value) for value in values)  # type: ignore[arg-type]
    return round(sum(sequence) / len(sequence), 4) if sequence else 0.0


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, Sequence) or isinstance(value, bytes):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_ints(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(parsed for item in value if (parsed := _positive_int(item)) is not None)


def _float_value(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _safe_error_reason(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return redact_sensitive_text(f"{exc.__class__.__name__}: {message}")[:500]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
