"""Execution manifest helpers for public memory benchmarks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.public_benchmark_case_diagnostics import artifact_text_value

_MAX_LIST_ITEMS = 20
_MAX_STRING_CHARS = 240


def build_execution_manifest(
    *,
    suite: str,
    evaluation_mode: str,
    dataset_path: Path,
    dataset_hash: str,
    selected_case_count: int,
    selected_case_fingerprint: str,
    case_selection: Mapping[str, object] | None,
    requested_case_ids: Sequence[str],
    requested_capabilities: Sequence[str],
    transport_mode: str,
    requested_parallelism: int,
    effective_parallelism: int,
    parallelism_degraded_reason: str | None,
    request_timeout_seconds: float,
    checkpoint_every_cases: int,
    checkpoint_min_interval_seconds: float,
    resume_from_checkpoint: bool,
    resume_reuse_policy: str,
    retrieval_contract: Mapping[str, object],
) -> dict[str, object]:
    """Return a safe manifest describing the comparable benchmark execution."""

    compatibility = {
        "schema_version": "public-benchmark-execution-compat-v1",
        "suite": suite,
        "evaluation_mode": evaluation_mode,
        "transport_mode": _bounded_str(transport_mode),
        "request_timeout_seconds": float(request_timeout_seconds),
        "resume_reuse_policy": _bounded_str(resume_reuse_policy),
        "retrieval_contract": _bounded_mapping(retrieval_contract),
    }
    execution_fingerprint = _fingerprint(compatibility)
    manifest: dict[str, object] = {
        "schema_version": "public-benchmark-execution-manifest-v1",
        "execution_fingerprint": execution_fingerprint,
        "compatibility": compatibility,
        "dataset": {
            "path_label": dataset_path.name[:_MAX_STRING_CHARS],
            "sha256": dataset_hash,
            "selected_case_count": max(0, selected_case_count),
            "selected_case_fingerprint": selected_case_fingerprint,
        },
        "selection": {
            "case_selection": _bounded_mapping(case_selection or {}),
            "requested_case_ids": _bounded_list(requested_case_ids),
            "requested_case_id_count": len(tuple(requested_case_ids)),
            "requested_capabilities": _bounded_list(requested_capabilities),
            "requested_capability_count": len(tuple(requested_capabilities)),
        },
        "execution": {
            "transport_mode": _bounded_str(transport_mode),
            "requested_parallelism": requested_parallelism,
            "effective_parallelism": effective_parallelism,
            "parallelism_degraded": parallelism_degraded_reason is not None,
            "parallelism_degraded_reason": (
                _bounded_str(parallelism_degraded_reason)
                if parallelism_degraded_reason
                else None
            ),
            "request_timeout_seconds": float(request_timeout_seconds),
        },
        "checkpoint": {
            "resume_from_checkpoint": bool(resume_from_checkpoint),
            "resume_reuse_policy": _bounded_str(resume_reuse_policy),
            "checkpoint_every_cases": max(1, int(checkpoint_every_cases)),
            "checkpoint_min_interval_seconds": max(
                0.0,
                float(checkpoint_min_interval_seconds),
            ),
        },
    }
    manifest["manifest_fingerprint"] = _fingerprint(manifest)
    return manifest


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_str(value: object) -> str:
    return artifact_text_value(value, max_chars=_MAX_STRING_CHARS)


def _bounded_list(values: Sequence[str]) -> list[str]:
    return [_bounded_str(value) for value in values[:_MAX_LIST_ITEMS]]


def _bounded_mapping(values: Mapping[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for raw_key, raw_value in list(values.items())[:_MAX_LIST_ITEMS]:
        key = _bounded_str(raw_key)[:80]
        if raw_value is None:
            continue
        if isinstance(raw_value, str):
            bounded[key] = _bounded_str(raw_value)
        elif isinstance(raw_value, bool | int | float):
            bounded[key] = raw_value
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, str | bytes):
            bounded[key] = [
                _bounded_str(item)[:120]
                for item in raw_value[:_MAX_LIST_ITEMS]
                if isinstance(item, str | bool | int | float)
            ]
        elif isinstance(raw_value, Mapping):
            bounded[key] = _bounded_mapping(raw_value)
    return bounded
