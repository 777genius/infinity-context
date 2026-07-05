"""Normalized public memory benchmark runner.

The runner intentionally talks to Infinity Context through the HTTP API surface, even
when it uses an in-process FastAPI TestClient. This keeps the benchmark close to
how external users exercise the platform while avoiding a hard dependency on a
specific provider adapter.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import tempfile
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
from infinity_context_core.application.context_lexical import text_variant_profile
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    score_query_relevance_against_profile,
)
from infinity_context_core.reporting import with_report_provenance

from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset as _validate_artifacts_not_dataset,
)
from infinity_context_server.public_benchmark_artifacts import (
    validate_distinct_artifact_paths as _validate_distinct_artifact_paths,
)
from infinity_context_server.public_benchmark_artifacts import (
    write_json_atomic as _write_json_atomic,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_answer_preview as _case_answer_preview,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_evidence_ref_previews as _case_evidence_ref_previews,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_evidence_refs as _case_evidence_refs,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    case_expected_terms_preview as _case_expected_terms_preview,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    preview_value as _preview_value,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    response_evidence_text as _evidence_text,
)
from infinity_context_server.public_benchmark_checkpoint import (
    BenchmarkSeedStats as _BenchmarkSeedStats,
)
from infinity_context_server.public_benchmark_checkpoint import (
    CaseRunResult,
    case_result_key,
    load_checkpoint_resume_state_with_diagnostics,
    safe_identifier,
    seed_corpus_identity,
    seed_corpus_metadata,
    selected_case_fingerprint,
)
from infinity_context_server.public_benchmark_checkpoint import (
    SeedCorpusMetadata as _SeedCorpusMetadata,
)
from infinity_context_server.public_benchmark_environment import (
    check_local_benchmark_environment,
    local_environment_failure_result,
)
from infinity_context_server.public_benchmark_execution import (
    CaseExecutionEntry as _CaseExecutionEntry,
)
from infinity_context_server.public_benchmark_execution import (
    CaseExecutionGroupOutcome as _CaseExecutionGroupOutcome,
)
from infinity_context_server.public_benchmark_execution import (
    case_exception_outcome as _case_exception_outcome,
)
from infinity_context_server.public_benchmark_execution import (
    case_execution_groups as _case_execution_groups,
)
from infinity_context_server.public_benchmark_execution import (
    case_execution_parallelism as _case_execution_parallelism,
)
from infinity_context_server.public_benchmark_execution import (
    emit_case_completed as _emit_case_completed,
)
from infinity_context_server.public_benchmark_execution import (
    emit_case_failed as _emit_case_failed,
)
from infinity_context_server.public_benchmark_execution import (
    emit_case_started as _emit_case_started,
)
from infinity_context_server.public_benchmark_execution import (
    execute_case_group_with_isolated_state as _execute_case_group_with_isolated_state,
)
from infinity_context_server.public_benchmark_execution import (
    execute_case_sequentially as _execute_case_sequentially,
)
from infinity_context_server.public_benchmark_execution import (
    merge_case_execution_group_outcome as _merge_case_execution_group_outcome,
)
from infinity_context_server.public_benchmark_execution import (
    normalize_parallelism as _normalize_parallelism,
)
from infinity_context_server.public_benchmark_execution import (
    ordered_run_results as _ordered_run_results,
)
from infinity_context_server.public_benchmark_http import (
    auth_headers as _auth_headers,
)
from infinity_context_server.public_benchmark_http import (
    post_required as _post_required,
)
from infinity_context_server.public_benchmark_http import (
    response_data as _response_data,
)
from infinity_context_server.public_benchmark_manifest import (
    build_execution_manifest as _build_execution_manifest,
)
from infinity_context_server.public_benchmark_metrics import (
    accuracy as _accuracy,
)
from infinity_context_server.public_benchmark_metrics import (
    benchmark_summaries as _benchmark_summaries,
)
from infinity_context_server.public_benchmark_metrics import (
    benchmark_summary_case_count as _benchmark_summary_case_count,
)
from infinity_context_server.public_benchmark_metrics import (
    case_failures as _case_failures,
)
from infinity_context_server.public_benchmark_metrics import (
    case_payload as _case_payload,
)
from infinity_context_server.public_benchmark_metrics import (
    dataset_source_metadata as _dataset_source_metadata,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_accuracy as _flat_capability_accuracy,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_case_count as _flat_capability_case_count,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_failure_count as _flat_capability_failure_count,
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
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkHttpClientPort,
    BenchmarkHttpResponsePort,
    BenchmarkMemoryInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.public_benchmark_models import (
    HttpBenchmarkAdapter as _HttpBenchmarkAdapter,
)
from infinity_context_server.public_benchmark_models import (
    TestClientBenchmarkAdapter as _TestClientBenchmarkAdapter,
)
from infinity_context_server.public_benchmark_progress import (
    DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS as _DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS,
)
from infinity_context_server.public_benchmark_progress import (
    _BenchmarkProgress,
)
from infinity_context_server.public_benchmark_progress import (
    emit_setup_failure_progress as _emit_setup_failure_progress,
)
from infinity_context_server.public_benchmark_results import (
    duplicate_case_failure_result as _duplicate_case_failure_result,
)
from infinity_context_server.public_benchmark_results import (
    setup_failure_result as _setup_failure_result,
)
from infinity_context_server.public_benchmark_results import (
    write_report as _write_report,
)
from infinity_context_server.public_benchmark_selection import (
    CASE_SELECTION_FIRST,
    CASE_SELECTION_STRATIFIED,
    SUPPORTED_CASE_SELECTION_STRATEGIES,
)
from infinity_context_server.public_benchmark_selection import (
    case_selection_missing_capabilities as _case_selection_missing_capabilities,
)
from infinity_context_server.public_benchmark_selection import (
    case_selection_missing_case_ids as _case_selection_missing_case_ids,
)
from infinity_context_server.public_benchmark_selection import (
    missing_capability_failures as _missing_capability_failures,
)
from infinity_context_server.public_benchmark_selection import (
    normalize_requested_capabilities as _normalize_requested_capabilities,
)
from infinity_context_server.public_benchmark_selection import (
    normalize_requested_case_ids as _normalize_requested_case_ids,
)
from infinity_context_server.public_benchmark_selection import (
    select_cases as _select_cases,
)
from infinity_context_server.public_benchmark_unsupported import (
    augment_case_selection_with_unsupported_requested_cases as _augment_unsupported_cases,
)
from infinity_context_server.public_benchmark_unsupported import (
    missing_case_id_failures_for_selection as _missing_case_id_failures_for_selection,
)
from infinity_context_server.public_benchmark_unsupported import (
    unsupported_case_reports_for_selection as _unsupported_case_reports_for_selection,
)

__all__ = (
    "BenchmarkDocumentInput",
    "BenchmarkHttpClientPort",
    "BenchmarkHttpResponsePort",
    "BenchmarkMemoryInput",
    "BenchmarkValidationError",
    "CASE_SELECTION_FIRST",
    "CASE_SELECTION_STRATIFIED",
    "PublicBenchmarkCase",
    "SUPPORTED_CASE_SELECTION_STRATEGIES",
    "_write_json_atomic",
    "load_public_benchmark_case_count",
    "load_public_benchmark_dataset_profile",
    "run_public_memory_benchmark",
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_MEMORY_BENCHMARK_SUITE = "public-memory-benchmark"
LOCOMO_BENCHMARK_SUITE = "locomo"
LONGMEMEVAL_BENCHMARK_SUITE = "longmemeval"
SUPPORTED_BENCHMARKS = frozenset({LOCOMO_BENCHMARK_SUITE, LONGMEMEVAL_BENCHMARK_SUITE})
_DEFAULT_MIN_ACCURACY = 0.85
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
_PUBLIC_BENCHMARK_CONTEXT_TOKEN_BUDGET = 4000
_PUBLIC_BENCHMARK_MAX_FACTS = 20
_PUBLIC_BENCHMARK_MAX_CHUNKS = 50
_PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE = 3
_MAX_RESUME_CASE_ID_DETAILS = 20
_MAX_LOCOMO_OBSERVATION_EVIDENCE_IDS = 8
_RESUME_REUSE_POLICY = "successful_cases_only"


@dataclass(frozen=True)
class _OfficialLocomoTurn:
    session_key: str
    dia_id: str
    speaker: str
    text: str
    turn_index: int


def run_public_memory_benchmark(
    *,
    dataset_path: Path,
    api_url: str | None = None,
    auth_token: str | None = None,
    report_out: Path | None = None,
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
    checkpoint_every_cases: int = 25,
    checkpoint_min_interval_seconds: float = _DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS,
    local_state_dir: Path | None = None,
    benchmark: str | None = None,
    min_accuracy: float = _DEFAULT_MIN_ACCURACY,
    max_cases: int | None = None,
    case_selection_strategy: str = CASE_SELECTION_FIRST,
    case_ids: Sequence[str] | None = None,
    capabilities: Sequence[str] | None = None,
    resume_from_checkpoint: bool = False,
    parallelism: int = 1,
    request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run normalized public memory cases and optionally write a JSON report."""

    _validate_distinct_artifact_paths(
        error_factory=BenchmarkValidationError,
        report_out=report_out,
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
    )
    _validate_artifacts_not_dataset(
        dataset_path=dataset_path,
        error_factory=BenchmarkValidationError,
        report_out=report_out,
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
    )
    started = time.perf_counter()
    request_timeout_seconds = _normalize_request_timeout_seconds(request_timeout_seconds)
    checkpoint_min_interval_seconds = _normalize_checkpoint_min_interval_seconds(
        checkpoint_min_interval_seconds
    )
    requested_case_ids = _normalize_requested_case_ids(case_ids)
    requested_capabilities = _normalize_requested_capabilities(capabilities)
    cases = _load_cases(dataset_path)
    canonical_benchmark = _normalize_benchmark_name(benchmark) if benchmark else None
    if canonical_benchmark:
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    cases, case_selection = _select_cases(
        cases,
        max_cases=max_cases,
        strategy=case_selection_strategy,
        case_ids=requested_case_ids,
        capabilities=requested_capabilities,
        capability_resolver=_case_capability,
        error_factory=BenchmarkValidationError,
    )
    case_selection = _augment_unsupported_cases(
        dataset_path=dataset_path,
        benchmark=canonical_benchmark,
        requested_case_ids=requested_case_ids,
        case_selection=case_selection,
        locomo_benchmark=LOCOMO_BENCHMARK_SUITE,
        load_dataset_payload=_load_dataset_payload,
        is_official_locomo_sample=_is_official_locomo_sample,
        official_locomo_case_ids=_official_locomo_case_ids,
        first_str=_first_str,
        case_hash=_case_hash,
    )

    duplicate_case_keys = _duplicate_case_keys(cases)
    if duplicate_case_keys:
        result = _duplicate_case_failure_result(
            suite=PUBLIC_MEMORY_BENCHMARK_SUITE,
            cases=cases,
            duplicate_case_keys=duplicate_case_keys,
        )
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        result["case_selection"] = case_selection
        result["requested_case_ids"] = list(requested_case_ids)
        result["requested_capabilities"] = list(requested_capabilities)
        _write_report(result, report_out)
        return result

    if not cases:
        missing_case_ids = _case_selection_missing_case_ids(case_selection)
        missing_capabilities = _case_selection_missing_capabilities(case_selection)
        case_selection_failures = _missing_case_id_failures_for_selection(case_selection)
        unsupported_cases = _unsupported_case_reports_for_selection(case_selection)
        capability_selection_failures = _missing_capability_failures(missing_capabilities)
        unsupported_case_id_count = len(unsupported_cases)
        selection_failures = case_selection_failures + capability_selection_failures
        failures = selection_failures or (
            []
            if unsupported_cases
            else [
                {
                    "case_id": "dataset",
                    "category": "setup",
                    "reason": "no_supported_cases",
                }
            ]
        )
        result = {
            "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
            "status": "failed",
            "ok": False,
            "benchmark_scope": "normalized_public_memory_retrieval",
            "evaluation_mode": "retrieved_expected_terms",
            "dataset_path_label": dataset_path.name,
            "requested_case_ids": list(requested_case_ids),
            "requested_capabilities": list(requested_capabilities),
            "checks": {
                "dataset_loaded": False,
                "case_count": False,
                "requested_case_ids_found": not case_selection_failures,
                "requested_case_ids_supported": unsupported_case_id_count == 0,
                "requested_capabilities_found": not missing_capabilities,
            },
            "metrics": {
                "case_count": 0,
                "benchmark_count": 0,
                "missing_case_id_count": len(missing_case_ids),
                "unsupported_case_id_count": unsupported_case_id_count,
                "missing_capability_count": len(missing_capabilities),
                "accuracy": 0.0,
            },
            "benchmarks": [],
            "cases": [],
            "failures": failures,
            "unsupported_cases": unsupported_cases,
            "case_selection": case_selection,
        }
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        _write_report(result, report_out)
        return result

    token = auth_token or (_default_service_token() if api_url else "test-token")
    if not token:
        result = _setup_failure_result(
            suite=PUBLIC_MEMORY_BENCHMARK_SUITE,
            reason="auth_token_required",
            case_count=len(cases),
        )
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        result["case_selection"] = case_selection
        result["requested_case_ids"] = list(requested_case_ids)
        result["requested_capabilities"] = list(requested_capabilities)
        _write_report(result, report_out)
        return result

    if api_url:
        with httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=request_timeout_seconds,
        ) as http_client:
            adapter: BenchmarkHttpClientPort = _HttpBenchmarkAdapter(http_client)
            result = _execute_cases(
                adapter=adapter,
                headers=_auth_headers(token),
                cases=cases,
                dataset_path=dataset_path,
                min_accuracy=min_accuracy,
                started=started,
                case_selection=case_selection,
                requested_case_ids=requested_case_ids,
                requested_capabilities=requested_capabilities,
                progress_out=progress_out,
                checkpoint_out=checkpoint_out,
                checkpoint_every_cases=checkpoint_every_cases,
                checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
                resume_from_checkpoint=resume_from_checkpoint,
                parallelism=parallelism,
                transport_mode="external_http",
                request_timeout_seconds=request_timeout_seconds,
            )
    else:
        environment = check_local_benchmark_environment()
        if not environment.ok:
            reason = environment.reason or "local_environment_unavailable"
            environment_diagnostics = dict(environment.diagnostics)
            _emit_setup_failure_progress(
                progress_out=progress_out,
                dataset_path=dataset_path,
                dataset_hash=_dataset_hash(dataset_path),
                started=started,
                reason=reason,
                case_count=len(cases),
                diagnostics={"local_environment": environment_diagnostics},
            )
            result = local_environment_failure_result(
                environment,
                suite=PUBLIC_MEMORY_BENCHMARK_SUITE,
                case_count=len(cases),
            )
            result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
            result["case_selection"] = case_selection
            result["requested_case_ids"] = list(requested_case_ids)
            result["requested_capabilities"] = list(requested_capabilities)
            _write_report(result, report_out)
            return result
        from fastapi.testclient import TestClient

        from infinity_context_server.config import DeployProfile, Settings
        from infinity_context_server.main import create_app

        state_context = (
            nullcontext(_prepare_local_state_dir(local_state_dir))
            if local_state_dir is not None
            else tempfile.TemporaryDirectory(prefix="memo-public-benchmark-")
        )
        with state_context as tmp_dir:
            tmp_path = Path(tmp_dir)
            app = create_app(
                Settings(
                    deploy_profile=DeployProfile.TEST,
                    database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
                    auto_create_schema=True,
                    service_token=token,
                    qdrant_enabled=False,
                    graphiti_enabled=False,
                    embeddings_enabled=False,
                )
            )
            with TestClient(app) as test_client:
                adapter = _TestClientBenchmarkAdapter(test_client)
                result = _execute_cases(
                    adapter=adapter,
                    headers=_auth_headers(token),
                    cases=cases,
                    dataset_path=dataset_path,
                    min_accuracy=min_accuracy,
                    started=started,
                    case_selection=case_selection,
                    requested_case_ids=requested_case_ids,
                    requested_capabilities=requested_capabilities,
                    progress_out=progress_out,
                    checkpoint_out=checkpoint_out,
                    checkpoint_every_cases=checkpoint_every_cases,
                    checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
                    resume_from_checkpoint=(resume_from_checkpoint and local_state_dir is not None),
                    parallelism=parallelism,
                    force_sequential_reason="local_in_process_transport",
                    transport_mode="local_in_process",
                    request_timeout_seconds=request_timeout_seconds,
                )

    result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
    if local_state_dir is not None and not api_url:
        result["local_state"] = {
            "enabled": True,
            "state_dir_label": local_state_dir.expanduser().name,
            "database_label": "memory.db",
        }
    _write_report(result, report_out)
    return result


def _default_service_token() -> str:
    from infinity_context_server.config import Settings

    return Settings().service_token


def _prepare_local_state_dir(local_state_dir: Path) -> Path:
    state_dir = local_state_dir.expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_public_benchmark_case_count(
    *,
    dataset_path: Path,
    benchmark: str | None = None,
) -> int:
    """Return the normalized case count without running retrieval or writing data."""

    return int(
        load_public_benchmark_dataset_profile(
            dataset_path=dataset_path,
            benchmark=benchmark,
        )["case_count"]
    )


def load_public_benchmark_dataset_profile(
    *,
    dataset_path: Path,
    benchmark: str | None = None,
) -> dict[str, object]:
    """Return safe normalized dataset profile without running retrieval."""

    cases = _load_cases(dataset_path)
    if benchmark:
        canonical_benchmark = _normalize_benchmark_name(benchmark)
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    case_keys = tuple(f"{case.benchmark}:{case.case_id}" for case in cases)
    unique_case_keys = set(case_keys)
    benchmark_counts: dict[str, int] = defaultdict(int)
    capability_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        benchmark_counts[case.benchmark] += 1
        capability = _case_capability(case)
        if capability:
            capability_counts[f"{case.benchmark}:{capability}"] += 1
    return {
        "case_count": len(cases),
        "unique_case_id_count": len(unique_case_keys),
        "duplicate_case_id_count": len(case_keys) - len(unique_case_keys),
        "benchmark_counts": dict(sorted(benchmark_counts.items())),
        "capability_counts": dict(sorted(capability_counts.items())),
        "dataset_hash": _dataset_hash(dataset_path),
        "dataset_path_label": dataset_path.name,
    }


def _with_public_benchmark_provenance(
    result: dict[str, object],
    *,
    dataset_path: Path,
) -> dict[str, object]:
    return with_report_provenance(
        result,
        generated_by="infinity_context_server.public_benchmark",
        run_id=_dataset_hash(dataset_path)[:16],
        cwd=PROJECT_ROOT,
    )


def _execute_cases(
    *,
    adapter: BenchmarkHttpClientPort,
    headers: Mapping[str, str],
    cases: Sequence[PublicBenchmarkCase],
    dataset_path: Path,
    min_accuracy: float,
    started: float,
    case_selection: Mapping[str, object] | None = None,
    requested_case_ids: Sequence[str] = (),
    requested_capabilities: Sequence[str] = (),
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
    checkpoint_every_cases: int = 25,
    checkpoint_min_interval_seconds: float = _DEFAULT_CHECKPOINT_MIN_INTERVAL_SECONDS,
    resume_from_checkpoint: bool = False,
    parallelism: int = 1,
    force_sequential_reason: str | None = None,
    transport_mode: str = "custom_adapter",
    request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, object]:
    _validate_distinct_artifact_paths(
        error_factory=BenchmarkValidationError,
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
    )
    _validate_artifacts_not_dataset(
        dataset_path=dataset_path,
        error_factory=BenchmarkValidationError,
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
    )
    requested_parallelism = _normalize_parallelism(
        parallelism,
        error_factory=BenchmarkValidationError,
    )
    request_timeout_seconds = _normalize_request_timeout_seconds(request_timeout_seconds)
    checkpoint_min_interval_seconds = _normalize_checkpoint_min_interval_seconds(
        checkpoint_min_interval_seconds
    )
    dataset_hash = _dataset_hash(dataset_path)
    scope_slug = f"public-benchmark-{dataset_hash[:16]}"
    run_results: list[CaseRunResult] = []
    failures: list[dict[str, object]] = []
    seeded_source_keys: set[tuple[str, str, str, str]] = set()
    seeded_corpus_identities: set[tuple[str, str, str]] = set()
    seed_corpus_metadata_cache: dict[tuple[int, int], _SeedCorpusMetadata] = {}
    seed_stats = _BenchmarkSeedStats()
    progress = _BenchmarkProgress(
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        total_case_count=len(cases),
        case_selection=case_selection,
        started=started,
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=checkpoint_every_cases,
        checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        selected_case_fingerprint=selected_case_fingerprint(cases),
    )

    progress.event(
        "run_started",
        total_case_count=len(cases),
        benchmark_count=len({case.benchmark for case in cases}),
        requested_parallelism=requested_parallelism,
        request_timeout_seconds=request_timeout_seconds,
        checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        transport_mode=transport_mode,
    )
    execution_manifest_preview = _build_execution_manifest(
        suite=PUBLIC_MEMORY_BENCHMARK_SUITE,
        evaluation_mode="retrieved_expected_terms",
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        selected_case_count=len(cases),
        selected_case_fingerprint=progress.selected_case_fingerprint or "",
        case_selection=case_selection,
        requested_case_ids=requested_case_ids,
        requested_capabilities=requested_capabilities,
        transport_mode=transport_mode,
        requested_parallelism=requested_parallelism,
        effective_parallelism=requested_parallelism,
        parallelism_degraded_reason=None,
        request_timeout_seconds=request_timeout_seconds,
        checkpoint_every_cases=checkpoint_every_cases,
        checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        resume_from_checkpoint=resume_from_checkpoint,
        resume_reuse_policy=_RESUME_REUSE_POLICY,
        retrieval_contract=_retrieval_contract_manifest(),
    )
    resumed_case_keys: set[tuple[str, str]] = set()
    resume_report: dict[str, object] = {
        "requested": resume_from_checkpoint,
        "status": "disabled",
        "reason": "not_requested",
        "resume_reuse_policy": _RESUME_REUSE_POLICY,
        "resumed_case_count": 0,
        "selected_case_count": len(cases),
        "checkpoint_case_count": 0,
        "checkpoint_success_case_count": 0,
        "checkpoint_failed_case_count": 0,
        "checkpoint_invalid_case_count": 0,
        "checkpoint_failure_diagnostic_count": 0,
        "checkpoint_failed_case_requeued_count": 0,
        "checkpoint_failed_case_ids": [],
        "checkpoint_failed_case_id_truncated_count": 0,
        "checkpoint_failures": [],
    }
    if resume_from_checkpoint:
        resume_load = load_checkpoint_resume_state_with_diagnostics(
            checkpoint_out=checkpoint_out,
            dataset_hash=dataset_hash,
            case_selection=case_selection,
            cases=cases,
            execution_fingerprint=str(execution_manifest_preview["execution_fingerprint"]),
        )
        checkpoint_failures = [dict(item) for item in resume_load.checkpoint_failures]
        checkpoint_failed_case_ids, checkpoint_failed_case_id_truncated_count = (
            _bounded_checkpoint_failure_case_id_details(checkpoint_failures)
        )
        resume_report = {
            "requested": True,
            "status": resume_load.status,
            "reason": resume_load.reason,
            "resume_reuse_policy": _RESUME_REUSE_POLICY,
            "resumed_case_count": 0,
            "selected_case_count": resume_load.selected_case_count,
            "checkpoint_case_count": resume_load.checkpoint_case_count,
            "checkpoint_success_case_count": resume_load.checkpoint_success_case_count,
            "checkpoint_failed_case_count": resume_load.checkpoint_failed_case_count,
            "checkpoint_invalid_case_count": resume_load.checkpoint_invalid_case_count,
            "checkpoint_failure_diagnostic_count": len(checkpoint_failures),
            "checkpoint_failed_case_requeued_count": resume_load.checkpoint_failed_case_count,
            "checkpoint_failed_case_ids": checkpoint_failed_case_ids,
            "checkpoint_failed_case_id_truncated_count": (
                checkpoint_failed_case_id_truncated_count
            ),
            "checkpoint_failures": checkpoint_failures,
        }
        resume_state = resume_load.state
        if resume_state is not None:
            run_results.extend(resume_state.run_results)
            failures.extend(dict(item) for item in resume_state.failures)
            seeded_source_keys.update(resume_state.seeded_source_keys)
            seeded_corpus_identities.update(resume_state.seeded_corpus_identities)
            seed_stats = resume_state.seed_stats
            resumed_case_keys = {
                case_result_key(result.benchmark, result.case_id)
                for result in resume_state.run_results
            }
            resume_report["resumed_case_count"] = len(resumed_case_keys)
            progress.event(
                "run_resumed",
                reason=resume_load.reason,
                resume_reuse_policy=_RESUME_REUSE_POLICY,
                resumed_case_count=len(resumed_case_keys),
                checkpoint_case_count=resume_load.checkpoint_case_count,
                checkpoint_success_case_count=resume_load.checkpoint_success_case_count,
                checkpoint_failed_case_count=resume_load.checkpoint_failed_case_count,
                checkpoint_invalid_case_count=resume_load.checkpoint_invalid_case_count,
                checkpoint_failure_diagnostic_count=len(checkpoint_failures),
                checkpoint_failed_case_requeued_count=(resume_load.checkpoint_failed_case_count),
                checkpoint_failed_case_ids=checkpoint_failed_case_ids,
                checkpoint_failed_case_id_truncated_count=(
                    checkpoint_failed_case_id_truncated_count
                ),
                seeded_source_count=len(seeded_source_keys),
                seed_source_attempt_count=seed_stats.source_attempt_count,
                seed_cache_hit_count=seed_stats.seed_cache_hit_count,
            )
        else:
            progress.event(
                "run_resume_skipped",
                reason=resume_load.reason,
                resume_reuse_policy=_RESUME_REUSE_POLICY,
                selected_case_count=resume_load.selected_case_count,
                checkpoint_case_count=resume_load.checkpoint_case_count,
                checkpoint_success_case_count=resume_load.checkpoint_success_case_count,
                checkpoint_failed_case_count=resume_load.checkpoint_failed_case_count,
                checkpoint_invalid_case_count=resume_load.checkpoint_invalid_case_count,
                checkpoint_failure_diagnostic_count=len(checkpoint_failures),
                checkpoint_failed_case_requeued_count=(resume_load.checkpoint_failed_case_count),
                checkpoint_failed_case_ids=checkpoint_failed_case_ids,
                checkpoint_failed_case_id_truncated_count=(
                    checkpoint_failed_case_id_truncated_count
                ),
            )
    pending_entries = tuple(
        _CaseExecutionEntry(case_index=case_index, case=case)
        for case_index, case in enumerate(cases, start=1)
        if case_result_key(case.benchmark, case.case_id) not in resumed_case_keys
    )
    resumed_case_ids, resumed_case_id_truncated_count = _bounded_case_id_details(
        case for case in cases if case_result_key(case.benchmark, case.case_id) in resumed_case_keys
    )
    pending_case_ids, pending_case_id_truncated_count = _bounded_case_id_details(
        entry.case for entry in pending_entries
    )
    resume_report["resumed_case_ids"] = resumed_case_ids
    resume_report["pending_case_ids"] = pending_case_ids
    resume_report["resumed_case_id_truncated_count"] = resumed_case_id_truncated_count
    resume_report["pending_case_id_truncated_count"] = pending_case_id_truncated_count
    if (
        force_sequential_reason is not None
        and requested_parallelism > 1
        and len(pending_entries) > 1
    ):
        effective_parallelism = 1
        parallelism_degraded_reason = force_sequential_reason
    else:
        effective_parallelism, parallelism_degraded_reason = _case_execution_parallelism(
            pending_entries,
            requested_parallelism=requested_parallelism,
        )
    progress.event(
        "run_execution_configured",
        pending_case_count=len(pending_entries),
        pending_case_ids=pending_case_ids,
        pending_case_id_truncated_count=pending_case_id_truncated_count,
        resumed_case_count=len(resumed_case_keys),
        resumed_case_ids=resumed_case_ids,
        resumed_case_id_truncated_count=resumed_case_id_truncated_count,
        requested_parallelism=requested_parallelism,
        effective_parallelism=effective_parallelism,
        parallelism_degraded_reason=parallelism_degraded_reason,
        request_timeout_seconds=request_timeout_seconds,
        checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        resume_reuse_policy=_RESUME_REUSE_POLICY,
        checkpoint_failed_case_requeued_count=resume_report[
            "checkpoint_failed_case_requeued_count"
        ],
        checkpoint_failed_case_ids=resume_report["checkpoint_failed_case_ids"],
        checkpoint_failed_case_id_truncated_count=resume_report[
            "checkpoint_failed_case_id_truncated_count"
        ],
        transport_mode=transport_mode,
    )
    execution_manifest = _build_execution_manifest(
        suite=PUBLIC_MEMORY_BENCHMARK_SUITE,
        evaluation_mode="retrieved_expected_terms",
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        selected_case_count=len(cases),
        selected_case_fingerprint=progress.selected_case_fingerprint or "",
        case_selection=case_selection,
        requested_case_ids=requested_case_ids,
        requested_capabilities=requested_capabilities,
        transport_mode=transport_mode,
        requested_parallelism=requested_parallelism,
        effective_parallelism=effective_parallelism,
        parallelism_degraded_reason=parallelism_degraded_reason,
        request_timeout_seconds=request_timeout_seconds,
        checkpoint_every_cases=checkpoint_every_cases,
        checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        resume_from_checkpoint=resume_from_checkpoint,
        resume_reuse_policy=_RESUME_REUSE_POLICY,
        retrieval_contract=_retrieval_contract_manifest(),
    )
    progress.execution_manifest = execution_manifest
    progress.event(
        "run_execution_manifest",
        execution_fingerprint=execution_manifest["execution_fingerprint"],
        manifest_fingerprint=execution_manifest["manifest_fingerprint"],
        transport_mode=transport_mode,
        requested_parallelism=requested_parallelism,
        effective_parallelism=effective_parallelism,
        parallelism_degraded_reason=parallelism_degraded_reason,
        resume_reuse_policy=_RESUME_REUSE_POLICY,
    )

    def run_case_adapter(
        case: PublicBenchmarkCase,
        source_keys: set[tuple[str, str, str, str]],
        corpus_identities: set[tuple[str, str, str]],
        metadata_cache: dict[tuple[int, int], _SeedCorpusMetadata],
        stats: _BenchmarkSeedStats,
        case_progress: _BenchmarkProgress | None,
        case_index: int | None,
        total_case_count: int | None,
    ) -> CaseRunResult:
        return _run_case(
            adapter=adapter,
            headers=headers,
            scope_slug=scope_slug,
            dataset_hash=dataset_hash,
            case=case,
            seeded_source_keys=source_keys,
            seeded_corpus_identities=corpus_identities,
            seed_corpus_metadata_cache=metadata_cache,
            seed_stats=stats,
            progress=case_progress,
            case_index=case_index,
            total_case_count=total_case_count,
        )

    if effective_parallelism <= 1:
        for entry in pending_entries:
            _execute_case_sequentially(
                entry=entry,
                run_case=run_case_adapter,
                capability_resolver=_case_capability,
                seeded_source_keys=seeded_source_keys,
                seeded_corpus_identities=seeded_corpus_identities,
                seed_corpus_metadata_cache=seed_corpus_metadata_cache,
                seed_stats=seed_stats,
                progress=progress,
                total_case_count=len(cases),
                run_results=run_results,
                failures=failures,
                effective_parallelism=effective_parallelism,
            )
            _emit_case_progress_snapshot(
                progress=progress,
                run_results=run_results,
                failures=failures,
                seeded_source_count=len(seeded_source_keys),
                seed_stats=seed_stats,
                effective_parallelism=effective_parallelism,
            )
            progress.checkpoint(
                processed_case_count=len(run_results),
                run_results=run_results,
                failures=failures,
                seeded_source_count=len(seeded_source_keys),
                seed_stats=seed_stats,
            )
    else:
        result_by_key = {
            case_result_key(result.benchmark, result.case_id): result for result in run_results
        }
        execution_groups = _case_execution_groups(pending_entries)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=effective_parallelism,
            thread_name_prefix="public-benchmark-context",
        ) as executor:
            future_to_group = {}
            for group in execution_groups:
                for entry in group.entries:
                    _emit_case_started(
                        progress=progress,
                        entry=entry,
                        capability_resolver=_case_capability,
                        total_case_count=len(cases),
                        effective_parallelism=effective_parallelism,
                    )
                future = executor.submit(
                    _execute_case_group_with_isolated_state,
                    group=group,
                    run_case=run_case_adapter,
                    capability_resolver=_case_capability,
                )
                future_to_group[future] = group
            for future in concurrent.futures.as_completed(future_to_group):
                group = future_to_group[future]
                try:
                    group_outcome = future.result()
                except Exception as exc:
                    group_outcome = _CaseExecutionGroupOutcome(
                        group=group,
                        case_outcomes=tuple(
                            _case_exception_outcome(
                                entry,
                                exc,
                                capability_resolver=_case_capability,
                            )
                            for entry in group.entries
                        ),
                        seeded_source_keys=frozenset(),
                        seeded_corpus_identities=frozenset(),
                        seed_stats=_BenchmarkSeedStats(),
                    )
                _merge_case_execution_group_outcome(
                    outcome=group_outcome,
                    seeded_source_keys=seeded_source_keys,
                    seeded_corpus_identities=seeded_corpus_identities,
                    seed_stats=seed_stats,
                )
                for outcome in group_outcome.case_outcomes:
                    entry = outcome.entry
                    if outcome.failure is not None:
                        failures.append(outcome.failure)
                        _emit_case_failed(
                            progress=progress,
                            entry=entry,
                            reason=str(outcome.failure["reason"]),
                            seeded_source_count=len(seeded_source_keys),
                            seed_cache_hit_count=seed_stats.seed_cache_hit_count,
                            effective_parallelism=effective_parallelism,
                        )
                    else:
                        _emit_case_completed(
                            progress=progress,
                            entry=entry,
                            result=outcome.result,
                            seeded_source_count=len(seeded_source_keys),
                            seed_cache_hit_count=seed_stats.seed_cache_hit_count,
                            effective_parallelism=effective_parallelism,
                        )
                    result_by_key[
                        case_result_key(outcome.result.benchmark, outcome.result.case_id)
                    ] = outcome.result
                    run_results[:] = _ordered_run_results(cases, result_by_key)
                    _emit_case_progress_snapshot(
                        progress=progress,
                        run_results=run_results,
                        failures=failures,
                        seeded_source_count=len(seeded_source_keys),
                        seed_stats=seed_stats,
                        effective_parallelism=effective_parallelism,
                    )
                    progress.checkpoint(
                        processed_case_count=len(run_results),
                        run_results=run_results,
                        failures=failures,
                        seeded_source_count=len(seeded_source_keys),
                        seed_stats=seed_stats,
                    )

    progress.event(
        "run_completed",
        total_case_count=len(cases),
        processed_case_count=len(run_results),
        processed_case_ratio=_ratio(len(run_results), len(cases)),
        **_progress_timing_fields(
            processed_case_count=len(run_results),
            total_case_count=len(cases),
            started=started,
        ),
        accuracy_so_far=_accuracy(run_results),
        capability_accuracy_so_far=_flat_capability_accuracy(run_results),
        capability_case_count_so_far=_flat_capability_case_count(run_results),
        capability_failure_count_so_far=_flat_capability_failure_count(run_results),
        **_progress_case_outcome_fields(
            processed_case_count=len(run_results),
            run_results=run_results,
            failures=failures,
            total_case_count=len(cases),
        ),
        seeded_source_count=len(seeded_source_keys),
        seed_source_attempt_count=seed_stats.source_attempt_count,
        seed_cache_hit_count=seed_stats.seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )
    progress.checkpoint(
        processed_case_count=len(cases),
        run_results=run_results,
        failures=failures,
        seeded_source_count=len(seeded_source_keys),
        seed_stats=seed_stats,
        force=True,
    )

    benchmarks = _benchmark_summaries(run_results, min_accuracy=min_accuracy)
    missing_case_ids = _case_selection_missing_case_ids(case_selection)
    missing_capabilities = _case_selection_missing_capabilities(case_selection)
    case_selection_failures = _missing_case_id_failures_for_selection(case_selection)
    unsupported_cases = _unsupported_case_reports_for_selection(case_selection)
    capability_selection_failures = _missing_capability_failures(missing_capabilities)
    benchmark_accuracy_ok = bool(run_results) and all(item["ok"] is True for item in benchmarks)
    unsupported_case_id_count = len(unsupported_cases)
    ok = (
        benchmark_accuracy_ok
        and not unsupported_cases
        and not case_selection_failures
        and not capability_selection_failures
    )
    case_keys = tuple(f"{case.benchmark}:{case.case_id}" for case in cases)
    result: dict[str, object] = {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark_scope": "normalized_public_memory_retrieval",
        "evaluation_mode": "retrieved_expected_terms",
        "dataset_path_label": dataset_path.name,
        "dataset_hash": dataset_hash,
        "requested_case_ids": list(requested_case_ids),
        "requested_capabilities": list(requested_capabilities),
        "case_selection": dict(case_selection or {}),
        "dataset_sources": {
            summary["name"]: _dataset_source_metadata(
                dataset_path=dataset_path,
                dataset_hash=dataset_hash,
                source_kind="local_dataset",
                case_count=_benchmark_summary_case_count(summary),
            )
            for summary in benchmarks
            if isinstance(summary.get("name"), str)
        },
        "checks": {
            "dataset_loaded": True,
            "case_count": len(run_results) > 0,
            "unique_case_ids": True,
            "minimum_accuracy_met": benchmark_accuracy_ok,
            "requested_case_ids_found": not case_selection_failures,
            "requested_case_ids_supported": unsupported_case_id_count == 0,
            "requested_capabilities_found": not missing_capabilities,
            "no_request_failures": (
                not failures and not case_selection_failures and not capability_selection_failures
            ),
        },
        "metrics": {
            "benchmark_count": len(benchmarks),
            **_run_metric_summary(run_results),
            "unique_case_id_count": len(set(case_keys)),
            "duplicate_case_id_count": 0,
            "missing_case_id_count": len(missing_case_ids),
            "unsupported_case_id_count": unsupported_case_id_count,
            "missing_capability_count": len(missing_capabilities),
            "seed_source_attempt_count": seed_stats.source_attempt_count,
            "seeded_source_count": len(seeded_source_keys),
            "seed_cache_hit_count": seed_stats.seed_cache_hit_count,
            "requested_parallelism": requested_parallelism,
            "effective_parallelism": effective_parallelism,
            "parallelism_degraded": parallelism_degraded_reason is not None,
            "parallelism_degraded_reason": parallelism_degraded_reason,
            "request_timeout_seconds": request_timeout_seconds,
            "checkpoint_min_interval_seconds": checkpoint_min_interval_seconds,
            "resumed_case_count": len(resumed_case_keys),
            "pending_case_count": len(pending_entries),
            "checkpoint_failed_case_requeued_count": resume_report[
                "checkpoint_failed_case_requeued_count"
            ],
            **_progress_timing_fields(
                processed_case_count=len(run_results),
                total_case_count=len(cases),
                started=started,
            ),
        },
        "resume": resume_report,
        "execution_manifest": execution_manifest,
        "benchmarks": benchmarks,
        "cases": [_case_payload(item) for item in run_results],
        "failures": (
            failures
            + case_selection_failures
            + capability_selection_failures
            + _case_failures(run_results)
        ),
        "unsupported_cases": unsupported_cases,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    for summary in benchmarks:
        name = summary["name"]
        metrics = summary.get("metrics", {})
        if isinstance(name, str) and isinstance(metrics, dict):
            result["metrics"][f"{name}_accuracy"] = metrics.get("accuracy")
            result["metrics"][f"{name}_case_count"] = metrics.get("case_count")
    return result


def _emit_case_progress_snapshot(
    *,
    progress: _BenchmarkProgress,
    run_results: Sequence[CaseRunResult],
    failures: Sequence[Mapping[str, object]],
    seeded_source_count: int,
    seed_stats: _BenchmarkSeedStats,
    effective_parallelism: int,
) -> None:
    processed_case_count = len(run_results)
    progress.event(
        "case_progress",
        processed_case_count=processed_case_count,
        total_case_count=progress.total_case_count,
        processed_case_ratio=_ratio(processed_case_count, progress.total_case_count),
        **_progress_timing_fields(
            processed_case_count=processed_case_count,
            total_case_count=progress.total_case_count,
            started=progress.started,
        ),
        accuracy_so_far=_accuracy(run_results),
        capability_accuracy_so_far=_flat_capability_accuracy(run_results),
        capability_case_count_so_far=_flat_capability_case_count(run_results),
        capability_failure_count_so_far=_flat_capability_failure_count(run_results),
        **_progress_case_outcome_fields(
            processed_case_count=processed_case_count,
            run_results=run_results,
            failures=failures,
            total_case_count=progress.total_case_count,
        ),
        seeded_source_count=seeded_source_count,
        seed_source_attempt_count=seed_stats.source_attempt_count,
        seed_cache_hit_count=seed_stats.seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )


def _bounded_case_id_details(cases: Iterable[PublicBenchmarkCase]) -> tuple[list[str], int]:
    case_ids = [f"{case.benchmark}:{case.case_id}"[:160] for case in cases]
    return (
        case_ids[:_MAX_RESUME_CASE_ID_DETAILS],
        max(0, len(case_ids) - _MAX_RESUME_CASE_ID_DETAILS),
    )


def _bounded_checkpoint_failure_case_id_details(
    failures: Sequence[Mapping[str, object]],
) -> tuple[list[str], int]:
    case_ids = [
        str(item.get("case_id"))[:160]
        for item in failures
        if str(item.get("case_id") or "").strip()
    ]
    return (
        case_ids[:_MAX_RESUME_CASE_ID_DETAILS],
        max(0, len(case_ids) - _MAX_RESUME_CASE_ID_DETAILS),
    )


def _normalize_request_timeout_seconds(value: float) -> float:
    if isinstance(value, bool) or value <= 0:
        raise BenchmarkValidationError("request_timeout_seconds must be greater than zero")
    return float(value)


def _normalize_checkpoint_min_interval_seconds(value: float) -> float:
    if isinstance(value, bool) or value < 0:
        raise BenchmarkValidationError(
            "checkpoint_min_interval_seconds must be greater than or equal to zero"
        )
    return float(value)


def _retrieval_contract_manifest() -> dict[str, object]:
    return {
        "context_token_budget": _PUBLIC_BENCHMARK_CONTEXT_TOKEN_BUDGET,
        "max_facts": _PUBLIC_BENCHMARK_MAX_FACTS,
        "max_chunks": _PUBLIC_BENCHMARK_MAX_CHUNKS,
        "max_reuse_detail_events_per_case": _PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE,
    }


def _run_case(
    *,
    adapter: BenchmarkHttpClientPort,
    headers: Mapping[str, str],
    scope_slug: str,
    dataset_hash: str,
    case: PublicBenchmarkCase,
    seeded_source_keys: set[tuple[str, str, str, str]],
    seeded_corpus_identities: set[tuple[str, str, str]],
    seed_corpus_metadata_cache: dict[tuple[int, int], _SeedCorpusMetadata],
    seed_stats: _BenchmarkSeedStats,
    progress: _BenchmarkProgress | None = None,
    case_index: int | None = None,
    total_case_count: int | None = None,
) -> CaseRunResult:
    memory_scope_ref = case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
    thread_ref = case.thread_external_ref or f"{case.benchmark}-{case.case_id}"
    corpus_identity = seed_corpus_identity(
        case,
        memory_scope_ref=memory_scope_ref,
        thread_ref=thread_ref,
    )
    corpus_metadata = seed_corpus_metadata(
        case,
        cache=seed_corpus_metadata_cache,
    )
    reused_source_count = 0
    reused_source_detail_event_count = 0
    reused_source_kind_counts: dict[str, int] = defaultdict(int)

    def record_reused_source(
        *,
        source_kind: str,
        source_index: int,
        source_id: str,
        source_type: str | None = None,
    ) -> None:
        nonlocal reused_source_count, reused_source_detail_event_count
        seed_stats.seed_cache_hit_count += 1
        reused_source_count += 1
        reused_source_kind_counts[source_kind] += 1
        if (
            progress is None
            or reused_source_detail_event_count
            >= _PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE
        ):
            return
        event_fields: dict[str, object] = {
            "case_index": case_index,
            "total_case_count": total_case_count,
            "case_id": case.case_id,
            "benchmark": case.benchmark,
            "source_kind": source_kind,
            "source_index": source_index,
            "source_id_hash": _short_hash(source_id),
            "seeded_source_count": len(seeded_source_keys),
            "seed_cache_hit_count": seed_stats.seed_cache_hit_count,
            "reuse_detail_event_index": reused_source_detail_event_count + 1,
            "reuse_detail_event_limit": _PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE,
        }
        if source_type:
            event_fields["source_type"] = source_type
        progress.event("source_seed_reused", **event_fields)
        reused_source_detail_event_count += 1

    if corpus_metadata.reusable_by_identity and corpus_identity in seeded_corpus_identities:
        seed_stats.source_attempt_count += corpus_metadata.source_count
        seed_stats.seed_cache_hit_count += corpus_metadata.source_count
        if progress is not None:
            progress.event(
                "source_seed_corpus_reused",
                case_index=case_index,
                total_case_count=total_case_count,
                case_id=case.case_id,
                benchmark=case.benchmark,
                reused_source_count=corpus_metadata.source_count,
                reused_source_kind_counts=dict(corpus_metadata.source_kind_counts),
                seeded_source_count=len(seeded_source_keys),
                seed_cache_hit_count=seed_stats.seed_cache_hit_count,
            )
    else:
        for index, memory in enumerate(case.memories):
            source_id = safe_identifier(
                memory.source_external_id or f"{dataset_hash}:{case.case_id}:memory:{index}",
                max_chars=160,
            )
            seed_key = (memory_scope_ref, thread_ref, "fact", source_id)
            seed_stats.source_attempt_count += 1
            if seed_key not in seeded_source_keys:
                if progress is not None:
                    progress.event(
                        "source_seed_started",
                        case_index=case_index,
                        total_case_count=total_case_count,
                        case_id=case.case_id,
                        benchmark=case.benchmark,
                        source_kind="fact",
                        source_index=index + 1,
                        source_id_hash=_short_hash(source_id),
                        payload_chars=len(memory.text),
                        seeded_source_count=len(seeded_source_keys),
                    )
                _post_required(
                    adapter,
                    "/v1/facts",
                    headers=headers,
                    payload={
                        "space_slug": scope_slug,
                        "memory_scope_external_ref": memory_scope_ref,
                        "thread_external_ref": thread_ref,
                        "text": memory.text,
                        "kind": memory.kind,
                        "source_refs": [
                            {
                                "source_type": "public_benchmark",
                                "source_id": source_id,
                                "quote_preview": memory.text[:240],
                            }
                        ],
                        "classification": "internal",
                    },
                    idempotency_key=source_id,
                )
                seeded_source_keys.add(seed_key)
                seed_stats.seeded_source_count = len(seeded_source_keys)
                if progress is not None:
                    progress.event(
                        "source_seed_completed",
                        case_index=case_index,
                        total_case_count=total_case_count,
                        case_id=case.case_id,
                        benchmark=case.benchmark,
                        source_kind="fact",
                        source_index=index + 1,
                        source_id_hash=_short_hash(source_id),
                        seeded_source_count=len(seeded_source_keys),
                    )
            else:
                record_reused_source(
                    source_kind="fact",
                    source_index=index + 1,
                    source_id=source_id,
                )

        for index, document in enumerate(case.documents):
            source_id = safe_identifier(
                document.source_external_id or f"{dataset_hash}:{case.case_id}:doc:{index}",
                max_chars=240,
            )
            seed_key = (memory_scope_ref, thread_ref, "document", source_id)
            seed_stats.source_attempt_count += 1
            if seed_key not in seeded_source_keys:
                if progress is not None:
                    progress.event(
                        "source_seed_started",
                        case_index=case_index,
                        total_case_count=total_case_count,
                        case_id=case.case_id,
                        benchmark=case.benchmark,
                        source_kind="document",
                        source_index=index + 1,
                        source_id_hash=_short_hash(source_id),
                        source_type=document.source_type,
                        payload_chars=len(document.text),
                        seeded_source_count=len(seeded_source_keys),
                    )
                _post_required(
                    adapter,
                    "/v1/documents",
                    headers=headers,
                    payload={
                        "space_slug": scope_slug,
                        "memory_scope_external_ref": memory_scope_ref,
                        "thread_external_ref": thread_ref,
                        "title": document.title,
                        "text": document.text,
                        "source_type": document.source_type,
                        "source_external_id": source_id,
                        "classification": document.classification,
                    },
                    idempotency_key=source_id,
                )
                seeded_source_keys.add(seed_key)
                seed_stats.seeded_source_count = len(seeded_source_keys)
                if progress is not None:
                    progress.event(
                        "source_seed_completed",
                        case_index=case_index,
                        total_case_count=total_case_count,
                        case_id=case.case_id,
                        benchmark=case.benchmark,
                        source_kind="document",
                        source_index=index + 1,
                        source_id_hash=_short_hash(source_id),
                        source_type=document.source_type,
                        seeded_source_count=len(seeded_source_keys),
                    )
            else:
                record_reused_source(
                    source_kind="document",
                    source_index=index + 1,
                    source_id=source_id,
                    source_type=document.source_type,
                )

        if corpus_metadata.reusable_by_identity:
            seeded_corpus_identities.add(corpus_identity)

    if progress is not None and reused_source_count:
        progress.event(
            "source_seed_reuse_summary",
            case_index=case_index,
            total_case_count=total_case_count,
            case_id=case.case_id,
            benchmark=case.benchmark,
            reused_source_count=reused_source_count,
            reused_source_kind_counts=dict(sorted(reused_source_kind_counts.items())),
            reuse_detail_event_count=reused_source_detail_event_count,
            reuse_detail_event_limit=_PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE,
            seeded_source_count=len(seeded_source_keys),
            seed_cache_hit_count=seed_stats.seed_cache_hit_count,
        )

    if progress is not None:
        progress.event(
            "context_request_started",
            case_index=case_index,
            total_case_count=total_case_count,
            case_id=case.case_id,
            benchmark=case.benchmark,
            seeded_source_count=len(seeded_source_keys),
        )
    started = time.perf_counter()
    response = _post_required(
        adapter,
        "/v1/context",
        headers=headers,
        payload={
            "space_slug": scope_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "thread_external_ref": thread_ref,
            "query": case.question,
            "token_budget": _PUBLIC_BENCHMARK_CONTEXT_TOKEN_BUDGET,
            "max_facts": _PUBLIC_BENCHMARK_MAX_FACTS,
            "max_chunks": _PUBLIC_BENCHMARK_MAX_CHUNKS,
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    if progress is not None:
        progress.event(
            "context_request_completed",
            case_index=case_index,
            total_case_count=total_case_count,
            case_id=case.case_id,
            benchmark=case.benchmark,
            latency_ms=latency_ms,
        )
    data = _response_data(response)
    evidence_text = _evidence_text(data)
    normalized_evidence = _normalize_text(evidence_text)
    covered_terms = tuple(
        term for term in case.expected_terms if _normalize_text(term) in normalized_evidence
    )
    missing = tuple(
        term for term in case.expected_terms if _normalize_text(term) not in normalized_evidence
    )
    leaked = tuple(
        term for term in case.forbidden_terms if _normalize_text(term) in normalized_evidence
    )
    items = data.get("items", [])
    item_ids = tuple(
        str(item.get("item_id")) for item in items if isinstance(item, dict) and item.get("item_id")
    )
    evidence_refs = _case_evidence_refs(case)
    covered_evidence_refs = tuple(
        ref for ref in evidence_refs if _normalize_text(ref) in normalized_evidence
    )
    missing_evidence_refs = tuple(
        ref for ref in evidence_refs if _normalize_text(ref) not in normalized_evidence
    )
    evidence_ref_previews = _case_evidence_ref_previews(case, refs=evidence_refs)
    missing_evidence_ref_previews = _case_evidence_ref_previews(
        case,
        refs=missing_evidence_refs,
    )
    return CaseRunResult(
        benchmark=case.benchmark,
        case_id=case.case_id,
        capability=_case_capability(case),
        ok=not missing and not leaked,
        expected_ok=not missing,
        forbidden_ok=not leaked,
        missing_terms=missing,
        leaked_terms=leaked,
        item_ids=item_ids,
        latency_ms=latency_ms,
        question_preview=_preview_value(case.question),
        answer_preview=_case_answer_preview(case),
        expected_terms_preview=_case_expected_terms_preview(case),
        evidence_refs=evidence_refs,
        evidence_ref_previews=evidence_ref_previews,
        covered_terms=covered_terms,
        covered_evidence_refs=covered_evidence_refs,
        missing_evidence_refs=missing_evidence_refs,
        missing_evidence_ref_previews=missing_evidence_ref_previews,
    )


def _load_cases(dataset_path: Path) -> tuple[PublicBenchmarkCase, ...]:
    if not dataset_path.exists():
        raise BenchmarkValidationError(f"Dataset does not exist: {dataset_path}")
    cases = _cases_from_payload(_load_dataset_payload(dataset_path))
    if not cases:
        raise BenchmarkValidationError("Dataset does not contain benchmark cases")
    return cases


def _load_dataset_payload(dataset_path: Path) -> object:
    text = dataset_path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return ()
    if stripped.startswith("[") or (stripped.startswith("{") and "\n" not in stripped):
        return json.loads(stripped)
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _cases_from_payload(payload: object) -> tuple[PublicBenchmarkCase, ...]:
    if isinstance(payload, Mapping):
        if _is_official_locomo_sample(payload):
            return _official_locomo_cases(payload)
        if _is_official_longmemeval_row(payload):
            return (_official_longmemeval_case(payload),)
        raw_cases = payload.get("cases") or payload.get("data") or payload.get("items")
        if raw_cases is not None:
            return _cases_from_payload(raw_cases)
        return (_normalize_case(payload),)

    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes):
        raise BenchmarkValidationError("Dataset root must be a case list, object or JSONL")

    cases: list[PublicBenchmarkCase] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if _is_official_locomo_sample(item):
            cases.extend(_official_locomo_cases(item))
        elif _is_official_longmemeval_row(item):
            cases.append(_official_longmemeval_case(item))
        else:
            cases.append(_normalize_case(item))
    return tuple(cases)


def _duplicate_case_keys(cases: Sequence[PublicBenchmarkCase]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for case in cases:
        key = f"{case.benchmark}:{case.case_id}"
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return tuple(duplicates)


def _is_official_locomo_sample(raw: Mapping[str, object]) -> bool:
    return isinstance(raw.get("conversation"), Mapping) and isinstance(raw.get("qa"), list)


def _official_locomo_cases(raw: Mapping[str, object]) -> tuple[PublicBenchmarkCase, ...]:
    sample_id = _first_str(raw, "sample_id", "id") or _case_hash(raw)
    documents = _official_locomo_documents(raw, sample_id=sample_id)
    evidence_lookup = _official_locomo_evidence_lookup(raw)
    raw_qas = raw.get("qa")
    cases: list[PublicBenchmarkCase] = []
    if not isinstance(raw_qas, Sequence) or isinstance(raw_qas, str | bytes):
        return ()
    for index, qa in enumerate(raw_qas):
        if not isinstance(qa, Mapping):
            continue
        question = _first_str(qa, "question", "query")
        evidence_terms = _official_locomo_evidence_terms(qa, evidence_lookup)
        expected_terms = evidence_terms or _official_locomo_supported_answer_terms(
            qa,
            documents=documents,
        )
        if not question or not expected_terms:
            continue
        category = qa.get("category")
        case_id = f"{sample_id}:qa:{index + 1}"
        cases.append(
            PublicBenchmarkCase(
                benchmark=LOCOMO_BENCHMARK_SUITE,
                case_id=case_id,
                question=question,
                expected_terms=expected_terms,
                documents=documents,
                memory_scope_external_ref=f"locomo-{sample_id}",
                thread_external_ref=f"locomo-{sample_id}",
                metadata={
                    "source_format": "official_locomo",
                    "sample_id": sample_id,
                    "qa_index": index,
                    "category": category,
                    "answer_preview": _preview_value(qa.get("answer")),
                    "evidence": qa.get("evidence") if isinstance(qa.get("evidence"), list) else [],
                    "evidence_previews": _official_locomo_evidence_previews(
                        qa,
                        evidence_lookup=evidence_lookup,
                    ),
                },
            )
        )
    return tuple(cases)


def _official_locomo_case_ids(raw: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(case.case_id for case in _official_locomo_cases(raw))


def _official_locomo_evidence_lookup(raw: Mapping[str, object]) -> dict[str, str]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return {}
    lookup: dict[str, str] = {}
    for key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(key):
            continue
        turns = conversation.get(key)
        if not isinstance(turns, Sequence) or isinstance(turns, str | bytes):
            continue
        for turn in turns:
            if not isinstance(turn, Mapping):
                continue
            dia_id = _first_str(turn, "dia_id", "id")
            evidence_text = "\n".join(_official_locomo_turn_evidence_parts(turn))
            if dia_id and evidence_text:
                lookup[dia_id] = evidence_text
    return lookup


def _official_locomo_turn_evidence_parts(turn: Mapping[str, object]) -> tuple[str, ...]:
    text = _first_str(turn, "text", "content", "utterance")
    caption = _first_str(turn, "blip_caption", "caption")
    visual_query = _first_str(turn, "query", "image_query", "visual_query")
    parts: list[str] = []
    if text:
        parts.append(text)
    if caption:
        parts.append(f"image caption: {caption}")
    if visual_query:
        parts.append(f"visual query: {visual_query}")
    return tuple(_unique(parts))


def _official_locomo_session_turns(
    raw: Mapping[str, object],
) -> dict[str, tuple[_OfficialLocomoTurn, ...]]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return {}
    turns_by_session: dict[str, tuple[_OfficialLocomoTurn, ...]] = {}
    for key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(key):
            continue
        turns = conversation.get(key)
        if not isinstance(turns, Sequence) or isinstance(turns, str | bytes):
            continue
        session_turns: list[_OfficialLocomoTurn] = []
        for index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                continue
            dia_id = _first_str(turn, "dia_id", "id")
            evidence_text = "\n".join(_official_locomo_turn_evidence_parts(turn))
            if not dia_id or not evidence_text:
                continue
            session_turns.append(
                _OfficialLocomoTurn(
                    session_key=key,
                    dia_id=dia_id,
                    speaker=_first_str(turn, "speaker", "role", "author") or "speaker",
                    text=evidence_text,
                    turn_index=index,
                )
            )
        if session_turns:
            turns_by_session[key] = tuple(session_turns)
    return turns_by_session


def _official_locomo_evidence_terms(
    qa: Mapping[str, object],
    evidence_lookup: Mapping[str, str],
) -> tuple[str, ...]:
    evidence = qa.get("evidence")
    terms: list[str] = []
    for item in _flatten_benchmark_scalar_values(evidence):
        evidence_id = str(item).strip()
        if evidence_id and evidence_id in evidence_lookup:
            terms.append(evidence_id)
    return tuple(_unique(terms))


def _official_locomo_evidence_previews(
    qa: Mapping[str, object],
    *,
    evidence_lookup: Mapping[str, str],
) -> dict[str, str]:
    previews: dict[str, str] = {}
    for item in _flatten_benchmark_scalar_values(qa.get("evidence")):
        evidence_id = str(item).strip()
        evidence_text = evidence_lookup.get(evidence_id)
        if evidence_id and evidence_text:
            previews[evidence_id] = _preview_value(evidence_text, max_chars=240)
    return previews


def _official_locomo_supported_answer_terms(
    qa: Mapping[str, object],
    *,
    documents: Sequence[BenchmarkDocumentInput],
) -> tuple[str, ...]:
    answer_terms = _terms(qa, "answer", "expected_answer", "answers")
    if not answer_terms:
        return ()
    searchable_text = _normalize_text("\n".join(document.text for document in documents))
    return tuple(term for term in answer_terms if _normalize_text(term) in searchable_text)


def _official_locomo_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(key):
            continue
        turns = conversation.get(key)
        if not isinstance(turns, Sequence) or isinstance(turns, str | bytes):
            continue
        date_value = conversation.get(f"{key}_date_time")
        lines = [f"{key} date: {date_value}"] if isinstance(date_value, str) else [key]
        for turn in turns:
            if not isinstance(turn, Mapping):
                continue
            dia_id = _first_str(turn, "dia_id", "id")
            speaker = _first_str(turn, "speaker", "role", "author") or "speaker"
            text = _first_str(turn, "text", "content", "utterance")
            prefix = f"{dia_id} " if dia_id else ""
            if text:
                lines.append(f"{prefix}{speaker}: {text}")
            caption = _first_str(turn, "blip_caption", "caption")
            if caption:
                lines.append(f"{prefix}{speaker} image caption: {caption}")
            visual_query = _first_str(turn, "query", "image_query", "visual_query")
            if visual_query:
                lines.append(f"{prefix}{speaker} visual query: {visual_query}")
        if len(lines) > 1:
            documents.append(
                BenchmarkDocumentInput(
                    title=f"LoCoMo {sample_id} {key}",
                    text="\n".join(lines),
                    source_type="locomo_session",
                    source_external_id=f"locomo:{sample_id}:{key}",
                )
            )
    documents.extend(_official_locomo_observation_documents(raw, sample_id=sample_id))
    documents.extend(_official_locomo_turn_documents(raw, sample_id=sample_id))
    documents.extend(_official_locomo_session_summary_documents(raw, sample_id=sample_id))
    documents.extend(_official_locomo_event_summary_documents(raw, sample_id=sample_id))
    return tuple(documents)


def _official_locomo_turn_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    turns_by_session = _official_locomo_session_turns(raw)
    documents: list[BenchmarkDocumentInput] = []
    conversation = raw.get("conversation")
    conversation_map = conversation if isinstance(conversation, Mapping) else {}
    for session_key in sorted(turns_by_session, key=_session_sort_key):
        date_value = conversation_map.get(f"{session_key}_date_time")
        for turn in turns_by_session[session_key]:
            lines = [f"{session_key} turn {turn.dia_id}"]
            if isinstance(date_value, str) and date_value.strip():
                lines.append(f"{session_key} date: {date_value.strip()}")
            lines.append(f"{turn.dia_id} {turn.speaker}: {turn.text}")
            documents.append(
                BenchmarkDocumentInput(
                    title=f"LoCoMo {sample_id} {session_key} turn {turn.dia_id}",
                    text="\n".join(lines),
                    source_type="locomo_turn",
                    source_external_id=(f"locomo:{sample_id}:{session_key}:{turn.dia_id}:turn"),
                )
            )
    return tuple(documents)


def _official_locomo_observation_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    observation = raw.get("observation")
    if not isinstance(observation, Mapping):
        return ()
    turns_by_session = _official_locomo_session_turns(raw)
    conversation = raw.get("conversation")
    conversation_map = conversation if isinstance(conversation, Mapping) else {}
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(observation, key=_session_sort_key):
        value = observation.get(key)
        if not isinstance(value, Mapping):
            continue
        session_key = key.removesuffix("_observation")
        session_turns = turns_by_session.get(session_key, ())
        lines = [f"{session_key} observations"]
        date_value = conversation_map.get(f"{session_key}_date_time")
        if isinstance(date_value, str) and date_value.strip():
            lines.append(f"{session_key} date: {date_value.strip()}")
        for actor, raw_items in value.items():
            actor_name = str(actor).strip() or "speaker"
            for item in _as_list(raw_items):
                text, evidence_ids = _official_locomo_observation_item(item)
                if not text or not evidence_ids:
                    continue
                evidence_id = evidence_ids[0]
                evidence_ids = _official_locomo_related_observation_evidence_ids(
                    text=text,
                    evidence_id=evidence_id,
                    explicit_evidence_ids=evidence_ids,
                    actor_name=actor_name,
                    session_turns=session_turns,
                )
                related_ids = tuple(item for item in evidence_ids if item != evidence_id)
                related_label = f" Related turns: {' '.join(related_ids)}." if related_ids else ""
                lines.append(f"{evidence_id} {actor_name}: {text}{related_label}")
        if len(lines) <= 1:
            continue
        documents.append(
            BenchmarkDocumentInput(
                title=f"LoCoMo {sample_id} {session_key} observations",
                text="\n".join(lines),
                source_type="locomo_observation",
                source_external_id=f"locomo:{sample_id}:{session_key}:observation",
            )
        )
    return tuple(documents)


def _official_locomo_related_observation_evidence_ids(
    *,
    text: str,
    evidence_id: str,
    explicit_evidence_ids: tuple[str, ...] = (),
    actor_name: str,
    session_turns: tuple[_OfficialLocomoTurn, ...],
) -> tuple[str, ...]:
    evidence_id = evidence_id.strip()
    if not evidence_id:
        return ()
    explicit_turn = next(
        (turn for turn in session_turns if turn.dia_id == evidence_id),
        None,
    )
    actor_key = actor_name.casefold().strip()
    ranked: list[tuple[tuple[int, int, int, int, int], _OfficialLocomoTurn]] = []
    for turn in session_turns:
        if turn.dia_id == evidence_id:
            continue
        if actor_key and turn.speaker.casefold().strip() != actor_key:
            continue
        relevance = _score_official_locomo_turn_relevance(query=text, turn_text=turn.text)
        if not _is_related_locomo_observation_turn(relevance):
            continue
        distance = (
            abs(turn.turn_index - explicit_turn.turn_index)
            if explicit_turn is not None
            else turn.turn_index
        )
        ranked.append(
            (
                (
                    -relevance.distinctive_term_hits,
                    -relevance.unique_term_hits,
                    -relevance.capped_frequency_hits,
                    distance,
                    turn.turn_index,
                ),
                turn,
            )
        )
    ranked.sort(key=lambda item: item[0])
    adjacent_ids = _official_locomo_adjacent_evidence_ids(
        explicit_turn=explicit_turn,
        session_turns=session_turns,
    )
    related_ids = tuple(turn.dia_id for _, turn in ranked[:3])
    session_order = {turn.dia_id: turn.turn_index for turn in session_turns}
    return tuple(
        sorted(
            _unique((evidence_id, *explicit_evidence_ids, *adjacent_ids, *related_ids)),
            key=lambda item: session_order.get(item, 10_000),
        )
    )


def _official_locomo_adjacent_evidence_ids(
    *,
    explicit_turn: _OfficialLocomoTurn | None,
    session_turns: tuple[_OfficialLocomoTurn, ...],
) -> tuple[str, ...]:
    if explicit_turn is None:
        return ()
    return tuple(
        turn.dia_id
        for turn in session_turns
        if turn.dia_id != explicit_turn.dia_id
        and turn.speaker.casefold().strip() == explicit_turn.speaker.casefold().strip()
        and explicit_turn.turn_index - 1 <= turn.turn_index <= explicit_turn.turn_index + 2
    )


def _is_related_locomo_observation_turn(relevance: QueryRelevance) -> bool:
    if relevance.unique_term_hits < 2:
        return False
    return relevance.distinctive_term_hits >= 2 or relevance.hit_ratio >= 0.2


def _official_locomo_observation_item(item: object) -> tuple[str, tuple[str, ...]]:
    if isinstance(item, Mapping):
        text = _first_str(item, "text", "content", "observation", "summary")
        evidence_ids = _official_locomo_observation_evidence_ids(item)
        return text or "", evidence_ids
    if isinstance(item, Sequence) and not isinstance(item, str | bytes):
        values = tuple(
            str(value).strip()
            for value in _flatten_benchmark_scalar_values(item)
            if str(value).strip()
        )
        if len(values) >= 2:
            return values[0], tuple(_unique(values[1:])[:_MAX_LOCOMO_OBSERVATION_EVIDENCE_IDS])
    return "", ()


def _official_locomo_observation_evidence_ids(item: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for key in (
        "dia_id",
        "evidence",
        "evidence_id",
        "evidence_ids",
        "id",
        "turn_id",
        "turn_ids",
    ):
        if key not in item:
            continue
        values.extend(
            str(value).strip()
            for value in _flatten_benchmark_scalar_values(item.get(key))
            if str(value).strip()
        )
        if values:
            break
    return tuple(_unique(values)[:_MAX_LOCOMO_OBSERVATION_EVIDENCE_IDS])


def _flatten_benchmark_scalar_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        return ()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        flattened: list[object] = []
        for item in value:
            flattened.extend(_flatten_benchmark_scalar_values(item))
        return tuple(flattened)
    return (value,) if value is not None else ()


def _official_locomo_session_summary_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    summaries = raw.get("session_summary")
    if not isinstance(summaries, Mapping):
        return ()
    conversation = raw.get("conversation")
    conversation_map = conversation if isinstance(conversation, Mapping) else {}
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(summaries, key=_session_sort_key):
        summary = summaries.get(key)
        if not isinstance(summary, str) or not summary.strip():
            continue
        session_key = key.removesuffix("_summary")
        lines = [f"{session_key} summary"]
        date_value = conversation_map.get(f"{session_key}_date_time")
        if isinstance(date_value, str) and date_value.strip():
            lines.append(f"{session_key} date: {date_value.strip()}")
        lines.append(summary.strip())
        documents.append(
            BenchmarkDocumentInput(
                title=f"LoCoMo {sample_id} {session_key} summary",
                text="\n".join(lines),
                source_type="locomo_session_summary",
                source_external_id=f"locomo:{sample_id}:{session_key}:summary",
            )
        )
    return tuple(documents)


def _official_locomo_event_summary_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    summaries = raw.get("event_summary")
    if not isinstance(summaries, Mapping):
        return ()
    turns_by_session = _official_locomo_session_turns(raw)
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(summaries, key=_session_sort_key):
        value = summaries.get(key)
        session_key = key.removeprefix("events_")
        session_turns = turns_by_session.get(session_key, ())
        lines = [f"{session_key} events"]
        if isinstance(value, Mapping):
            date = _first_str(value, "date", "session_date")
            if date:
                lines.append(f"date: {date}")
            for actor, raw_items in value.items():
                if str(actor).strip().lower() in {"date", "session_date"}:
                    continue
                actor_name = str(actor).strip() or "speaker"
                for item in _as_list(raw_items):
                    text = _official_locomo_event_summary_text(item)
                    if text:
                        evidence_ids = _official_locomo_related_event_summary_evidence_ids(
                            text=text,
                            actor_name=actor_name,
                            session_turns=session_turns,
                        )
                        evidence_label = " ".join(evidence_ids)
                        prefix = f"{evidence_label} " if evidence_label else ""
                        lines.append(f"{prefix}{actor_name}: {text}")
        else:
            text = _official_locomo_event_summary_text(value)
            if text:
                lines.append(text)
        if len(lines) <= 1:
            continue
        documents.append(
            BenchmarkDocumentInput(
                title=f"LoCoMo {sample_id} {session_key} events",
                text="\n".join(lines),
                source_type="locomo_event_summary",
                source_external_id=f"locomo:{sample_id}:{session_key}:events",
            )
        )
    return tuple(documents)


def _official_locomo_related_event_summary_evidence_ids(
    *,
    text: str,
    actor_name: str,
    session_turns: tuple[_OfficialLocomoTurn, ...],
) -> tuple[str, ...]:
    actor_key = actor_name.casefold().strip()
    ranked: list[tuple[tuple[int, int, int, int], _OfficialLocomoTurn]] = []
    for turn in session_turns:
        if actor_key and turn.speaker.casefold().strip() != actor_key:
            continue
        relevance = _score_official_locomo_turn_relevance(query=text, turn_text=turn.text)
        if not _is_related_locomo_observation_turn(relevance):
            continue
        ranked.append(
            (
                (
                    -relevance.distinctive_term_hits,
                    -relevance.unique_term_hits,
                    -relevance.capped_frequency_hits,
                    turn.turn_index,
                ),
                turn,
            )
        )
    ranked.sort(key=lambda item: item[0])
    session_order = {turn.dia_id: turn.turn_index for turn in session_turns}
    return tuple(
        sorted(
            _unique(turn.dia_id for _, turn in ranked[:4]),
            key=lambda item: session_order.get(item, 10_000),
        )
    )


def _score_official_locomo_turn_relevance(
    *,
    query: str,
    turn_text: str,
) -> QueryRelevance:
    text_counts, text_variants = _official_locomo_turn_text_variant_profile(turn_text)
    return score_query_relevance_against_profile(
        query=query,
        text_counts=text_counts,
        text_variants=text_variants,
    )


@lru_cache(maxsize=8192)
def _official_locomo_turn_text_variant_profile(
    turn_text: str,
) -> tuple[Mapping[str, int], tuple[tuple[str, ...], ...]]:
    return text_variant_profile(turn_text)


def _official_locomo_event_summary_text(item: object) -> str:
    if isinstance(item, str) and item.strip():
        return item.strip()
    if isinstance(item, Mapping):
        return _first_str(item, "text", "content", "event", "summary") or ""
    if isinstance(item, Sequence) and not isinstance(item, str | bytes):
        return " ".join(str(value).strip() for value in item if str(value).strip())
    return ""


def _is_session_key(value: object) -> bool:
    return (
        isinstance(value, str) and value.startswith("session_") and not value.endswith("_date_time")
    )


def _session_sort_key(value: object) -> tuple[int, str]:
    if not isinstance(value, str):
        return (10**9, "")
    if _is_session_key(value):
        try:
            return (int(value.rsplit("_", 1)[1]), value)
        except ValueError:
            return (10**9, value)
    return (10**9, value)


def _is_official_longmemeval_row(raw: Mapping[str, object]) -> bool:
    return (
        isinstance(raw.get("haystack_sessions"), list)
        and isinstance(raw.get("question"), str)
        and raw.get("answer") is not None
    )


def _official_longmemeval_case(raw: Mapping[str, object]) -> PublicBenchmarkCase:
    question_id = _first_str(raw, "question_id", "id") or _case_hash(raw)
    question = _first_str(raw, "question", "query")
    expected_terms = _official_longmemeval_evidence_terms(raw) or _terms(
        raw,
        "answer",
        "expected_answer",
        "answers",
    )
    if not question or not expected_terms:
        raise BenchmarkValidationError(f"LongMemEval row {question_id} is missing question/answer")
    return PublicBenchmarkCase(
        benchmark=LONGMEMEVAL_BENCHMARK_SUITE,
        case_id=question_id,
        question=question,
        expected_terms=expected_terms,
        documents=_official_longmemeval_documents(raw, question_id=question_id),
        memory_scope_external_ref=f"longmemeval-{question_id}",
        thread_external_ref=f"longmemeval-{question_id}",
        metadata={
            "source_format": "official_longmemeval",
            "question_type": raw.get("question_type"),
            "question_date": raw.get("question_date"),
            "answer_preview": _preview_value(raw.get("answer")),
            "answer_session_ids": raw.get("answer_session_ids")
            if isinstance(raw.get("answer_session_ids"), list)
            else [],
        },
    )


def _official_longmemeval_evidence_terms(raw: Mapping[str, object]) -> tuple[str, ...]:
    answer_session_ids = tuple(
        item.strip()
        for item in _as_list(raw.get("answer_session_ids"))
        if isinstance(item, str) and item.strip()
    )
    if not answer_session_ids:
        return ()
    haystack_session_ids = {
        item.strip()
        for item in _as_list(raw.get("haystack_session_ids"))
        if isinstance(item, str) and item.strip()
    }
    if not haystack_session_ids:
        return tuple(_unique(answer_session_ids))
    return tuple(_unique(item for item in answer_session_ids if item in haystack_session_ids))


def _official_longmemeval_documents(
    raw: Mapping[str, object],
    *,
    question_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    sessions = raw.get("haystack_sessions")
    if not isinstance(sessions, Sequence) or isinstance(sessions, str | bytes):
        return ()
    dates = raw.get("haystack_dates")
    session_ids = raw.get("haystack_session_ids")
    documents: list[BenchmarkDocumentInput] = []
    for index, session in enumerate(sessions):
        session_id = _sequence_str(session_ids, index) or f"session-{index + 1}"
        date_value = _sequence_str(dates, index)
        lines = [f"{session_id} date: {date_value}"] if date_value else [session_id]
        for message in _as_list(session):
            if isinstance(message, Mapping):
                role = _first_str(message, "role", "speaker", "author") or "speaker"
                content = _first_str(message, "content", "text", "message")
                if content:
                    lines.append(f"{role}: {content}")
            elif isinstance(message, str) and message.strip():
                lines.append(message.strip())
        if len(lines) > 1:
            documents.append(
                BenchmarkDocumentInput(
                    title=f"LongMemEval {question_id} {session_id}",
                    text="\n".join(lines),
                    source_type="longmemeval_session",
                    source_external_id=f"longmemeval:{question_id}:{session_id}",
                )
            )
    return tuple(documents)


def _sequence_str(value: object, index: int) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    if index >= len(value):
        return None
    item = value[index]
    return item.strip() if isinstance(item, str) and item.strip() else None


def _normalize_case(raw: Mapping[str, object]) -> PublicBenchmarkCase:
    benchmark = _normalize_benchmark_name(
        _first_str(raw, "benchmark", "source_benchmark", "dataset", "source")
    )
    case_id = _first_str(raw, "case_id", "qa_id", "uid", "id", "sample_id") or _case_hash(raw)
    question = _question(raw)
    expected_terms = _terms(raw, "expected_terms", "expected", "answer_terms")
    if not expected_terms:
        expected_terms = _terms(raw, "answer", "expected_answer", "ground_truth", "gold_answer")
    forbidden_terms = _terms(raw, "forbidden_terms", "forbidden", "must_not_retrieve")
    is_abstention_case = _is_normalized_abstention_case(raw)
    if is_abstention_case:
        expected_terms = ()
    memories = _memory_inputs(raw)
    documents = _document_inputs(raw)
    if not question:
        raise BenchmarkValidationError(f"Case {case_id} is missing question")
    if not expected_terms and not is_abstention_case:
        raise BenchmarkValidationError(f"Case {case_id} is missing expected_terms or answer")
    if is_abstention_case and not forbidden_terms:
        raise BenchmarkValidationError(
            f"Case {case_id} is missing forbidden_terms for abstention evaluation"
        )
    if not memories and not documents:
        raise BenchmarkValidationError(f"Case {case_id} is missing memories/documents")
    metadata = dict(_metadata(raw))
    metadata.setdefault(
        "answer_preview",
        _preview_value(
            _first_present(raw, "answer", "expected_answer", "ground_truth", "gold_answer")
        ),
    )
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        forbidden_terms=forbidden_terms,
        memories=memories,
        documents=documents,
        memory_scope_external_ref=_first_str(
            raw, "memory_scope_external_ref", "user_id", "memory_scope_id"
        ),
        thread_external_ref=_first_str(raw, "thread_external_ref", "thread_id", "session_id"),
        metadata=metadata,
    )


def _is_normalized_abstention_case(raw: Mapping[str, object]) -> bool:
    qa = raw.get("qa")
    return _mapping_requests_abstention(raw) or (
        isinstance(qa, Mapping) and _mapping_requests_abstention(qa)
    )


def _mapping_requests_abstention(raw: Mapping[str, object]) -> bool:
    for key in ("answerable", "is_answerable", "has_answer"):
        if raw.get(key) is False:
            return True
    for key in ("abstention", "no_answer", "unanswerable", "hard_negative"):
        if raw.get(key) is True:
            return True
    return False


def _normalize_benchmark_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkValidationError("Benchmark name is required")
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"locomo", "lo-co-mo", "long-context-memory"}:
        return LOCOMO_BENCHMARK_SUITE
    if normalized in {"longmemeval", "longmem-eval", "long-memory-eval"}:
        return LONGMEMEVAL_BENCHMARK_SUITE
    raise BenchmarkValidationError(f"Unsupported benchmark: {value}")


def _question(raw: Mapping[str, object]) -> str:
    direct = _first_str(raw, "question", "query", "input")
    if direct:
        return direct
    qa = raw.get("qa")
    if isinstance(qa, Mapping):
        return _first_str(qa, "question", "query", "input") or ""
    return ""


def _terms(raw: Mapping[str, object], *keys: str) -> tuple[str, ...]:
    terms: list[str] = []
    for key in keys:
        value = raw.get(key)
        terms.extend(_term_values(value))
        if terms:
            break
    qa = raw.get("qa")
    if not terms and isinstance(qa, Mapping):
        for key in keys:
            terms.extend(_term_values(qa.get(key)))
            if terms:
                break
    return tuple(_unique(terms))


def _term_values(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, int | float | bool):
        return [str(value)]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [
            str(item).strip()
            for item in _flatten_benchmark_scalar_values(value)
            if str(item).strip()
        ]
    return []


def _memory_inputs(raw: Mapping[str, object]) -> tuple[BenchmarkMemoryInput, ...]:
    values = _first_present(raw, "memories", "facts", "conversation", "messages", "history")
    entries: list[BenchmarkMemoryInput] = []
    for index, value in enumerate(_as_list(values)):
        if isinstance(value, str) and value.strip():
            entries.append(BenchmarkMemoryInput(text=value.strip()))
        elif isinstance(value, Mapping):
            text = _first_str(value, "text", "content", "message", "utterance")
            speaker = _first_str(value, "speaker", "role", "author")
            kind = _first_str(value, "kind", "memory_kind") or "note"
            if text:
                prefix = f"{speaker}: " if speaker else ""
                entries.append(BenchmarkMemoryInput(text=f"{prefix}{text}", kind=kind))
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            nested = " ".join(str(item).strip() for item in value if str(item).strip())
            if nested:
                entries.append(BenchmarkMemoryInput(text=f"session {index}: {nested}"))
    return tuple(entries)


def _document_inputs(raw: Mapping[str, object]) -> tuple[BenchmarkDocumentInput, ...]:
    values = _first_present(raw, "documents", "chunks", "passages", "haystack", "context")
    docs: list[BenchmarkDocumentInput] = []
    for index, value in enumerate(_as_list(values)):
        if isinstance(value, str) and value.strip():
            docs.append(BenchmarkDocumentInput(title=f"benchmark document {index + 1}", text=value))
        elif isinstance(value, Mapping):
            text = _first_str(value, "text", "content", "body", "passage")
            if not text:
                continue
            title = (
                _first_str(value, "title", "name", "session_id")
                or f"benchmark document {index + 1}"
            )
            docs.append(BenchmarkDocumentInput(title=title, text=text))
    return tuple(docs)


def _first_present(raw: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _first_str(raw: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _metadata(raw: Mapping[str, object]) -> Mapping[str, object]:
    value = raw.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _case_capability(case: PublicBenchmarkCase) -> str:
    if case.benchmark == LONGMEMEVAL_BENCHMARK_SUITE:
        question_type = case.metadata.get("question_type")
        return _longmemeval_capability(question_type)
    if case.benchmark == LOCOMO_BENCHMARK_SUITE:
        return _locomo_capability(case.metadata.get("category"))
    value = case.metadata.get("capability")
    return _safe_metric_key(value) if isinstance(value, str) else ""


def _longmemeval_capability(value: object) -> str:
    normalized = _safe_metric_key(value)
    if not normalized:
        return ""
    return {
        "single_session_user": "information_extraction",
        "single_session_assistant": "information_extraction",
        "single_session_preference": "information_extraction",
        "multi_session": "multi_session_reasoning",
        "temporal_reasoning": "temporal_reasoning",
        "knowledge_update": "knowledge_update",
    }.get(normalized, normalized)


def _locomo_capability(value: object) -> str:
    if isinstance(value, int):
        return f"locomo_category_{value}"
    if isinstance(value, float) and value.is_integer():
        return f"locomo_category_{int(value)}"
    normalized = _safe_metric_key(value)
    return f"locomo_{normalized}" if normalized else ""


def _safe_metric_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    return "".join(char for char in normalized if char.isalnum() or char == "_").strip("_")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _dataset_hash(dataset_path: Path) -> str:
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _case_hash(raw: Mapping[str, object]) -> str:
    encoded = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_values.append(value.strip())
    return unique_values
