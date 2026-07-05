"""Progress and checkpoint writer for public memory benchmarks."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from infinity_context_server.public_benchmark_artifacts import (
    write_json_atomic as _write_json_atomic,
)
from infinity_context_server.public_benchmark_checkpoint import (
    BenchmarkSeedStats,
    CaseRunResult,
)
from infinity_context_server.public_benchmark_metrics import (
    bounded_progress_fields as _bounded_progress_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    bounded_public_artifact_fields as _bounded_public_artifact_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    case_payload as _case_payload,
)
from infinity_context_server.public_benchmark_metrics import (
    progress_case_outcome_fields as _progress_case_outcome_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    progress_timing_fields as _progress_timing_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    run_metric_summary as _run_metric_summary,
)

DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS = 30.0


def emit_setup_failure_progress(
    *,
    progress_out: Path | None,
    dataset_path: Path,
    dataset_hash: str,
    started: float,
    reason: str,
    case_count: int,
    diagnostics: Mapping[str, object] | None = None,
) -> None:
    if progress_out is None:
        return
    payload: dict[str, object] = {
        "schema_version": "public-benchmark-progress-v1",
        "event_type": "run_setup_failed",
        "event_index": 1,
        "dataset_path_label": dataset_path.name,
        "dataset_hash": dataset_hash,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "reason": reason,
        "total_case_count": case_count,
    }
    if diagnostics:
        payload["diagnostics"] = dict(diagnostics)
    progress_out.parent.mkdir(parents=True, exist_ok=True)
    with progress_out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_bounded_progress_fields(payload), ensure_ascii=False) + "\n")


@dataclass
class _BenchmarkProgress:
    dataset_path: Path
    dataset_hash: str
    total_case_count: int
    case_selection: Mapping[str, object] | None
    started: float
    progress_out: Path | None = None
    checkpoint_out: Path | None = None
    checkpoint_every_cases: int = 25
    checkpoint_min_interval_seconds: float = DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS
    selected_case_fingerprint: str | None = None
    execution_manifest: Mapping[str, object] | None = None
    _event_index: int = field(default=0, init=False, repr=False)
    _last_checkpoint_at: float = field(default=0.0, init=False, repr=False)

    def event(self, event_type: str, **fields: object) -> None:
        if self.progress_out is None:
            return
        self._event_index += 1
        payload: dict[str, object] = {
            "schema_version": "public-benchmark-progress-v1",
            "event_type": event_type,
            "event_index": self._event_index,
            "dataset_path_label": self.dataset_path.name,
            "dataset_hash": self.dataset_hash,
            "elapsed_ms": round((time.perf_counter() - self.started) * 1000, 2),
        }
        payload.update(_bounded_progress_fields(fields))
        self.progress_out.parent.mkdir(parents=True, exist_ok=True)
        with self.progress_out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def checkpoint(
        self,
        *,
        processed_case_count: int,
        run_results: Sequence[CaseRunResult],
        failures: Sequence[Mapping[str, object]],
        seeded_source_count: int,
        seed_stats: BenchmarkSeedStats | None = None,
        force: bool = False,
    ) -> None:
        if self.checkpoint_out is None:
            return
        processed_case_count = max(0, min(processed_case_count, self.total_case_count))
        now = time.perf_counter()
        last_checkpoint_at = self._last_checkpoint_at or self.started
        interval = max(1, self.checkpoint_every_cases)
        interval_seconds = max(0.0, float(self.checkpoint_min_interval_seconds))
        checkpoint_reason = (
            "forced"
            if force
            else self._checkpoint_due_reason(
                processed_case_count=processed_case_count,
                now=now,
                interval=interval,
                interval_seconds=interval_seconds,
                last_checkpoint_at=last_checkpoint_at,
            )
        )
        if checkpoint_reason is None:
            return
        payload = {
            "schema_version": "public-benchmark-checkpoint-v1",
            "status": ("completed" if processed_case_count >= self.total_case_count else "running"),
            "dataset_path_label": self.dataset_path.name,
            "dataset_hash": self.dataset_hash,
            "case_selection": dict(self.case_selection or {}),
            "selected_case_count": self.total_case_count,
            "checkpoint_policy": {
                "checkpoint_every_cases": interval,
                "checkpoint_min_interval_seconds": interval_seconds,
                "checkpoint_reason": checkpoint_reason,
            },
            "progress": {
                "processed_case_count": processed_case_count,
                "total_case_count": self.total_case_count,
                "processed_case_ratio": _ratio(
                    min(processed_case_count, self.total_case_count),
                    self.total_case_count,
                ),
                **_progress_timing_fields(
                    processed_case_count=processed_case_count,
                    total_case_count=self.total_case_count,
                    started=self.started,
                ),
                **_progress_case_outcome_fields(
                    processed_case_count=processed_case_count,
                    run_results=run_results,
                    failures=failures,
                    total_case_count=self.total_case_count,
                ),
                "seeded_source_count": seeded_source_count,
                "seed_source_attempt_count": (
                    seed_stats.source_attempt_count if seed_stats is not None else 0
                ),
                "seed_cache_hit_count": (
                    seed_stats.seed_cache_hit_count if seed_stats is not None else 0
                ),
                "checkpoint_reason": checkpoint_reason,
                "elapsed_since_checkpoint_ms": round(
                    max(0.0, now - last_checkpoint_at) * 1000,
                    2,
                ),
                "elapsed_ms": round((now - self.started) * 1000, 2),
            },
            "metrics_so_far": _run_metric_summary(run_results),
            "cases": [_case_payload(item) for item in run_results],
            "failures": [_bounded_public_artifact_fields(item) for item in failures],
            "recent_cases": [_case_payload(item) for item in run_results[-20:]],
            "recent_failures": [
                _bounded_public_artifact_fields(item) for item in failures[-20:]
            ],
        }
        if self.selected_case_fingerprint:
            payload["selected_case_fingerprint"] = self.selected_case_fingerprint
        if self.execution_manifest:
            payload["execution_manifest"] = dict(self.execution_manifest)
            execution_fingerprint = self.execution_manifest.get("execution_fingerprint")
            if isinstance(execution_fingerprint, str) and execution_fingerprint:
                payload["execution_fingerprint"] = execution_fingerprint
        self.checkpoint_out.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.checkpoint_out, payload)
        self._last_checkpoint_at = now

    def _checkpoint_due_reason(
        self,
        *,
        processed_case_count: int,
        now: float,
        interval: int,
        interval_seconds: float,
        last_checkpoint_at: float,
    ) -> str | None:
        if processed_case_count >= self.total_case_count:
            return "completed"
        if processed_case_count <= 0:
            return None
        if processed_case_count % interval == 0:
            return "case_interval"
        if now - last_checkpoint_at >= interval_seconds:
            return "time_interval"
        return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(1.0, numerator / denominator)), 6)
