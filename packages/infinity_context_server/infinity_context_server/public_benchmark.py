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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    score_query_relevance,
)
from infinity_context_core.reporting import with_report_provenance

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
)
from infinity_context_server.public_benchmark_checkpoint import (
    SeedCorpusMetadata as _SeedCorpusMetadata,
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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_MEMORY_BENCHMARK_SUITE = "public-memory-benchmark"
LOCOMO_BENCHMARK_SUITE = "locomo"
LONGMEMEVAL_BENCHMARK_SUITE = "longmemeval"
SUPPORTED_BENCHMARKS = frozenset({LOCOMO_BENCHMARK_SUITE, LONGMEMEVAL_BENCHMARK_SUITE})
CASE_SELECTION_FIRST = "first"
CASE_SELECTION_STRATIFIED = "stratified"
SUPPORTED_CASE_SELECTION_STRATEGIES = frozenset(
    {CASE_SELECTION_FIRST, CASE_SELECTION_STRATIFIED}
)
_DEFAULT_MIN_ACCURACY = 0.85
_PUBLIC_BENCHMARK_CONTEXT_TOKEN_BUDGET = 4000
_PUBLIC_BENCHMARK_MAX_FACTS = 20
_PUBLIC_BENCHMARK_MAX_CHUNKS = 50
_PUBLIC_BENCHMARK_MAX_REUSE_DETAIL_EVENTS_PER_CASE = 3


class BenchmarkValidationError(ValueError):
    """Raised when a benchmark dataset cannot be normalized safely."""


class BenchmarkHttpClientPort(Protocol):
    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        """Execute an HTTP POST through the chosen transport."""


class BenchmarkHttpResponsePort(Protocol):
    status_code: int
    text: str

    def json(self) -> Any:
        """Return decoded JSON response body."""


@dataclass(frozen=True)
class BenchmarkMemoryInput:
    text: str
    kind: str = "note"
    source_external_id: str | None = None


@dataclass(frozen=True)
class BenchmarkDocumentInput:
    title: str
    text: str
    source_type: str = "benchmark_document"
    classification: str = "internal"
    source_external_id: str | None = None


@dataclass(frozen=True)
class PublicBenchmarkCase:
    benchmark: str
    case_id: str
    question: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    memories: tuple[BenchmarkMemoryInput, ...] = ()
    documents: tuple[BenchmarkDocumentInput, ...] = ()
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _OfficialLocomoTurn:
    session_key: str
    dia_id: str
    speaker: str
    text: str
    turn_index: int


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

    def event(self, event_type: str, **fields: object) -> None:
        if self.progress_out is None:
            return
        payload: dict[str, object] = {
            "schema_version": "public-benchmark-progress-v1",
            "event_type": event_type,
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
        seed_stats: _BenchmarkSeedStats | None = None,
        force: bool = False,
    ) -> None:
        if self.checkpoint_out is None:
            return
        interval = max(1, self.checkpoint_every_cases)
        if (
            not force
            and processed_case_count < self.total_case_count
            and processed_case_count % interval != 0
        ):
            return
        payload = {
            "schema_version": "public-benchmark-checkpoint-v1",
            "status": (
                "completed"
                if processed_case_count >= self.total_case_count
                else "running"
            ),
            "dataset_path_label": self.dataset_path.name,
            "dataset_hash": self.dataset_hash,
            "case_selection": dict(self.case_selection or {}),
            "progress": {
                "processed_case_count": processed_case_count,
                "total_case_count": self.total_case_count,
                "processed_case_ratio": _ratio(
                    min(processed_case_count, self.total_case_count),
                    self.total_case_count,
                ),
                "seeded_source_count": seeded_source_count,
                "seed_source_attempt_count": (
                    seed_stats.source_attempt_count if seed_stats is not None else 0
                ),
                "seed_cache_hit_count": (
                    seed_stats.seed_cache_hit_count if seed_stats is not None else 0
                ),
                "failure_count": len(failures),
                "elapsed_ms": round((time.perf_counter() - self.started) * 1000, 2),
            },
            "metrics_so_far": {
                "case_count": len(run_results),
                "accuracy": _accuracy(run_results),
                "latency_ms_p95": _p95([item.latency_ms for item in run_results]),
            },
            "cases": [_case_payload(item) for item in run_results],
            "failures": list(failures),
            "recent_cases": [_case_payload(item) for item in run_results[-20:]],
            "recent_failures": list(failures[-20:]),
        }
        self.checkpoint_out.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.checkpoint_out, payload)


class _TestClientBenchmarkAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        return self._client.post(path, json=dict(json_body), headers=dict(headers))


class _HttpBenchmarkAdapter:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        return self._client.post(path, json=dict(json_body), headers=dict(headers))


def run_public_memory_benchmark(
    *,
    dataset_path: Path,
    api_url: str | None = None,
    auth_token: str | None = None,
    report_out: Path | None = None,
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
    checkpoint_every_cases: int = 25,
    local_state_dir: Path | None = None,
    benchmark: str | None = None,
    min_accuracy: float = _DEFAULT_MIN_ACCURACY,
    max_cases: int | None = None,
    case_selection_strategy: str = CASE_SELECTION_FIRST,
    resume_from_checkpoint: bool = False,
    parallelism: int = 1,
) -> dict[str, object]:
    """Run normalized public memory cases and optionally write a JSON report."""

    started = time.perf_counter()
    cases = _load_cases(dataset_path)
    if benchmark:
        canonical_benchmark = _normalize_benchmark_name(benchmark)
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    cases, case_selection = _select_cases(
        cases,
        max_cases=max_cases,
        strategy=case_selection_strategy,
    )

    duplicate_case_keys = _duplicate_case_keys(cases)
    if duplicate_case_keys:
        result = _duplicate_case_failure_result(
            cases=cases,
            duplicate_case_keys=duplicate_case_keys,
        )
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        result["case_selection"] = case_selection
        _write_report(result, report_out)
        return result

    if not cases:
        result = {
            "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
            "status": "failed",
            "ok": False,
            "checks": {
                "dataset_loaded": False,
                "case_count": False,
            },
            "metrics": {
                "case_count": 0,
                "benchmark_count": 0,
                "accuracy": 0.0,
            },
            "benchmarks": [],
            "cases": [],
            "failures": [
                {
                    "case_id": "dataset",
                    "category": "setup",
                    "reason": "no_supported_cases",
                }
            ],
            "case_selection": case_selection,
        }
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        _write_report(result, report_out)
        return result

    token = auth_token or (_default_service_token() if api_url else "test-token")
    if not token:
        result = _setup_failure_result(reason="auth_token_required", case_count=len(cases))
        result = _with_public_benchmark_provenance(result, dataset_path=dataset_path)
        result["case_selection"] = case_selection
        _write_report(result, report_out)
        return result

    if api_url:
        with httpx.Client(base_url=api_url.rstrip("/"), timeout=30.0) as http_client:
            adapter: BenchmarkHttpClientPort = _HttpBenchmarkAdapter(http_client)
            result = _execute_cases(
                adapter=adapter,
                headers=_auth_headers(token),
                cases=cases,
                dataset_path=dataset_path,
                min_accuracy=min_accuracy,
                started=started,
                case_selection=case_selection,
                progress_out=progress_out,
                checkpoint_out=checkpoint_out,
                checkpoint_every_cases=checkpoint_every_cases,
                resume_from_checkpoint=resume_from_checkpoint,
                parallelism=parallelism,
            )
    else:
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
                    progress_out=progress_out,
                    checkpoint_out=checkpoint_out,
                    checkpoint_every_cases=checkpoint_every_cases,
                    resume_from_checkpoint=(
                        resume_from_checkpoint and local_state_dir is not None
                    ),
                    parallelism=parallelism,
                    force_sequential_reason="local_in_process_transport",
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
    progress_out: Path | None = None,
    checkpoint_out: Path | None = None,
    checkpoint_every_cases: int = 25,
    resume_from_checkpoint: bool = False,
    parallelism: int = 1,
    force_sequential_reason: str | None = None,
) -> dict[str, object]:
    requested_parallelism = _normalize_parallelism(
        parallelism,
        error_factory=BenchmarkValidationError,
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
    )

    progress.event(
        "run_started",
        total_case_count=len(cases),
        benchmark_count=len({case.benchmark for case in cases}),
        requested_parallelism=requested_parallelism,
    )
    resumed_case_keys: set[tuple[str, str]] = set()
    resume_report: dict[str, object] = {
        "requested": resume_from_checkpoint,
        "status": "disabled",
        "reason": "not_requested",
        "resumed_case_count": 0,
        "selected_case_count": len(cases),
        "checkpoint_case_count": 0,
    }
    if resume_from_checkpoint:
        resume_load = load_checkpoint_resume_state_with_diagnostics(
            checkpoint_out=checkpoint_out,
            dataset_hash=dataset_hash,
            case_selection=case_selection,
            cases=cases,
        )
        resume_report = {
            "requested": True,
            "status": resume_load.status,
            "reason": resume_load.reason,
            "resumed_case_count": 0,
            "selected_case_count": resume_load.selected_case_count,
            "checkpoint_case_count": resume_load.checkpoint_case_count,
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
                resumed_case_count=len(resumed_case_keys),
                checkpoint_case_count=resume_load.checkpoint_case_count,
                seeded_source_count=len(seeded_source_keys),
                seed_source_attempt_count=seed_stats.source_attempt_count,
                seed_cache_hit_count=seed_stats.seed_cache_hit_count,
            )
        else:
            progress.event(
                "run_resume_skipped",
                reason=resume_load.reason,
                selected_case_count=resume_load.selected_case_count,
                checkpoint_case_count=resume_load.checkpoint_case_count,
            )
    pending_entries = tuple(
        _CaseExecutionEntry(case_index=case_index, case=case)
        for case_index, case in enumerate(cases, start=1)
        if case_result_key(case.benchmark, case.case_id) not in resumed_case_keys
    )
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
        requested_parallelism=requested_parallelism,
        effective_parallelism=effective_parallelism,
        parallelism_degraded_reason=parallelism_degraded_reason,
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
            case_result_key(result.benchmark, result.case_id): result
            for result in run_results
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
        failure_count=len(failures),
        seeded_source_count=len(seeded_source_keys),
        seed_cache_hit_count=seed_stats.seed_cache_hit_count,
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
    accuracy = _accuracy(run_results)
    ok = bool(run_results) and all(item["ok"] is True for item in benchmarks)
    case_keys = tuple(f"{case.benchmark}:{case.case_id}" for case in cases)
    result: dict[str, object] = {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark_scope": "normalized_public_memory_retrieval",
        "evaluation_mode": "retrieved_expected_terms",
        "dataset_path_label": dataset_path.name,
        "dataset_hash": dataset_hash,
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
            "minimum_accuracy_met": ok,
            "no_request_failures": not failures,
        },
        "metrics": {
            "benchmark_count": len(benchmarks),
            "case_count": len(run_results),
            "unique_case_id_count": len(set(case_keys)),
            "duplicate_case_id_count": 0,
            "accuracy": accuracy,
            "latency_ms_p95": _p95([item.latency_ms for item in run_results]),
            "seed_source_attempt_count": seed_stats.source_attempt_count,
            "seeded_source_count": len(seeded_source_keys),
            "seed_cache_hit_count": seed_stats.seed_cache_hit_count,
            "requested_parallelism": requested_parallelism,
            "effective_parallelism": effective_parallelism,
            "parallelism_degraded": parallelism_degraded_reason is not None,
            "parallelism_degraded_reason": parallelism_degraded_reason,
            "resumed_case_count": len(resumed_case_keys),
            "pending_case_count": len(pending_entries),
        },
        "resume": resume_report,
        "benchmarks": benchmarks,
        "cases": [_case_payload(item) for item in run_results],
        "failures": failures + _case_failures(run_results),
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
        accuracy_so_far=_accuracy(run_results),
        failure_count=len(failures),
        seeded_source_count=seeded_source_count,
        seed_source_attempt_count=seed_stats.source_attempt_count,
        seed_cache_hit_count=seed_stats.seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )


def _select_cases(
    cases: Sequence[PublicBenchmarkCase],
    *,
    max_cases: int | None,
    strategy: str,
) -> tuple[tuple[PublicBenchmarkCase, ...], dict[str, object]]:
    normalized_strategy = _normalize_case_selection_strategy(strategy)
    available = tuple(cases)
    if max_cases is not None and max_cases < 1:
        raise BenchmarkValidationError("max_cases must be greater than zero")
    if max_cases is None or max_cases >= len(available):
        selected = available
    elif normalized_strategy == CASE_SELECTION_FIRST:
        selected = available[:max_cases]
    else:
        selected = _stratified_case_selection(available, max_cases=max_cases)
    return selected, _case_selection_report(
        available=available,
        selected=selected,
        max_cases=max_cases,
        strategy=normalized_strategy,
    )


def _normalize_case_selection_strategy(value: str) -> str:
    normalized = (value or "").strip().lower().replace("_", "-")
    if normalized in {"", CASE_SELECTION_FIRST}:
        return CASE_SELECTION_FIRST
    if normalized == CASE_SELECTION_STRATIFIED:
        return CASE_SELECTION_STRATIFIED
    raise BenchmarkValidationError(f"Unsupported case selection strategy: {value}")


def _stratified_case_selection(
    cases: Sequence[PublicBenchmarkCase],
    *,
    max_cases: int,
) -> tuple[PublicBenchmarkCase, ...]:
    grouped: dict[str, list[PublicBenchmarkCase]] = defaultdict(list)
    for case in cases:
        grouped[_case_selection_group(case)].append(case)
    selected: list[PublicBenchmarkCase] = []
    round_index = 0
    ordered_groups = sorted(grouped)
    while len(selected) < max_cases:
        added = False
        for group in ordered_groups:
            group_cases = grouped[group]
            if round_index >= len(group_cases):
                continue
            selected.append(group_cases[round_index])
            added = True
            if len(selected) >= max_cases:
                break
        if not added:
            break
        round_index += 1
    return tuple(selected)


def _case_selection_report(
    *,
    available: Sequence[PublicBenchmarkCase],
    selected: Sequence[PublicBenchmarkCase],
    max_cases: int | None,
    strategy: str,
) -> dict[str, object]:
    available_counts = _case_selection_counts(available)
    selected_counts = _case_selection_counts(selected)
    return {
        "schema_version": "public-benchmark-case-selection-v1",
        "strategy": strategy,
        "requested_max_cases": max_cases,
        "input_case_count": len(available),
        "selected_case_count": len(selected),
        "truncated": len(selected) < len(available),
        "available_capability_count": len(available_counts),
        "selected_capability_count": len(selected_counts),
        "available_capability_counts": available_counts,
        "selected_capability_counts": selected_counts,
    }


def _case_selection_counts(
    cases: Sequence[PublicBenchmarkCase],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for case in cases:
        counts[_case_selection_group(case)] += 1
    return dict(sorted(counts.items()))


def _case_selection_group(case: PublicBenchmarkCase) -> str:
    capability = _case_capability(case)
    return f"{case.benchmark}:{capability or 'uncategorized'}"


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

    if (
        corpus_metadata.reusable_by_identity
        and corpus_identity in seeded_corpus_identities
    ):
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
                memory.source_external_id
                or f"{dataset_hash}:{case.case_id}:memory:{index}",
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
                document.source_external_id
                or f"{dataset_hash}:{case.case_id}:doc:{index}",
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
                    "evidence": qa.get("evidence") if isinstance(qa.get("evidence"), list) else [],
                },
            )
        )
    return tuple(cases)


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
    for item in _as_list(evidence):
        if not isinstance(item, str):
            continue
        evidence_id = item.strip()
        if evidence_id and evidence_id in evidence_lookup:
            terms.append(evidence_id)
    return tuple(_unique(terms))


def _official_locomo_supported_answer_terms(
    qa: Mapping[str, object],
    *,
    documents: Sequence[BenchmarkDocumentInput],
) -> tuple[str, ...]:
    answer_terms = _terms(qa, "answer", "expected_answer", "answers")
    if not answer_terms:
        return ()
    searchable_text = _normalize_text("\n".join(document.text for document in documents))
    return tuple(
        term for term in answer_terms if _normalize_text(term) in searchable_text
    )


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
                    source_external_id=(
                        f"locomo:{sample_id}:{session_key}:{turn.dia_id}:turn"
                    ),
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
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(observation, key=_session_sort_key):
        value = observation.get(key)
        if not isinstance(value, Mapping):
            continue
        session_key = key.removesuffix("_observation")
        session_turns = turns_by_session.get(session_key, ())
        lines = [f"{session_key} observations"]
        for actor, raw_items in value.items():
            actor_name = str(actor).strip() or "speaker"
            for item in _as_list(raw_items):
                text, evidence_id = _official_locomo_observation_item(item)
                if not text or not evidence_id:
                    continue
                evidence_ids = _official_locomo_related_observation_evidence_ids(
                    text=text,
                    evidence_id=evidence_id,
                    actor_name=actor_name,
                    session_turns=session_turns,
                )
                evidence_label = " ".join(evidence_ids)
                lines.append(f"{evidence_label} {actor_name}: {text}")
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
        relevance = score_query_relevance(query=text, text=turn.text)
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
    related_ids = tuple(turn.dia_id for _, turn in ranked[:3])
    session_order = {turn.dia_id: turn.turn_index for turn in session_turns}
    return tuple(
        sorted(
            _unique((evidence_id, *related_ids)),
            key=lambda item: session_order.get(item, 10_000),
        )
    )


def _is_related_locomo_observation_turn(relevance: QueryRelevance) -> bool:
    if relevance.unique_term_hits < 2:
        return False
    return relevance.distinctive_term_hits >= 2 or relevance.hit_ratio >= 0.2


def _official_locomo_observation_item(item: object) -> tuple[str, str]:
    if isinstance(item, Mapping):
        text = _first_str(item, "text", "content", "observation", "summary")
        evidence_id = _first_str(item, "dia_id", "evidence", "evidence_id", "id")
        return text, evidence_id
    if isinstance(item, Sequence) and not isinstance(item, str | bytes):
        values = tuple(str(value).strip() for value in item if isinstance(value, str))
        if len(values) >= 2:
            return values[0], values[1]
    return "", ""


def _official_locomo_session_summary_documents(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkDocumentInput, ...]:
    summaries = raw.get("session_summary")
    if not isinstance(summaries, Mapping):
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(summaries, key=_session_sort_key):
        summary = summaries.get(key)
        if not isinstance(summary, str) or not summary.strip():
            continue
        session_key = key.removesuffix("_summary")
        documents.append(
            BenchmarkDocumentInput(
                title=f"LoCoMo {sample_id} {session_key} summary",
                text=f"{session_key} summary\n{summary.strip()}",
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
    documents: list[BenchmarkDocumentInput] = []
    for key in sorted(summaries, key=_session_sort_key):
        value = summaries.get(key)
        session_key = key.removeprefix("events_")
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
                        lines.append(f"{actor_name}: {text}")
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
    memories = _memory_inputs(raw)
    documents = _document_inputs(raw)
    if not question:
        raise BenchmarkValidationError(f"Case {case_id} is missing question")
    if not expected_terms:
        raise BenchmarkValidationError(f"Case {case_id} is missing expected_terms or answer")
    if not memories and not documents:
        raise BenchmarkValidationError(f"Case {case_id} is missing memories/documents")
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
        metadata=_metadata(raw),
    )


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
        return [str(item).strip() for item in value if str(item).strip()]
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


def _post_required(
    adapter: BenchmarkHttpClientPort,
    path: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    idempotency_key: str | None = None,
) -> BenchmarkHttpResponsePort:
    request_headers = dict(headers)
    if idempotency_key:
        request_headers["Idempotency-Key"] = idempotency_key[:120]
    response = adapter.post(path, json_body=payload, headers=request_headers)
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"{path} returned HTTP {response.status_code}")
    return response


def _response_data(response: BenchmarkHttpResponsePort) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _evidence_text(data: Mapping[str, object]) -> str:
    texts: list[str] = []
    rendered = data.get("rendered_text")
    if isinstance(rendered, str):
        texts.append(rendered)
    items = data.get("items")
    if isinstance(items, Sequence) and not isinstance(items, str | bytes):
        for item in items:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return "\n".join(texts)


def _benchmark_summaries(
    run_results: Sequence[CaseRunResult],
    *,
    min_accuracy: float,
) -> list[dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in run_results:
        grouped[item.benchmark].append(item)
    summaries: list[dict[str, object]] = []
    for benchmark in sorted(grouped):
        cases = grouped[benchmark]
        accuracy = _accuracy(cases)
        summaries.append(
            {
                "name": benchmark,
                "suite": benchmark,
                "ok": accuracy >= min_accuracy,
                "metrics": {
                    "accuracy": accuracy,
                    "case_count": len(cases),
                    "capability_count": len(
                        {item.capability for item in cases if item.capability}
                    ),
                    "expected_recall": _ratio(
                        sum(1 for item in cases if item.expected_ok),
                        len(cases),
                    ),
                    "forbidden_leak_rate": _ratio(
                        sum(1 for item in cases if not item.forbidden_ok),
                        len(cases),
                    ),
                    "latency_ms_p95": _p95([item.latency_ms for item in cases]),
                },
                "capability_breakdown": _capability_breakdown(cases),
            }
        )
    return summaries


def _case_payload(item: CaseRunResult) -> dict[str, object]:
    return {
        "benchmark": item.benchmark,
        "case_id": item.case_id,
        "capability": item.capability,
        "status": "ok" if item.ok else "failed",
        "expected_ok": item.expected_ok,
        "forbidden_ok": item.forbidden_ok,
        "missing_terms": list(item.missing_terms),
        "leaked_terms": list(item.leaked_terms),
        "item_ids": list(item.item_ids),
        "latency_ms": item.latency_ms,
    }


def _case_failures(run_results: Sequence[CaseRunResult]) -> list[dict[str, object]]:
    return [
        {
            "case_id": item.case_id,
            "category": item.benchmark,
            "capability": item.capability,
            "reason": "missing_expected_terms" if item.missing_terms else "forbidden_terms_leaked",
            "missing_terms": list(item.missing_terms),
            "leaked_terms": list(item.leaked_terms),
        }
        for item in run_results
        if not item.ok
    ]


def _accuracy(run_results: Sequence[CaseRunResult]) -> float:
    return _ratio(sum(1 for item in run_results if item.ok), len(run_results))


def _capability_breakdown(cases: Sequence[CaseRunResult]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in cases:
        if item.capability:
            grouped[item.capability].append(item)
    return {
        capability: {
            "case_count": len(items),
            "accuracy": _accuracy(items),
            "expected_recall": _ratio(
                sum(1 for item in items if item.expected_ok),
                len(items),
            ),
            "forbidden_leak_rate": _ratio(
                sum(1 for item in items if not item.forbidden_ok),
                len(items),
            ),
        }
        for capability, items in sorted(grouped.items())
    }


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


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return round(ordered[index], 2)


def _dataset_hash(dataset_path: Path) -> str:
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _bounded_progress_fields(fields: Mapping[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            bounded[key] = value[:240]
        elif isinstance(value, bool | int | float):
            bounded[key] = value
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            bounded[key] = [
                item[:120] if isinstance(item, str) else item
                for item in value[:20]
                if isinstance(item, str | bool | int | float)
            ]
        elif isinstance(value, Mapping):
            bounded[key] = {
                str(map_key)[:80]: map_value[:120]
                if isinstance(map_value, str)
                else map_value
                for map_key, map_value in list(value.items())[:20]
                if isinstance(map_value, str | bool | int | float)
            }
    return bounded


def _dataset_source_metadata(
    *,
    dataset_path: Path,
    dataset_hash: str,
    source_kind: str,
    case_count: int | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "source_kind": source_kind,
        "path_label": dataset_path.name,
        "sha256": dataset_hash,
        "size_bytes": dataset_path.stat().st_size,
    }
    if isinstance(case_count, int):
        result["case_count"] = case_count
    return result


def _benchmark_summary_case_count(summary: Mapping[str, object]) -> int | None:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    case_count = metrics.get("case_count")
    return case_count if isinstance(case_count, int) else None


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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup_failure_result(*, reason: str, case_count: int) -> dict[str, object]:
    return {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": case_count > 0,
            "auth_token_configured": False,
        },
        "metrics": {
            "case_count": case_count,
            "benchmark_count": 0,
            "accuracy": 0.0,
        },
        "benchmarks": [],
        "cases": [],
        "failures": [{"case_id": "suite_setup", "category": "setup", "reason": reason}],
    }


def _duplicate_case_failure_result(
    *,
    cases: Sequence[PublicBenchmarkCase],
    duplicate_case_keys: Sequence[str],
) -> dict[str, object]:
    return {
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "failed",
        "ok": False,
        "checks": {
            "dataset_loaded": True,
            "case_count": bool(cases),
            "unique_case_ids": False,
        },
        "metrics": {
            "case_count": len(cases),
            "benchmark_count": len({case.benchmark for case in cases}),
            "accuracy": 0.0,
            "duplicate_case_id_count": len(duplicate_case_keys),
        },
        "benchmarks": [],
        "cases": [],
        "failures": [
            {
                "case_id": key,
                "category": "setup",
                "reason": "duplicate_case_id",
            }
            for key in duplicate_case_keys[:20]
        ],
    }


def _write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
