"""Official public memory benchmark canary orchestration.

This module owns the reusable public benchmark canary workflow. CLI scripts and
full-provider smoke tests call this package module instead of importing from
``scripts/`` so the benchmark evidence path stays testable and reusable.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from infinity_context_core.reporting import with_report_provenance

from infinity_context_server.eval_constants import (
    _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS,
    _PUBLIC_MEMORY_BENCHMARK_REQUIRED,
)
from infinity_context_server.public_benchmark import (
    CASE_SELECTION_FIRST,
    CASE_SELECTION_STRATIFIED,
    run_public_memory_benchmark,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_MEMORY_BENCHMARK_SUITE = "public-memory-benchmark"
LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
LONGMEMEVAL_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
    "longmemeval_s_cleaned.json"
)
DEFAULT_MAX_CASES = 2
DEFAULT_MIN_ACCURACY = 0.5
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_CASE_SELECTION_STRATEGY = CASE_SELECTION_STRATIFIED


@dataclass(frozen=True)
class OfficialDataset:
    name: str
    url: str
    filename: str


@dataclass(frozen=True)
class DatasetSelection:
    path: Path
    source_kind: str


OFFICIAL_DATASETS = {
    "locomo": OfficialDataset("locomo", LOCOMO_URL, "locomo10.json"),
    "longmemeval": OfficialDataset(
        "longmemeval",
        LONGMEMEVAL_URL,
        "longmemeval_s_cleaned.json",
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        choices=("all", "locomo", "longmemeval"),
        default=os.getenv("MEMORY_PUBLIC_BENCHMARK_NAME", "all"),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=int(os.getenv("MEMORY_PUBLIC_BENCHMARK_MAX_CASES", str(DEFAULT_MAX_CASES))),
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=float(
            os.getenv("MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY", str(DEFAULT_MIN_ACCURACY))
        ),
    )
    parser.add_argument(
        "--competitive-floor",
        action="store_true",
        default=_bool_env(os.getenv("MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR")),
        help=(
            "Run each public benchmark with the scorecard's publishable "
            "case-count and accuracy floors."
        ),
    )
    parser.add_argument(
        "--case-selection-strategy",
        choices=(CASE_SELECTION_FIRST, CASE_SELECTION_STRATIFIED),
        default=os.getenv(
            "MEMORY_PUBLIC_BENCHMARK_CASE_SELECTION_STRATEGY",
            DEFAULT_CASE_SELECTION_STRATEGY,
        ),
        help="Case sampling policy for small public benchmark canaries.",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=int(os.getenv("MEMORY_PUBLIC_BENCHMARK_PARALLELISM", "1")),
        help=(
            "Maximum parallel isolated cases per benchmark. Shared memory scopes "
            "automatically run sequentially to keep evidence ordering honest."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("MEMORY_PUBLIC_BENCHMARK_API_URL") or None,
    )
    parser.add_argument(
        "--auth-token",
        default=(
            os.getenv("MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN")
            or os.getenv("MEMORY_SERVICE_TOKEN")
            or None
        ),
    )
    parser.add_argument("--locomo-dataset", type=Path, default=None)
    parser.add_argument("--longmemeval-dataset", type=Path, default=None)
    parser.add_argument(
        "--download-timeout-seconds",
        type=float,
        default=float(
            os.getenv(
                "MEMORY_PUBLIC_BENCHMARK_DOWNLOAD_TIMEOUT_SECONDS",
                str(DEFAULT_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=(
            Path(os.environ["MEMORY_PUBLIC_BENCHMARK_REPORT_OUT"])
            if os.getenv("MEMORY_PUBLIC_BENCHMARK_REPORT_OUT")
            else None
        ),
    )
    parser.add_argument(
        "--progress-out",
        type=Path,
        default=(
            Path(os.environ["MEMORY_PUBLIC_BENCHMARK_PROGRESS_OUT"])
            if os.getenv("MEMORY_PUBLIC_BENCHMARK_PROGRESS_OUT")
            else None
        ),
    )
    parser.add_argument(
        "--checkpoint-out",
        type=Path,
        default=(
            Path(os.environ["MEMORY_PUBLIC_BENCHMARK_CHECKPOINT_OUT"])
            if os.getenv("MEMORY_PUBLIC_BENCHMARK_CHECKPOINT_OUT")
            else None
        ),
    )
    parser.add_argument(
        "--checkpoint-every-cases",
        type=int,
        default=int(os.getenv("MEMORY_PUBLIC_BENCHMARK_CHECKPOINT_EVERY_CASES", "25")),
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        action="store_true",
        default=_bool_env(os.getenv("MEMORY_PUBLIC_BENCHMARK_RESUME_FROM_CHECKPOINT")),
        help=(
            "Resume already completed cases from --checkpoint-out when dataset and "
            "case selection fingerprints match."
        ),
    )
    parser.add_argument(
        "--local-state-dir",
        type=Path,
        default=(
            Path(os.environ["MEMORY_PUBLIC_BENCHMARK_LOCAL_STATE_DIR"])
            if os.getenv("MEMORY_PUBLIC_BENCHMARK_LOCAL_STATE_DIR")
            else None
        ),
        help=(
            "Optional persistent local state directory for in-process benchmark "
            "runs. Ignored when --api-url targets an external server."
        ),
    )
    args = parser.parse_args(argv)
    result = run_official_public_benchmark_canary(
        benchmark=args.benchmark,
        max_cases=args.max_cases,
        min_accuracy=args.min_accuracy,
        competitive_floor=args.competitive_floor,
        api_url=args.api_url,
        auth_token=args.auth_token,
        case_selection_strategy=args.case_selection_strategy,
        locomo_dataset=args.locomo_dataset,
        longmemeval_dataset=args.longmemeval_dataset,
        download_timeout_seconds=args.download_timeout_seconds,
        report_out=args.report_out,
        progress_out=args.progress_out,
        checkpoint_out=args.checkpoint_out,
        checkpoint_every_cases=args.checkpoint_every_cases,
        resume_from_checkpoint=args.resume_from_checkpoint,
        local_state_dir=args.local_state_dir,
        parallelism=args.parallelism,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


def run_official_public_benchmark_canary(
    *,
    benchmark: str = "all",
    max_cases: int = DEFAULT_MAX_CASES,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
    competitive_floor: bool = False,
    api_url: str | None = None,
    auth_token: str | None = None,
    case_selection_strategy: str = DEFAULT_CASE_SELECTION_STRATEGY,
    locomo_dataset: Path | None = None,
    longmemeval_dataset: Path | None = None,
    download_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    report_out: Path | None = None,
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
    checkpoint_every_cases: int = 25,
    resume_from_checkpoint: bool = False,
    local_state_dir: Path | None = None,
    parallelism: int = 1,
) -> dict[str, object]:
    if max_cases < 1:
        raise ValueError("max_cases must be greater than zero")
    selected = _selected_benchmarks(benchmark)
    effective_progress_out = progress_out or _default_progress_out(report_out)
    effective_checkpoint_out = checkpoint_out or _default_checkpoint_out(report_out)
    run_id = f"official-public-{time.time_ns()}"
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="memo-official-public-benchmark-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        reports: list[dict[str, object]] = []
        dataset_sources: dict[str, dict[str, object]] = {}
        run_policies: dict[str, dict[str, object]] = {}
        for name in selected:
            policy = _run_policy(
                name=name,
                requested_max_cases=max_cases,
                requested_min_accuracy=min_accuracy,
                competitive_floor=competitive_floor,
            )
            run_policies[name] = policy
            selection = _dataset_selection(
                name=name,
                tmp_dir=tmp_path,
                locomo_dataset=locomo_dataset,
                longmemeval_dataset=longmemeval_dataset,
                timeout_seconds=download_timeout_seconds,
            )
            report = run_public_memory_benchmark(
                dataset_path=selection.path,
                api_url=api_url,
                auth_token=auth_token,
                benchmark=name,
                max_cases=int(policy["max_cases"]),
                min_accuracy=float(policy["min_accuracy"]),
                case_selection_strategy=case_selection_strategy,
                progress_out=effective_progress_out,
                checkpoint_out=_benchmark_checkpoint_path(
                    effective_checkpoint_out,
                    benchmark=name,
                    split=len(selected) > 1,
                ),
                checkpoint_every_cases=checkpoint_every_cases,
                resume_from_checkpoint=resume_from_checkpoint,
                local_state_dir=local_state_dir,
                parallelism=parallelism,
            )
            reports.append(report)
            dataset_sources[name] = _dataset_source_metadata(
                name=name,
                selection=selection,
                report=report,
            )

    result = _merge_reports(
        reports=reports,
        dataset_sources=dataset_sources,
        benchmark=benchmark,
        max_cases=max_cases,
        min_accuracy=min_accuracy,
        competitive_floor=competitive_floor,
        run_policies=run_policies,
        case_selection_strategy=case_selection_strategy,
        api_url=api_url,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        progress_out=effective_progress_out,
        checkpoint_out=effective_checkpoint_out,
    )
    result = with_report_provenance(
        result,
        generated_by="infinity_context_server.official_public_benchmark",
        run_id=run_id,
        cwd=PROJECT_ROOT,
    )
    _write_report(result, report_out)
    return result


def _selected_benchmarks(value: str) -> tuple[str, ...]:
    normalized = value.strip().lower()
    if normalized == "all":
        return ("locomo", "longmemeval")
    if normalized in OFFICIAL_DATASETS:
        return (normalized,)
    raise ValueError(f"Unsupported benchmark: {value}")


def _run_policy(
    *,
    name: str,
    requested_max_cases: int,
    requested_min_accuracy: float,
    competitive_floor: bool,
) -> dict[str, object]:
    floor = _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.get(name, {})
    min_case_count = int(floor.get("min_case_count", requested_max_cases))
    min_accuracy = float(floor.get("min_accuracy", requested_min_accuracy))
    return {
        "max_cases": max(requested_max_cases, min_case_count)
        if competitive_floor
        else requested_max_cases,
        "min_accuracy": max(requested_min_accuracy, min_accuracy)
        if competitive_floor
        else requested_min_accuracy,
        "competitive_min_case_count": min_case_count,
        "competitive_min_accuracy": min_accuracy,
    }


def _dataset_selection(
    *,
    name: str,
    tmp_dir: Path,
    locomo_dataset: Path | None,
    longmemeval_dataset: Path | None,
    timeout_seconds: float,
) -> DatasetSelection:
    override = locomo_dataset if name == "locomo" else longmemeval_dataset
    if override is not None:
        return DatasetSelection(path=override, source_kind="local_override")
    dataset = OFFICIAL_DATASETS[name]
    destination = tmp_dir / dataset.filename
    _download(dataset.url, destination, timeout_seconds=timeout_seconds)
    return DatasetSelection(path=destination, source_kind="official_download")


def _benchmark_checkpoint_path(
    checkpoint_out: Path | None,
    *,
    benchmark: str,
    split: bool,
) -> Path | None:
    if checkpoint_out is None or not split:
        return checkpoint_out
    suffix = checkpoint_out.suffix or ".json"
    stem = checkpoint_out.name[: -len(suffix)] if checkpoint_out.suffix else checkpoint_out.name
    return checkpoint_out.with_name(f"{stem}.{benchmark}{suffix}")


def _default_progress_out(report_out: Path | None) -> Path | None:
    if report_out is None:
        return None
    return _sibling_artifact_path(report_out, artifact="progress", suffix=".jsonl")


def _default_checkpoint_out(report_out: Path | None) -> Path | None:
    if report_out is None:
        return None
    return _sibling_artifact_path(report_out, artifact="checkpoint", suffix=".json")


def _sibling_artifact_path(path: Path, *, artifact: str, suffix: str) -> Path:
    original_suffix = path.suffix
    stem = path.name[: -len(original_suffix)] if original_suffix else path.name
    return path.with_name(f"{stem}.{artifact}{suffix}")


def _download(url: str, destination: Path, *, timeout_seconds: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "infinity-context-benchmark/1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        destination.write_bytes(response.read())


def _merge_reports(
    *,
    reports: Sequence[Mapping[str, object]],
    dataset_sources: Mapping[str, Mapping[str, object]],
    benchmark: str,
    max_cases: int,
    min_accuracy: float,
    competitive_floor: bool,
    run_policies: Mapping[str, Mapping[str, object]],
    case_selection_strategy: str,
    api_url: str | None,
    elapsed_ms: float,
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
) -> dict[str, object]:
    cases: list[object] = []
    benchmarks: list[object] = []
    failures: list[object] = []
    dataset_hashes: dict[str, str] = {}
    case_selection: dict[str, object] = {}
    checks = {
        "official_sources_configured": True,
        "case_count": True,
        "unique_case_ids": True,
        "minimum_accuracy_met": True,
        "no_request_failures": True,
    }
    metrics: dict[str, object] = {
        "benchmark_count": len(reports),
        "case_count": 0,
        "accuracy": 0.0,
    }
    ok = bool(reports)
    passed_cases = 0
    total_cases = 0
    requested_parallelism_values: list[int] = []
    effective_parallelism_values: list[int] = []
    parallelism_degraded_count = 0
    parallelism_degraded_reasons: set[str] = set()
    for report in reports:
        ok = ok and report.get("ok") is True
        report_checks = report.get("checks")
        if isinstance(report_checks, Mapping):
            checks["minimum_accuracy_met"] = (
                checks["minimum_accuracy_met"]
                and report_checks.get("minimum_accuracy_met") is True
            )
            checks["no_request_failures"] = (
                checks["no_request_failures"]
                and report_checks.get("no_request_failures") is True
            )
            checks["unique_case_ids"] = (
                checks["unique_case_ids"]
                and report_checks.get("unique_case_ids") is not False
            )
        report_cases = report.get("cases")
        if isinstance(report_cases, list):
            cases.extend(report_cases)
            total_cases += len(report_cases)
            passed_cases += sum(
                1
                for item in report_cases
                if isinstance(item, Mapping) and item.get("status") == "ok"
            )
        report_benchmarks = report.get("benchmarks")
        if isinstance(report_benchmarks, list):
            benchmarks.extend(report_benchmarks)
            dataset_hash = report.get("dataset_hash")
            if isinstance(dataset_hash, str) and dataset_hash:
                for item in report_benchmarks:
                    if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                        dataset_hashes[item["name"]] = dataset_hash
        report_failures = report.get("failures")
        if isinstance(report_failures, list):
            failures.extend(report_failures)
        report_case_selection = report.get("case_selection")
        if isinstance(report_case_selection, Mapping):
            for item in report_benchmarks if isinstance(report_benchmarks, list) else []:
                if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                    case_selection[item["name"]] = dict(report_case_selection)
        report_metrics = report.get("metrics")
        if isinstance(report_metrics, Mapping):
            for key, value in report_metrics.items():
                if key.endswith("_accuracy") or key.endswith("_case_count"):
                    metrics[key] = value
            requested_parallelism = report_metrics.get("requested_parallelism")
            effective_parallelism = report_metrics.get("effective_parallelism")
            if isinstance(requested_parallelism, int):
                requested_parallelism_values.append(requested_parallelism)
            if isinstance(effective_parallelism, int):
                effective_parallelism_values.append(effective_parallelism)
            if report_metrics.get("parallelism_degraded") is True:
                parallelism_degraded_count += 1
                degraded_reason = report_metrics.get("parallelism_degraded_reason")
                if isinstance(degraded_reason, str) and degraded_reason.strip():
                    parallelism_degraded_reasons.add(degraded_reason.strip())
    metrics["case_count"] = total_cases
    metrics["accuracy"] = round(passed_cases / total_cases, 4) if total_cases else 0.0
    metrics["duplicate_case_id_count"] = sum(
        _report_metric_int(report, "duplicate_case_id_count") for report in reports
    )
    metrics["unique_case_id_count"] = sum(
        _report_metric_int(report, "unique_case_id_count") for report in reports
    )
    checks["unique_case_ids"] = checks["unique_case_ids"] and (
        metrics["duplicate_case_id_count"] == 0
    )
    checks["case_count"] = total_cases > 0
    if requested_parallelism_values:
        metrics["requested_parallelism_max"] = max(requested_parallelism_values)
    if effective_parallelism_values:
        metrics["effective_parallelism_max"] = max(effective_parallelism_values)
    metrics["parallelism_degraded_count"] = parallelism_degraded_count
    metrics["parallelism_degraded"] = parallelism_degraded_count > 0
    if parallelism_degraded_reasons:
        metrics["parallelism_degraded_reasons"] = sorted(parallelism_degraded_reasons)
    return {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark_scope": "official_public_memory_retrieval_canary",
        "evaluation_mode": "retrieved_expected_terms",
        "source_urls": {
            name: OFFICIAL_DATASETS[name].url for name in _selected_benchmarks(benchmark)
        },
        "competitive_floor_mode": competitive_floor,
        "publishable_public_benchmark_candidate": competitive_floor
        and set(_selected_benchmarks(benchmark)) == set(_PUBLIC_MEMORY_BENCHMARK_REQUIRED),
        "competitive_floor_requirements": {
            name: dict(floor)
            for name, floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.items()
        },
        "requested_max_cases": max_cases,
        "requested_min_accuracy": min_accuracy,
        "case_selection_strategy": case_selection_strategy,
        "case_selection": case_selection,
        "effective_case_limits": {
            name: int(policy["max_cases"]) for name, policy in run_policies.items()
        },
        "effective_accuracy_floors": {
            name: float(policy["min_accuracy"]) for name, policy in run_policies.items()
        },
        "dataset_hashes": dataset_hashes,
        "dataset_sources": {name: dict(source) for name, source in dataset_sources.items()},
        "api_url": api_url,
        "artifact_labels": {
            "progress": progress_out.name if progress_out is not None else None,
            "checkpoint": checkpoint_out.name if checkpoint_out is not None else None,
        },
        "max_cases_per_benchmark": max_cases,
        "min_accuracy": min_accuracy,
        "checks": checks,
        "metrics": metrics,
        "benchmarks": benchmarks,
        "cases": cases,
        "failures": failures,
        "elapsed_ms": elapsed_ms,
    }


def _dataset_source_metadata(
    *,
    name: str,
    selection: DatasetSelection,
    report: Mapping[str, object],
) -> dict[str, object]:
    dataset = OFFICIAL_DATASETS[name]
    dataset_hash = report.get("dataset_hash")
    metrics = report.get("metrics")
    case_count = (
        metrics.get(f"{name}_case_count")
        if isinstance(metrics, Mapping)
        else None
    )
    return {
        "source_kind": selection.source_kind,
        "official_url": dataset.url,
        "path_label": selection.path.name,
        "sha256": dataset_hash if isinstance(dataset_hash, str) else None,
        "size_bytes": selection.path.stat().st_size,
        "case_count": case_count if isinstance(case_count, int) else None,
    }


def _report_metric_int(report: Mapping[str, object], key: str) -> int:
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        return 0
    value = metrics.get(key)
    return value if isinstance(value, int) else 0


def _write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
