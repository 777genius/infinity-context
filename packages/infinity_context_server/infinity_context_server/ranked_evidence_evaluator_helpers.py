"""Narrow evaluator helpers for the ranked-evidence semantic gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite

from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.ranked_evidence_seed_case import RankedEvidenceSeedCase

_EVALUATOR_ONLY_SCHEMA_VERSION = "memory-comparison-evaluator-only.v1"
_EVALUATOR_GROUND_TRUTH_KEY = "_evaluator_ground_truth"
_MAX_GROUND_TRUTH_DEPTH = 8
_MAX_GROUND_TRUTH_ITEMS = 10_000
_MAX_GROUND_TRUTH_KEY_CHARS = 256
_MAX_GROUND_TRUTH_TEXT_CHARS = 1_000_000
_MAX_INTEGER_DIGITS = 128


def evaluator_only_payload(case: PublicBenchmarkCase) -> dict[str, object]:
    """Project bounded judge-only gold without exposing it to retrieval helpers."""

    if not isinstance(case, PublicBenchmarkCase):
        raise BenchmarkValidationError("Evaluator payload requires a public benchmark case")
    if not isinstance(case.metadata, Mapping):
        raise BenchmarkValidationError("Evaluator metadata must be a mapping")

    ground_truth = case.metadata.get(_EVALUATOR_GROUND_TRUTH_KEY)
    if ground_truth is None:
        ground_truth = case.metadata.get("answer_preview")
    if ground_truth is None:
        if not all(isinstance(term, str) for term in case.expected_terms):
            raise BenchmarkValidationError("Expected terms must contain only strings")
        ground_truth = " | ".join(case.expected_terms)

    return {
        "schema_version": _EVALUATOR_ONLY_SCHEMA_VERSION,
        "ground_truth": _bounded_ground_truth(ground_truth, remaining=[_MAX_GROUND_TRUTH_ITEMS]),
    }


def benchmark_memory_source_id(
    case: PublicBenchmarkCase | RankedEvidenceSeedCase,
    memory: BenchmarkMemoryInput,
    *,
    step: int,
) -> str:
    """Return the canonical source identity while reading no evaluator fields."""

    if not isinstance(case, PublicBenchmarkCase | RankedEvidenceSeedCase):
        raise BenchmarkValidationError("Memory source identity requires a benchmark case DTO")
    if not isinstance(memory, BenchmarkMemoryInput):
        raise BenchmarkValidationError("Memory source identity requires a benchmark memory DTO")
    if not isinstance(step, int) or isinstance(step, bool) or step < 1:
        raise BenchmarkValidationError("Memory source identity step must be a positive integer")
    source_external_id = memory.source_external_id
    if source_external_id is not None and not isinstance(source_external_id, str):
        raise BenchmarkValidationError("Memory source_external_id must be a string or null")
    if not isinstance(case.case_id, str) or not case.case_id:
        raise BenchmarkValidationError("Benchmark case_id must be a non-empty string")
    return safe_identifier(
        source_external_id or f"{case.case_id}:memory:{step}",
        max_chars=160,
    )


def source_ref_id(ref: object) -> str | None:
    """Read an identifier from the public string-or-mapping source-ref shape."""

    if isinstance(ref, str):
        stripped = ref.strip()
        return stripped or None
    if not isinstance(ref, Mapping):
        return None
    for key in ("source_id", "source_external_id", "id"):
        value = ref.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _bounded_ground_truth(
    value: object,
    *,
    remaining: list[int],
    depth: int = 0,
) -> object:
    if depth > _MAX_GROUND_TRUTH_DEPTH:
        raise BenchmarkValidationError("Evaluator ground truth exceeds maximum depth")
    remaining[0] -= 1
    if remaining[0] < 0:
        raise BenchmarkValidationError("Evaluator ground truth exceeds maximum item count")

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_GROUND_TRUTH_TEXT_CHARS:
            raise BenchmarkValidationError("Evaluator ground truth text is too large")
        return value
    if isinstance(value, int):
        if len(str(abs(value))) > _MAX_INTEGER_DIGITS:
            raise BenchmarkValidationError("Evaluator ground truth integer is too large")
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise BenchmarkValidationError("Evaluator ground truth number must be finite")
        return value
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > _MAX_GROUND_TRUTH_KEY_CHARS:
                raise BenchmarkValidationError(
                    "Evaluator ground truth mapping keys must be bounded strings"
                )
            projected[key] = _bounded_ground_truth(
                item,
                remaining=remaining,
                depth=depth + 1,
            )
        return projected
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_bounded_ground_truth(item, remaining=remaining, depth=depth + 1) for item in value]
    raise BenchmarkValidationError("Evaluator ground truth is not JSON-compatible")


__all__ = (
    "benchmark_memory_source_id",
    "evaluator_only_payload",
    "source_ref_id",
)
