"""Provider token and latency telemetry for memory comparison contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite

_MAX_PROVIDER_TOKEN_COUNT = 1_000_000_000
_MAX_PROVIDER_LATENCY_MS = 86_400_000.0
_FROZEN_ANSWER_CUTOFF = 50


def _token_latency_telemetry(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    input_valid = _is_sequence(evaluations)
    evaluation_values = _sequence_values(evaluations)
    invalid_evaluation_count = sum(not isinstance(item, Mapping) for item in evaluation_values)
    primary_stages = _present_stages(evaluation_values)
    all_cutoff_items = tuple(
        result
        for item in evaluation_values
        for result in _mapping(_mapping(item).get("cutoff_results")).values()
        if isinstance(result, Mapping)
    )
    all_stages = _present_stages(all_cutoff_items)
    primary_totals = _stage_totals(primary_stages)
    all_cutoff_totals = _stage_totals(all_stages)
    return {
        "scope": "answerer_and_judge_provider_calls_only",
        "publishable": False,
        "publication_status": "pending_composite_wiring",
        "publication_blockers": [
            "retrieval_completeness_not_composed",
            "session_isolation_not_composed",
        ],
        "primary_cutoff": _FROZEN_ANSWER_CUTOFF,
        "input_valid": input_valid,
        "invalid_evaluation_count": invalid_evaluation_count,
        "primary": primary_totals,
        "actual_all_cutoffs": all_cutoff_totals,
        "multi_cutoff_overhead": {
            "provider_call_count": min(
                _MAX_PROVIDER_TOKEN_COUNT,
                max(len(all_stages) - len(primary_stages), 0),
            ),
            "tokens": max(
                int(all_cutoff_totals["total_tokens"]) - int(primary_totals["total_tokens"]),
                0,
            ),
            "latency_ms": round(
                max(
                    float(all_cutoff_totals["latency_ms"]) - float(primary_totals["latency_ms"]),
                    0.0,
                ),
                4,
            ),
        },
    }


def _stage_totals(stages: Sequence[Mapping[str, object]]) -> dict[str, object]:
    stage_values = tuple(stage for stage in _sequence_values(stages) if isinstance(stage, Mapping))
    prompt = min(
        _MAX_PROVIDER_TOKEN_COUNT,
        sum(
            _int_value(_mapping(stage.get("token_usage")).get("prompt_tokens"))
            for stage in stage_values
        ),
    )
    completion = min(
        _MAX_PROVIDER_TOKEN_COUNT,
        sum(
            _int_value(_mapping(stage.get("token_usage")).get("completion_tokens"))
            for stage in stage_values
        ),
    )
    return {
        "provider_call_count": min(len(stage_values), _MAX_PROVIDER_TOKEN_COUNT),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": min(_MAX_PROVIDER_TOKEN_COUNT, prompt + completion),
        "latency_ms": round(
            min(
                _MAX_PROVIDER_LATENCY_MS,
                sum(_float_value(stage.get("latency_ms")) for stage in stage_values),
            ),
            4,
        ),
    }


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return min(value, _MAX_PROVIDER_TOKEN_COUNT)


def _float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    if isinstance(value, int):
        return float(min(int(_MAX_PROVIDER_LATENCY_MS), max(0, value)))
    number = float(value)
    if not isfinite(number) or number < 0:
        return 0.0
    return min(number, _MAX_PROVIDER_LATENCY_MS)


def _present_stages(
    items: Sequence[object],
) -> list[Mapping[str, object]]:
    stages: list[Mapping[str, object]] = []
    for item in items:
        mapped = _mapping(item)
        for name in ("generation", "judgment"):
            value = mapped.get(name)
            if isinstance(value, Mapping) and value:
                stages.append(value)
    return stages


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
