"""Benchmark-neutral dataset dispatch for memory-comparison cases."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

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
        parse_memory_comparison_dataset_bytes(dataset_path.read_bytes()),
        locomo_ingest_mode=locomo_ingest_mode,
    )
    if not cases:
        raise BenchmarkValidationError("Dataset does not contain benchmark cases")
    return cases


def parse_memory_comparison_dataset_bytes(dataset_bytes: bytes) -> object:
    """Parse one exact dataset byte sequence using the canonical JSON/JSONL policy."""

    if type(dataset_bytes) is not bytes:
        raise BenchmarkValidationError("dataset_bytes must be exact bytes")
    try:
        stripped = dataset_bytes.decode("utf-8").strip()
        if not stripped:
            return ()
        try:
            return _strict_json_loads(stripped)
        except (json.JSONDecodeError, _StrictDatasetJsonError):
            return tuple(_strict_json_loads(line) for line in stripped.splitlines() if line.strip())
    except (UnicodeDecodeError, json.JSONDecodeError, _StrictDatasetJsonError) as exc:
        raise BenchmarkValidationError("Dataset must be valid UTF-8 JSON or JSONL") from exc


class _StrictDatasetJsonError(ValueError):
    pass


def _strict_json_loads(value: str) -> object:
    return json.loads(
        value,
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictDatasetJsonError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise _StrictDatasetJsonError(f"non-finite JSON constant: {value}")


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
