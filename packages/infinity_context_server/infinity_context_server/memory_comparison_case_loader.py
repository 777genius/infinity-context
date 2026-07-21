"""Benchmark-neutral dataset dispatch for memory-comparison cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    LOCOMO_INGEST_RICH_DOCUMENTS,
    _official_locomo_turn_cases_from_payload,
)
from infinity_context_server.memory_comparison_longmemeval_cases import (
    official_longmemeval_pair_case,
)
from infinity_context_server.public_benchmark import (
    _cases_from_payload,
    _is_official_locomo_sample,
    _is_official_longmemeval_row,
    _load_dataset_payload,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)


def load_memory_comparison_cases(
    dataset_path: Path,
    *,
    locomo_ingest_mode: str,
) -> tuple[PublicBenchmarkCase, ...]:
    if locomo_ingest_mode not in {
        LOCOMO_INGEST_RICH_DOCUMENTS,
        LOCOMO_INGEST_OFFICIAL_TURNS,
    }:
        raise BenchmarkValidationError(f"Unsupported LoCoMo ingest mode: {locomo_ingest_mode}")
    if not dataset_path.exists():
        raise BenchmarkValidationError(f"Dataset does not exist: {dataset_path}")
    cases = cases_from_payload(
        _load_dataset_payload(dataset_path),
        locomo_ingest_mode=locomo_ingest_mode,
    )
    if not cases:
        raise BenchmarkValidationError("Dataset does not contain benchmark cases")
    return cases


def cases_from_payload(
    payload: object,
    *,
    locomo_ingest_mode: str,
) -> tuple[PublicBenchmarkCase, ...]:
    if isinstance(payload, Mapping):
        if _is_official_longmemeval_row(payload):
            return (official_longmemeval_pair_case(payload),)
        if _is_official_locomo_sample(payload):
            if locomo_ingest_mode == LOCOMO_INGEST_OFFICIAL_TURNS:
                return _official_locomo_turn_cases_from_payload(payload)
            return _cases_from_payload(payload)
        nested = payload.get("cases") or payload.get("data") or payload.get("items")
        if nested is not None:
            return cases_from_payload(
                nested,
                locomo_ingest_mode=locomo_ingest_mode,
            )
        return _cases_from_payload(payload)

    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        cases: list[PublicBenchmarkCase] = []
        for item in payload:
            if isinstance(item, Mapping):
                cases.extend(cases_from_payload(item, locomo_ingest_mode=locomo_ingest_mode))
        return tuple(cases)
    raise BenchmarkValidationError("Dataset root must be a case list, object or JSONL")


# Compatibility names for existing internal imports.
_load_memory_comparison_cases = load_memory_comparison_cases
_memory_comparison_cases_from_payload = cases_from_payload
