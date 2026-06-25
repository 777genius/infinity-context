from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import infinity_context_server.public_benchmark as public_benchmark_module
import infinity_context_server.public_benchmark_checkpoint as checkpoint_module
import pytest
from infinity_context_server.public_benchmark import (
    CASE_SELECTION_FIRST,
    CASE_SELECTION_STRATIFIED,
    BenchmarkDocumentInput,
    BenchmarkHttpResponsePort,
    BenchmarkValidationError,
    PublicBenchmarkCase,
    _execute_cases,
    _load_cases,
    _write_json_atomic,
    load_public_benchmark_case_count,
    load_public_benchmark_dataset_profile,
    run_public_memory_benchmark,
)
from infinity_context_server.public_benchmark_checkpoint import (
    load_checkpoint_resume_state_with_diagnostics,
    selected_case_fingerprint,
)


class _FakeBenchmarkResponse:
    def __init__(self, status_code: int, payload: Mapping[str, object]) -> None:
        self.status_code = status_code
        self._payload = dict(payload)
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class _CountingBenchmarkAdapter:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, object]]] = []

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        del headers
        self.posts.append((path, dict(json_body)))
        if path == "/v1/context":
            return _FakeBenchmarkResponse(
                200,
                {
                    "data": {
                        "rendered_text": "SHARED_MARKER",
                        "items": [{"item_id": "chunk_shared", "text": "SHARED_MARKER"}],
                    }
                },
            )
        return _FakeBenchmarkResponse(201, {"data": {}})


class _RecordingHttpClient:
    created: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.posts: list[tuple[str, Mapping[str, object], Mapping[str, str]]] = []
        type(self).created.append(
            {"base_url": base_url, "timeout": timeout, "client": self}
        )

    def __enter__(self) -> _RecordingHttpClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def post(
        self,
        path: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> _FakeBenchmarkResponse:
        self.posts.append((path, dict(json), dict(headers)))
        if path == "/v1/context":
            return _FakeBenchmarkResponse(
                200,
                {
                    "data": {
                        "rendered_text": "SHARED_MARKER",
                        "items": [{"item_id": "chunk_shared", "text": "SHARED_MARKER"}],
                    }
                },
            )
        return _FakeBenchmarkResponse(201, {"data": {}})


def test_public_benchmark_evidence_text_includes_item_source_refs() -> None:
    evidence = public_benchmark_module._evidence_text(
        {
            "rendered_text": "",
            "items": [
                {
                    "text": "snippet without the exact dialogue marker",
                    "source_refs": [
                        {
                            "source_type": "locomo_turn",
                            "source_id": "locomo:conv-42:session_5:D5:8:turn",
                            "chunk_id": "chunk-D5-8",
                            "quote_preview": "D5:8 Nate should clean the tank",
                        }
                    ],
                }
            ],
        }
    )

    assert "D5:8" in evidence
    assert "clean the tank" in evidence


def test_public_benchmark_evidence_text_includes_citation_sources() -> None:
    evidence = public_benchmark_module._evidence_text(
        {
            "items": [
                {
                    "text": "snippet without the exact dialogue marker",
                    "citations": [
                        {
                            "source": {
                                "source_type": "locomo_turn",
                                "source_id": "locomo:conv-26:session_4:D4:8:turn",
                                "quote_preview": "D4:8 Melanie went to Canada in June",
                            }
                        }
                    ],
                }
            ],
        }
    )

    assert "D4:8" in evidence
    assert "Canada in June" in evidence


def test_official_locomo_event_summaries_include_related_turn_markers() -> None:
    documents = public_benchmark_module._official_locomo_event_summary_documents(
        {
            "conversation": {
                "session_7": [
                    {
                        "dia_id": "D7:2",
                        "speaker": "John",
                        "text": (
                            "I am running for office again. It has been a wild ride, "
                            "but I am more excited than ever."
                        ),
                    },
                    {
                        "dia_id": "D7:4",
                        "speaker": "John",
                        "text": (
                            "I saw the impact I could make in the community through "
                            "politics and positive changes."
                        ),
                    },
                ],
                "session_7_date_time": "25 February, 2023",
            },
            "event_summary": {
                "events_session_7": {
                    "John": [
                        (
                            "John runs for office again, with even more zeal and "
                            "enthusiasm than his first run, inspired by the social "
                            "impact one can make in office."
                        )
                    ],
                    "date": "25 February, 2023",
                }
            },
        },
        sample_id="conv-test",
    )

    assert len(documents) == 1
    assert "D7:2" in documents[0].text
    assert "D7:4" in documents[0].text


class _ParallelBenchmarkAdapter:
    def __init__(self, *, expected_parallel_contexts: int) -> None:
        self.posts: list[tuple[str, Mapping[str, object]]] = []
        self.max_active_context_posts = 0
        self._active_context_posts = 0
        self._remaining_barrier_waits = expected_parallel_contexts
        self._lock = threading.Lock()
        self._context_barrier = threading.Barrier(expected_parallel_contexts, timeout=3)

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> BenchmarkHttpResponsePort:
        del headers
        with self._lock:
            self.posts.append((path, dict(json_body)))
        if path != "/v1/context":
            return _FakeBenchmarkResponse(201, {"data": {}})
        with self._lock:
            self._active_context_posts += 1
            self.max_active_context_posts = max(
                self.max_active_context_posts,
                self._active_context_posts,
            )
            should_wait = self._remaining_barrier_waits > 0
            if should_wait:
                self._remaining_barrier_waits -= 1
        try:
            if should_wait:
                self._context_barrier.wait()
        except threading.BrokenBarrierError:
            pass
        finally:
            with self._lock:
                self._active_context_posts -= 1
        return _FakeBenchmarkResponse(
            200,
            {
                "data": {
                    "rendered_text": "SHARED_MARKER",
                    "items": [{"item_id": "chunk_shared", "text": "SHARED_MARKER"}],
                }
            },
        )


def _skip_if_local_public_benchmark_environment_unavailable() -> None:
    preflight = public_benchmark_module.check_local_benchmark_environment()
    if not preflight.ok:
        pytest.skip(preflight.reason or "local public benchmark environment unavailable")


def test_public_memory_benchmark_runs_locomo_and_longmemeval_like_cases(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "public-benchmark.jsonl"
    report = tmp_path / "public-benchmark-report.json"
    rows = [
        {
            "benchmark": "locomo",
            "case_id": "locomo-single-hop",
            "question": "Where does Alice keep Kubernetes manifests?",
            "memories": [
                "Alice keeps Kubernetes manifests in helmfile overlays for project Atlas."
            ],
            "expected_terms": ["helmfile overlays"],
            "forbidden_terms": ["vault root token"],
        },
        {
            "benchmark": "longmemeval",
            "case_id": "longmem-document-deadline",
            "query": "What is the Project Falcon migration deadline?",
            "documents": [
                {
                    "title": "Falcon migration notes",
                    "text": "Project Falcon migration deadline is 2026-08-15.",
                }
            ],
            "answer": "2026-08-15",
        },
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        report_out=report,
        min_accuracy=1.0,
    )

    assert result["ok"] is True
    assert result["suite"] == "public-memory-benchmark"
    assert result["metrics"]["case_count"] == 2
    assert result["metrics"]["unique_case_id_count"] == 2
    assert result["metrics"]["duplicate_case_id_count"] == 0
    assert result["metrics"]["accuracy"] == 1.0
    assert result["checks"]["unique_case_ids"] is True
    assert result["metrics"]["locomo_accuracy"] == 1.0
    assert result["metrics"]["longmemeval_accuracy"] == 1.0
    assert isinstance(result["dataset_hash"], str)
    assert len(result["dataset_hash"]) == 64
    assert "dataset_path" not in result
    assert result["dataset_path_label"] == dataset.name
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)
    assert set(result["dataset_sources"]) == {"locomo", "longmemeval"}
    assert result["dataset_sources"]["locomo"] == {
        "source_kind": "local_dataset",
        "path_label": dataset.name,
        "sha256": result["dataset_hash"],
        "size_bytes": dataset.stat().st_size,
        "case_count": 1,
    }
    assert {item["name"] for item in result["benchmarks"]} == {"locomo", "longmemeval"}
    assert all(case["status"] == "ok" for case in result["cases"])
    assert result["provenance"]["generated_by"] == "infinity_context_server.public_benchmark"
    assert result["provenance"]["suite"] == "public-memory-benchmark"
    assert result["provenance"]["run_id"] == result["dataset_hash"][:16]
    assert result["provenance"]["git"]["dirty"] in {True, False}
    assert report.exists()
    assert not (tmp_path / ".public-benchmark-report.json.tmp").exists()
    assert not list(tmp_path.glob(".public-benchmark-report.json.*.tmp"))
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert "dataset_path" not in written
    assert written["dataset_path_label"] == dataset.name
    assert str(tmp_path) not in report.read_text(encoding="utf-8")
    assert written["dataset_hash"] == result["dataset_hash"]
    assert written["dataset_sources"] == result["dataset_sources"]
    assert written["provenance"]["generated_by"] == "infinity_context_server.public_benchmark"


def test_public_benchmark_json_atomic_write_preserves_existing_file_on_failure(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    _write_json_atomic(report, {"status": "previous"})

    with pytest.raises(TypeError):
        _write_json_atomic(report, {"bad": object()})

    assert json.loads(report.read_text(encoding="utf-8")) == {"status": "previous"}
    assert not list(tmp_path.glob(".report.json.*.tmp"))


def test_public_memory_benchmark_can_use_persistent_local_state(tmp_path: Path) -> None:
    dataset = tmp_path / "public-benchmark.jsonl"
    state_dir = tmp_path / "benchmark-state"
    row = {
        "benchmark": "longmemeval",
        "case_id": "longmem-document-deadline",
        "query": "What is the Project Falcon migration deadline?",
        "documents": [
            {
                "title": "Falcon migration notes",
                "text": "Project Falcon migration deadline is 2026-08-15.",
            }
        ],
        "answer": "2026-08-15",
    }
    dataset.write_text(json.dumps(row), encoding="utf-8")

    first = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        local_state_dir=state_dir,
    )
    second = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        local_state_dir=state_dir,
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert (state_dir / "memory.db").exists()
    assert first["local_state"] == {
        "enabled": True,
        "state_dir_label": "benchmark-state",
        "database_label": "memory.db",
    }
    assert str(tmp_path) not in json.dumps(first, sort_keys=True)
    assert str(tmp_path) not in json.dumps(second, sort_keys=True)


def test_public_memory_benchmark_counts_normalized_cases_without_running(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "public-benchmark.jsonl"
    rows = [
        {
            "benchmark": "locomo",
            "case_id": "locomo-single-hop",
            "question": "Where does Alice keep Kubernetes manifests?",
            "memories": [
                "Alice keeps Kubernetes manifests in helmfile overlays for project Atlas."
            ],
            "expected_terms": ["helmfile overlays"],
        },
        {
            "benchmark": "longmemeval",
            "case_id": "longmem-document-deadline",
            "query": "What is the Project Falcon migration deadline?",
            "documents": [
                {
                    "title": "Falcon migration notes",
                    "text": "Project Falcon migration deadline is 2026-08-15.",
                }
            ],
            "answer": "2026-08-15",
        },
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    assert load_public_benchmark_case_count(dataset_path=dataset) == 2
    assert load_public_benchmark_case_count(dataset_path=dataset, benchmark="locomo") == 1
    assert load_public_benchmark_case_count(dataset_path=dataset, benchmark="longmemeval") == 1
    profile = load_public_benchmark_dataset_profile(dataset_path=dataset)
    assert profile["case_count"] == 2
    assert profile["unique_case_id_count"] == 2
    assert profile["duplicate_case_id_count"] == 0
    assert profile["benchmark_counts"] == {"locomo": 1, "longmemeval": 1}
    assert profile["dataset_path_label"] == dataset.name
    assert len(str(profile["dataset_hash"])) == 64


def test_public_memory_benchmark_stratifies_limited_cases_by_capability(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-stratified.json"
    rows = [
        _longmemeval_row(
            "info-1",
            "single-session-user",
            "Where is the first information marker?",
            "INFO_MARKER_ONE",
        ),
        _longmemeval_row(
            "info-2",
            "single-session-assistant",
            "Where is the second information marker?",
            "INFO_MARKER_TWO",
        ),
        _longmemeval_row(
            "temporal-1",
            "temporal-reasoning",
            "Where is the temporal marker?",
            "TEMPORAL_MARKER",
        ),
        _longmemeval_row(
            "knowledge-1",
            "knowledge-update",
            "Where is the knowledge marker?",
            "KNOWLEDGE_MARKER",
        ),
        _longmemeval_row(
            "multi-1",
            "multi-session",
            "Where is the multi-session marker?",
            "MULTI_MARKER",
        ),
    ]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=3,
        case_selection_strategy=CASE_SELECTION_STRATIFIED,
    )

    assert result["ok"] is True
    assert [case["case_id"] for case in result["cases"]] == [
        "info-1",
        "knowledge-1",
        "multi-1",
    ]
    assert [case["capability"] for case in result["cases"]] == [
        "information_extraction",
        "knowledge_update",
        "multi_session_reasoning",
    ]
    assert result["case_selection"]["strategy"] == CASE_SELECTION_STRATIFIED
    assert result["case_selection"]["input_case_count"] == 5
    assert result["case_selection"]["selected_case_count"] == 3
    assert result["case_selection"]["available_capability_count"] == 4
    assert result["case_selection"]["selected_capability_count"] == 3


def test_public_memory_benchmark_first_case_selection_preserves_old_order(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-first.json"
    rows = [
        _longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1"),
        _longmemeval_row("info-2", "single-session-user", "Where is marker 2?", "MARKER_2"),
        _longmemeval_row(
            "temporal-1",
            "temporal-reasoning",
            "Where is marker 3?",
            "MARKER_3",
        ),
    ]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=2,
        case_selection_strategy=CASE_SELECTION_FIRST,
    )

    assert result["ok"] is True
    assert [case["case_id"] for case in result["cases"]] == ["info-1", "info-2"]
    assert result["case_selection"]["strategy"] == CASE_SELECTION_FIRST
    assert result["case_selection"]["selected_capability_count"] == 1


def test_public_memory_benchmark_filters_explicit_case_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-case-ids.json"
    rows = [
        _longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1"),
        _longmemeval_row("info-2", "single-session-user", "Where is marker 2?", "MARKER_2"),
        _longmemeval_row(
            "temporal-1",
            "temporal-reasoning",
            "Where is marker 3?",
            "MARKER_3",
        ),
    ]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=1,
        case_selection_strategy=CASE_SELECTION_FIRST,
        case_ids=("longmemeval:temporal-1",),
    )

    assert result["ok"] is True
    assert result["requested_case_ids"] == ["longmemeval:temporal-1"]
    assert result["requested_capabilities"] == []
    assert [case["case_id"] for case in result["cases"]] == ["temporal-1"]
    assert result["case_selection"]["strategy"] == "case-id"
    assert result["case_selection"]["requested_case_ids"] == [
        "longmemeval:temporal-1",
    ]
    assert result["case_selection"]["missing_case_ids"] == []
    assert result["case_selection"]["requested_max_cases"] == 1
    assert result["checks"]["requested_case_ids_found"] is True


def test_public_memory_benchmark_filters_requested_capabilities(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-capability-filter.json"
    rows = [
        _longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1"),
        _longmemeval_row(
            "temporal-1",
            "temporal-reasoning",
            "Where is marker 2?",
            "MARKER_2",
        ),
        _longmemeval_row(
            "knowledge-1",
            "knowledge-update",
            "Where is marker 3?",
            "MARKER_3",
        ),
    ]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        capabilities=("temporal-reasoning",),
    )

    assert result["ok"] is True
    assert result["requested_case_ids"] == []
    assert result["requested_capabilities"] == ["temporal_reasoning"]
    assert [case["case_id"] for case in result["cases"]] == ["temporal-1"]
    assert result["case_selection"]["requested_capabilities"] == ["temporal_reasoning"]
    assert result["case_selection"]["selection_pool_case_count"] == 1
    assert result["case_selection"]["selected_capability_counts"] == {
        "longmemeval:temporal_reasoning": 1
    }
    assert result["checks"]["requested_capabilities_found"] is True
    assert result["metrics"]["missing_capability_count"] == 0


def test_public_memory_benchmark_reports_missing_requested_capabilities(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-missing-capability.json"
    rows = [
        _longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1")
    ]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        capabilities=("temporal_reasoning",),
    )

    assert result["ok"] is False
    assert result["requested_case_ids"] == []
    assert result["requested_capabilities"] == ["temporal_reasoning"]
    assert result["checks"]["requested_capabilities_found"] is False
    assert result["metrics"]["case_count"] == 0
    assert result["metrics"]["missing_capability_count"] == 1
    assert result["case_selection"]["missing_capabilities"] == ["temporal_reasoning"]
    assert result["failures"] == [
        {
            "case_id": "case_selection",
            "category": "setup",
            "reason": "requested_capability_not_found",
            "capability": "temporal_reasoning",
        }
    ]


def test_public_memory_benchmark_fails_missing_explicit_case_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-missing-case-id.json"
    rows = [_longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1")]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=1,
        case_selection_strategy=CASE_SELECTION_FIRST,
        case_ids=("longmemeval:info-1", "missing-case"),
    )

    assert result["ok"] is False
    assert result["checks"]["minimum_accuracy_met"] is True
    assert result["checks"]["requested_case_ids_found"] is False
    assert result["checks"]["no_request_failures"] is False
    assert result["metrics"]["missing_case_id_count"] == 1
    assert result["case_selection"]["missing_case_ids"] == ["missing-case"]
    assert result["failures"] == [
        {
            "case_id": "missing-case",
            "category": "setup",
            "reason": "requested_case_id_not_found",
        }
    ]


def test_public_memory_benchmark_fails_when_all_explicit_case_ids_are_missing(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-all-missing-case-ids.json"
    rows = [_longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1")]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        max_cases=1,
        case_selection_strategy=CASE_SELECTION_FIRST,
        case_ids=("missing-case",),
    )

    assert result["ok"] is False
    assert result["cases"] == []
    assert result["checks"]["requested_case_ids_found"] is False
    assert result["metrics"]["missing_case_id_count"] == 1
    assert result["case_selection"]["selected_case_count"] == 0
    assert result["failures"] == [
        {
            "case_id": "missing-case",
            "category": "setup",
            "reason": "requested_case_id_not_found",
        }
    ]


def test_public_memory_benchmark_rejects_invalid_max_cases_with_case_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval-case-ids-invalid-limit.json"
    rows = [_longmemeval_row("info-1", "single-session-user", "Where is marker 1?", "MARKER_1")]
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(BenchmarkValidationError, match="max_cases"):
        run_public_memory_benchmark(
            dataset_path=dataset,
            min_accuracy=1.0,
            max_cases=0,
            case_selection_strategy=CASE_SELECTION_FIRST,
            case_ids=("longmemeval:info-1",),
        )


def test_public_memory_benchmark_external_api_uses_configured_request_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "external-timeout.jsonl"
    progress_out = tmp_path / "progress.jsonl"
    row = {
        "benchmark": "locomo",
        "case_id": "external-timeout",
        "memory_scope_external_ref": "external-timeout-scope",
        "thread_external_ref": "external-timeout-thread",
        "question": "Where is the shared marker?",
        "documents": [
            {
                "title": "External timeout marker",
                "text": "SHARED_MARKER lives in this benchmark document.",
            }
        ],
        "expected_terms": ["SHARED_MARKER"],
    }
    dataset.write_text(json.dumps(row), encoding="utf-8")
    _RecordingHttpClient.created = []
    monkeypatch.setattr(public_benchmark_module.httpx, "Client", _RecordingHttpClient)

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        api_url="http://benchmark.test/",
        auth_token="token",
        min_accuracy=1.0,
        request_timeout_seconds=7.5,
        progress_out=progress_out,
    )
    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    run_started = next(event for event in progress_events if event["event_type"] == "run_started")
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )

    assert result["ok"] is True
    assert result["metrics"]["request_timeout_seconds"] == 7.5
    assert _RecordingHttpClient.created[0]["timeout"] == 7.5
    assert _RecordingHttpClient.created[0]["base_url"] == "http://benchmark.test"
    assert run_started["request_timeout_seconds"] == 7.5
    assert execution_configured["request_timeout_seconds"] == 7.5


def test_public_memory_benchmark_rejects_non_positive_request_timeout(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "invalid-timeout.jsonl"
    row = _longmemeval_row(
        "invalid-timeout",
        "single-session-user",
        "Where is marker 1?",
        "MARKER_1",
    )
    dataset.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(BenchmarkValidationError, match="request_timeout_seconds"):
        run_public_memory_benchmark(
            dataset_path=dataset,
            min_accuracy=1.0,
            request_timeout_seconds=0,
        )


def test_public_memory_benchmark_local_parallel_degrades_to_safe_transport(
    tmp_path: Path,
) -> None:
    _skip_if_local_public_benchmark_environment_unavailable()
    dataset = tmp_path / "public-benchmark-parallel.jsonl"
    progress_out = tmp_path / "progress.jsonl"
    rows = [
        {
            "benchmark": "locomo",
            "case_id": f"local-parallel-{index}",
            "memory_scope_external_ref": f"parallel-scope-{index}",
            "thread_external_ref": f"parallel-thread-{index}",
            "question": "Where is the local parallel marker?",
            "documents": [
                {
                    "title": f"Parallel marker {index}",
                    "text": (
                        f"LOCAL_PARALLEL_MARKER_{index} lives in an isolated "
                        "public benchmark document."
                    ),
                }
            ],
            "expected_terms": [f"LOCAL_PARALLEL_MARKER_{index}"],
        }
        for index in range(2)
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
        parallelism=2,
        progress_out=progress_out,
    )
    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )

    assert result["ok"] is True
    assert result["metrics"]["requested_parallelism"] == 2
    assert result["metrics"]["effective_parallelism"] == 1
    assert result["metrics"]["parallelism_degraded"] is True
    assert result["metrics"]["parallelism_degraded_reason"] == ("local_in_process_transport")
    assert result["metrics"]["accuracy"] == 1.0
    assert execution_configured["effective_parallelism"] == 1
    assert execution_configured["parallelism_degraded_reason"] == ("local_in_process_transport")


def test_public_memory_benchmark_rejects_unknown_case_selection_strategy(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "public-benchmark.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "benchmark": "locomo",
                    "case_id": "one",
                    "question": "Where is the marker?",
                    "memories": ["The marker is in Atlas."],
                    "expected_terms": ["Atlas"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkValidationError, match="Unsupported case selection"):
        run_public_memory_benchmark(
            dataset_path=dataset,
            min_accuracy=1.0,
            max_cases=1,
            case_selection_strategy="weighted-random",
        )


def test_public_memory_benchmark_profile_counts_duplicate_case_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "public-benchmark-duplicates.jsonl"
    rows = [
        {
            "benchmark": "locomo",
            "case_id": "duplicate-case",
            "question": f"Where is marker {index}?",
            "memories": [f"marker-{index} lives in project memory."],
            "expected_terms": [f"marker-{index}"],
        }
        for index in range(3)
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    profile = load_public_benchmark_dataset_profile(
        dataset_path=dataset,
        benchmark="locomo",
    )

    assert profile["case_count"] == 3
    assert profile["unique_case_id_count"] == 1
    assert profile["duplicate_case_id_count"] == 2

    result = run_public_memory_benchmark(
        dataset_path=dataset,
        min_accuracy=1.0,
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["checks"]["unique_case_ids"] is False
    assert result["metrics"]["duplicate_case_id_count"] == 1
    assert result["failures"] == [
        {
            "case_id": "locomo:duplicate-case",
            "category": "setup",
            "reason": "duplicate_case_id",
        }
    ]
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)


def test_public_memory_benchmark_reports_missing_expected_terms(tmp_path: Path) -> None:
    dataset = tmp_path / "public-benchmark-failing.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "locomo",
                        "id": "missing-expected",
                        "question": "Where is the release checklist?",
                        "facts": ["The release checklist lives in Linear."],
                        "expected_terms": ["Notion"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is False
    assert result["metrics"]["accuracy"] == 0.0
    assert result["benchmarks"][0]["ok"] is False
    assert result["cases"][0]["missing_terms"] == ["Notion"]
    assert result["failures"][0]["reason"] == "missing_expected_terms"


def test_public_memory_benchmark_flattens_nested_expected_terms(tmp_path: Path) -> None:
    dataset = tmp_path / "public-benchmark-nested-expected.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "locomo",
                        "id": "nested-expected",
                        "question": "Where is the release checklist?",
                        "facts": ["The release checklist moved from Linear to Notion."],
                        "expected_terms": [["Linear"], ["Notion"]],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]

    assert case.expected_terms == ("Linear", "Notion")


def test_public_memory_benchmark_accepts_normalized_abstention_case(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "public-benchmark-abstention.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "longmemeval",
                        "id": "hard-negative",
                        "question": "What hamster did I mention?",
                        "documents": [{"title": "safe", "text": "I mentioned my cat Luna."}],
                        "answerable": False,
                        "forbidden_terms": ["hamster"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cases = _load_cases(dataset)

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
    )

    assert cases[0].expected_terms == ()
    assert cases[0].forbidden_terms == ("hamster",)
    assert result["ok"] is True
    assert result["metrics"]["accuracy"] == 1.0


def test_public_memory_benchmark_reports_abstention_forbidden_leak(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "public-benchmark-abstention-leak.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "longmemeval",
                        "id": "hard-negative-leak",
                        "question": "What shared marker should not be retrieved?",
                        "documents": [{"title": "safe", "text": "The answer is unavailable."}],
                        "abstention": True,
                        "forbidden_terms": ["SHARED_MARKER"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=_load_cases(dataset),
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
    )

    assert result["ok"] is False
    assert result["metrics"]["accuracy"] == 0.0
    assert result["metrics"]["failure_count"] == 1
    assert result["metrics"]["capability_failure_count"] == {
        "longmemeval:unknown_capability": 1,
    }
    assert result["cases"][0]["missing_terms"] == []
    assert result["cases"][0]["leaked_terms"] == ["SHARED_MARKER"]
    assert result["failures"][0]["reason"] == "forbidden_terms_leaked"


def test_public_memory_benchmark_rejects_abstention_without_forbidden_terms(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "public-benchmark-abstention-invalid.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "benchmark": "longmemeval",
                        "id": "hard-negative-invalid",
                        "question": "What hamster did I mention?",
                        "documents": [{"title": "safe", "text": "I mentioned my cat Luna."}],
                        "answerable": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkValidationError, match="forbidden_terms for abstention"):
        _load_cases(dataset)


def test_public_memory_benchmark_seeds_duplicate_sources_once(tmp_path: Path) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    shared_document = BenchmarkDocumentInput(
        title="Shared document",
        text="SHARED_MARKER lives in a shared public benchmark document.",
        source_external_id="shared-document",
    )
    cases = tuple(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"case-{index}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="shared-scope",
            thread_external_ref="shared-thread",
        )
        for index in range(2)
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
    )

    document_posts = [post for post in adapter.posts if post[0] == "/v1/documents"]
    context_posts = [post for post in adapter.posts if post[0] == "/v1/context"]
    assert len(document_posts) == 1
    assert len(context_posts) == 2
    assert result["ok"] is True
    assert result["metrics"]["seed_source_attempt_count"] == 2
    assert result["metrics"]["seeded_source_count"] == 1
    assert result["metrics"]["seed_cache_hit_count"] == 1


def test_public_memory_benchmark_bounds_reused_source_progress_details(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    dataset.write_text("[]", encoding="utf-8")
    shared_documents = [
        BenchmarkDocumentInput(
            title=f"Shared document {index}",
            text=f"SHARED_MARKER lives in shared public benchmark document {index}.",
            source_external_id=f"shared-document-{index}",
        )
        for index in range(5)
    ]
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="case-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=tuple(shared_documents),
            memory_scope_external_ref="shared-scope",
            thread_external_ref="shared-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="case-two",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                *shared_documents,
                BenchmarkDocumentInput(
                    title="Extra document",
                    text="SHARED_MARKER also lives in an extra document.",
                    source_external_id="extra-document",
                ),
            ),
            memory_scope_external_ref="shared-scope",
            thread_external_ref="shared-thread",
        ),
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    reused_events = [
        event for event in progress_events if event["event_type"] == "source_seed_reused"
    ]
    summary = next(
        event for event in progress_events if event["event_type"] == "source_seed_reuse_summary"
    )
    rendered = progress_out.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["metrics"]["seed_source_attempt_count"] == 11
    assert result["metrics"]["seeded_source_count"] == 6
    assert result["metrics"]["seed_cache_hit_count"] == 5
    assert len(reused_events) == 3
    assert [event["reuse_detail_event_index"] for event in reused_events] == [1, 2, 3]
    assert summary["reused_source_count"] == 5
    assert summary["reused_source_kind_counts"] == {"document": 5}
    assert summary["reuse_detail_event_count"] == 3
    assert summary["seed_cache_hit_count"] == 5
    assert "shared-document-4" not in rendered
    assert "extra-document" not in rendered


def test_public_memory_benchmark_reuses_seeded_corpus_without_per_source_scan(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    dataset.write_text("[]", encoding="utf-8")
    shared_documents = tuple(
        BenchmarkDocumentInput(
            title=f"Shared document {index}",
            text=f"SHARED_MARKER lives in shared public benchmark document {index}.",
            source_external_id=f"shared-document-{index}",
        )
        for index in range(5)
    )
    cases = tuple(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"case-{index}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=shared_documents,
            memory_scope_external_ref="shared-scope",
            thread_external_ref="shared-thread",
        )
        for index in range(2)
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    event_counts = {
        event_type: sum(1 for event in progress_events if event["event_type"] == event_type)
        for event_type in {
            "source_seed_completed",
            "source_seed_corpus_reused",
            "source_seed_reuse_summary",
            "source_seed_reused",
        }
    }
    corpus_reused = next(
        event for event in progress_events if event["event_type"] == "source_seed_corpus_reused"
    )

    assert result["ok"] is True
    assert result["metrics"]["seed_source_attempt_count"] == 10
    assert result["metrics"]["seeded_source_count"] == 5
    assert result["metrics"]["seed_cache_hit_count"] == 5
    assert len([post for post in adapter.posts if post[0] == "/v1/documents"]) == 5
    assert event_counts == {
        "source_seed_completed": 5,
        "source_seed_corpus_reused": 1,
        "source_seed_reuse_summary": 0,
        "source_seed_reused": 0,
    }
    assert corpus_reused["reused_source_count"] == 5
    assert corpus_reused["reused_source_kind_counts"] == {"document": 5}


def test_public_memory_benchmark_uses_recall_oriented_context_budget(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="recall-budget-case",
        question="Where is the shared marker?",
        expected_terms=("SHARED_MARKER",),
        documents=(
            BenchmarkDocumentInput(
                title="Shared document",
                text="SHARED_MARKER lives in a shared public benchmark document.",
            ),
        ),
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=(case,),
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
    )

    context_posts = [post for post in adapter.posts if post[0] == "/v1/context"]
    assert len(context_posts) == 1
    assert context_posts[0][1]["token_budget"] == 4000
    assert context_posts[0][1]["max_facts"] == 20
    assert context_posts[0][1]["max_chunks"] == 50
    assert result["ok"] is True


def test_public_memory_benchmark_runs_isolated_cases_in_parallel(
    tmp_path: Path,
) -> None:
    adapter = _ParallelBenchmarkAdapter(expected_parallel_contexts=2)
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    cases = tuple(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"parallel-{index}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title=f"Parallel document {index}",
                    text=f"SHARED_MARKER lives in isolated benchmark document {index}.",
                ),
            ),
        )
        for index in range(3)
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        parallelism=2,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )
    checkpoint = json.loads(checkpoint_out.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["metrics"]["requested_parallelism"] == 2
    assert result["metrics"]["effective_parallelism"] == 2
    assert result["metrics"]["parallelism_degraded"] is False
    assert adapter.max_active_context_posts == 2
    assert [case["case_id"] for case in result["cases"]] == [
        "parallel-0",
        "parallel-1",
        "parallel-2",
    ]
    assert [case["case_id"] for case in checkpoint["cases"]] == [
        "parallel-0",
        "parallel-1",
        "parallel-2",
    ]
    assert execution_configured["effective_parallelism"] == 2
    assert [event["event_type"] for event in progress_events].count("case_completed") == 3
    progress_snapshots = [
        event for event in progress_events if event["event_type"] == "case_progress"
    ]
    assert len(progress_snapshots) == 3
    assert progress_snapshots[-1]["processed_case_count"] == 3
    assert progress_snapshots[-1]["processed_case_ratio"] == 1.0


def test_public_memory_benchmark_parallelizes_independent_context_groups(
    tmp_path: Path,
) -> None:
    adapter = _ParallelBenchmarkAdapter(expected_parallel_contexts=2)
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    shared_document = BenchmarkDocumentInput(
        title="Shared group document",
        text="SHARED_MARKER lives in the first grouped benchmark document.",
        source_external_id="group-a-shared-document",
    )
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="group-a-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="group-a-scope",
            thread_external_ref="group-a-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="group-a-two",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="group-a-scope",
            thread_external_ref="group-a-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="group-b-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Independent group document",
                    text="SHARED_MARKER lives in the second grouped document.",
                    source_external_id="group-b-document",
                ),
            ),
            memory_scope_external_ref="group-b-scope",
            thread_external_ref="group-b-thread",
        ),
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        parallelism=2,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )
    checkpoint = json.loads(checkpoint_out.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["metrics"]["requested_parallelism"] == 2
    assert result["metrics"]["effective_parallelism"] == 2
    assert result["metrics"]["parallelism_degraded"] is False
    assert result["metrics"]["seed_source_attempt_count"] == 3
    assert result["metrics"]["seeded_source_count"] == 2
    assert result["metrics"]["seed_cache_hit_count"] == 1
    assert adapter.max_active_context_posts == 2
    assert len([post for post in adapter.posts if post[0] == "/v1/documents"]) == 2
    assert [case["case_id"] for case in result["cases"]] == [
        "group-a-one",
        "group-a-two",
        "group-b-one",
    ]
    assert [case["case_id"] for case in checkpoint["cases"]] == [
        "group-a-one",
        "group-a-two",
        "group-b-one",
    ]
    assert execution_configured["effective_parallelism"] == 2
    assert [event["event_type"] for event in progress_events].count("case_completed") == 3


def test_public_memory_benchmark_degrades_parallelism_for_shared_contexts(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    dataset.write_text("[]", encoding="utf-8")
    shared_document = BenchmarkDocumentInput(
        title="Shared document",
        text="SHARED_MARKER lives in a shared public benchmark document.",
        source_external_id="shared-document",
    )
    cases = tuple(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"shared-{index}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="shared-scope",
            thread_external_ref="shared-thread",
        )
        for index in range(2)
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        parallelism=2,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )

    assert result["ok"] is True
    assert result["metrics"]["requested_parallelism"] == 2
    assert result["metrics"]["effective_parallelism"] == 1
    assert result["metrics"]["parallelism_degraded"] is True
    assert result["metrics"]["seed_source_attempt_count"] == 2
    assert result["metrics"]["seeded_source_count"] == 1
    assert result["metrics"]["seed_cache_hit_count"] == 1
    assert len([post for post in adapter.posts if post[0] == "/v1/documents"]) == 1
    assert execution_configured["parallelism_degraded_reason"] == "shared_case_context_refs"


def test_public_memory_benchmark_writes_progress_and_checkpoint(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    cases = (
        PublicBenchmarkCase(
            benchmark="longmemeval",
            case_id="progress-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
            memory_scope_external_ref="progress-scope",
            thread_external_ref="progress-thread",
            metadata={"question_type": "single-session-user"},
        ),
        PublicBenchmarkCase(
            benchmark="longmemeval",
            case_id="progress-two",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
            memory_scope_external_ref="progress-scope",
            thread_external_ref="progress-thread",
            metadata={"question_type": "knowledge-update"},
        ),
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    checkpoint = json.loads(checkpoint_out.read_text(encoding="utf-8"))
    rendered = checkpoint_out.read_text(encoding="utf-8") + progress_out.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["metrics"]["cases_per_second"] > 0
    assert result["metrics"]["estimated_remaining_ms"] == 0.0
    assert result["metrics"]["capability_accuracy"] == {
        "longmemeval:information_extraction": 1.0,
        "longmemeval:knowledge_update": 1.0,
    }
    assert result["metrics"]["capability_case_count"] == {
        "longmemeval:information_extraction": 1,
        "longmemeval:knowledge_update": 1,
    }
    assert result["metrics"]["capability_failure_count"] == {
        "longmemeval:information_extraction": 0,
        "longmemeval:knowledge_update": 0,
    }
    assert result["metrics"]["benchmark_metrics"]["longmemeval"]["capability_breakdown"][
        "knowledge_update"
    ]["case_count"] == 1
    assert [event["event_index"] for event in progress_events] == list(
        range(1, len(progress_events) + 1)
    )
    assert [event["event_type"] for event in progress_events].count("case_started") == 2
    assert any(
        event["event_type"] == "source_seed_started" and event["source_kind"] == "document"
        for event in progress_events
    )
    assert any(
        event["event_type"] == "source_seed_corpus_reused"
        and event["reused_source_kind_counts"] == {"document": 1}
        and event["seed_cache_hit_count"] == 1
        for event in progress_events
    )
    final_progress = progress_events[-1]
    assert final_progress["event_type"] == "run_completed"
    assert final_progress["processed_case_count"] == 2
    assert final_progress["processed_case_ratio"] == 1.0
    assert final_progress["remaining_case_count"] == 0
    assert final_progress["resume_pending_case_count"] == 0
    assert final_progress["succeeded_case_count"] == 2
    assert final_progress["failed_case_count"] == 0
    assert final_progress["accuracy_so_far"] == 1.0
    assert final_progress["capability_case_count_so_far"] == {
        "longmemeval:information_extraction": 1,
        "longmemeval:knowledge_update": 1,
    }
    progress_snapshots = [
        event for event in progress_events if event["event_type"] == "case_progress"
    ]
    assert [event["processed_case_count"] for event in progress_snapshots] == [1, 2]
    assert [event["processed_case_ratio"] for event in progress_snapshots] == [0.5, 1.0]
    assert all(event["cases_per_second"] > 0 for event in progress_snapshots)
    assert progress_snapshots[0]["estimated_remaining_ms"] > 0
    assert progress_snapshots[-1]["estimated_remaining_ms"] == 0.0
    assert progress_snapshots[-1]["accuracy_so_far"] == 1.0
    assert progress_snapshots[0]["capability_accuracy_so_far"] == {
        "longmemeval:information_extraction": 1.0,
    }
    assert progress_snapshots[-1]["capability_accuracy_so_far"] == {
        "longmemeval:information_extraction": 1.0,
        "longmemeval:knowledge_update": 1.0,
    }
    assert progress_snapshots[-1]["capability_case_count_so_far"] == {
        "longmemeval:information_extraction": 1,
        "longmemeval:knowledge_update": 1,
    }
    assert progress_snapshots[-1]["capability_failure_count_so_far"] == {
        "longmemeval:information_extraction": 0,
        "longmemeval:knowledge_update": 0,
    }
    assert checkpoint["status"] == "completed"
    assert checkpoint["selected_case_count"] == 2
    assert checkpoint["selected_case_fingerprint"] == selected_case_fingerprint(cases)
    assert checkpoint["progress"]["processed_case_count"] == 2
    assert checkpoint["progress"]["processed_case_ratio"] == 1.0
    assert checkpoint["progress"]["cases_per_second"] > 0
    assert checkpoint["progress"]["estimated_remaining_ms"] == 0.0
    assert checkpoint["progress"]["seeded_source_count"] == 1
    assert checkpoint["progress"]["seed_source_attempt_count"] == 2
    assert checkpoint["progress"]["seed_cache_hit_count"] == 1
    assert checkpoint["metrics_so_far"]["accuracy"] == 1.0
    assert checkpoint["metrics_so_far"]["capability_accuracy"] == {
        "longmemeval:information_extraction": 1.0,
        "longmemeval:knowledge_update": 1.0,
    }
    assert checkpoint["metrics_so_far"]["capability_failure_count"] == {
        "longmemeval:information_extraction": 0,
        "longmemeval:knowledge_update": 0,
    }
    assert checkpoint["metrics_so_far"]["benchmark_metrics"]["longmemeval"][
        "capability_breakdown"
    ]["information_extraction"]["case_count"] == 1
    assert [item["case_id"] for item in checkpoint["cases"]] == [
        "progress-one",
        "progress-two",
    ]
    assert not (tmp_path / ".checkpoint.json.tmp").exists()
    assert not list(tmp_path.glob(".checkpoint.json.*.tmp"))
    assert str(tmp_path) not in rendered
    assert "shared-document" not in rendered


def test_public_memory_benchmark_rejects_overlapping_artifact_paths(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    artifact = tmp_path / "benchmark-artifact.json"
    dataset.write_text(
        json.dumps(
            {
                "benchmark": "locomo",
                "case_id": "artifact-paths",
                "question": "Where is the marker?",
                "memories": ["The marker is in Atlas."],
                "expected_terms": ["Atlas"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkValidationError, match="artifact paths must be distinct"):
        run_public_memory_benchmark(
            dataset_path=dataset,
            report_out=artifact,
            checkpoint_out=artifact,
        )


def test_public_memory_benchmark_rejects_artifact_path_over_dataset(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "benchmark": "locomo",
                "case_id": "dataset-overwrite",
                "question": "Where is the marker?",
                "memories": ["The marker is in Atlas."],
                "expected_terms": ["Atlas"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkValidationError, match="must not overwrite dataset_path"):
        run_public_memory_benchmark(
            dataset_path=dataset,
            report_out=dataset,
        )


def test_execute_cases_rejects_overlapping_progress_checkpoint_paths(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    artifact = tmp_path / "progress-and-checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="overlap",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
        ),
    )

    with pytest.raises(BenchmarkValidationError, match="artifact paths must be distinct"):
        _execute_cases(
            adapter=adapter,
            headers={"Authorization": "Bearer test-token"},
            cases=cases,
            dataset_path=dataset,
            min_accuracy=1.0,
            started=time.perf_counter(),
            progress_out=artifact,
            checkpoint_out=artifact,
        )


def test_execute_cases_rejects_progress_path_over_dataset(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="dataset-overwrite",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
        ),
    )

    with pytest.raises(BenchmarkValidationError, match="must not overwrite dataset_path"):
        _execute_cases(
            adapter=adapter,
            headers={"Authorization": "Bearer test-token"},
            cases=cases,
            dataset_path=dataset,
            min_accuracy=1.0,
            started=time.perf_counter(),
            progress_out=dataset,
        )


def test_checkpoint_resume_skips_oversized_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_out = tmp_path / "checkpoint.json"
    checkpoint_out.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(checkpoint_module, "_MAX_CHECKPOINT_BYTES", 1)

    result = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint_out,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=(),
    )

    assert result.state is None
    assert result.status == "skipped"
    assert result.reason == "checkpoint_too_large"


def test_checkpoint_resume_skips_excessive_case_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_out = tmp_path / "checkpoint.json"
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {},
                "cases": [{}, {}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(checkpoint_module, "_MAX_CHECKPOINT_CASES", 1)

    result = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint_out,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=(),
    )

    assert result.state is None
    assert result.status == "skipped"
    assert result.reason == "checkpoint_case_count_exceeds_limit"
    assert result.checkpoint_case_count == 2


def test_checkpoint_resume_reports_invalid_case_payload_count(tmp_path: Path) -> None:
    checkpoint_out = tmp_path / "checkpoint.json"
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {},
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "",
                        "status": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-invalid",
            question="Where is the marker?",
            expected_terms=("SHARED_MARKER",),
        ),
    )

    result = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint_out,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=cases,
    )

    assert result.state is None
    assert result.status == "skipped"
    assert result.reason == "no_selected_successful_case_results"
    assert result.checkpoint_case_count == 1
    assert result.checkpoint_invalid_case_count == 1


def test_checkpoint_resume_skips_selected_case_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    checkpoint_out = tmp_path / "checkpoint.json"
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "dataset_hash": "dataset-hash",
                "case_selection": {},
                "selected_case_fingerprint": "different-selection",
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-one",
                        "capability": "locomo_unknown",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk_shared"],
                        "latency_ms": 10.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-one",
            question="Where is the marker?",
            expected_terms=("SHARED_MARKER",),
        ),
    )

    result = load_checkpoint_resume_state_with_diagnostics(
        checkpoint_out=checkpoint_out,
        dataset_hash="dataset-hash",
        case_selection=None,
        cases=cases,
    )

    assert result.state is None
    assert result.status == "skipped"
    assert result.reason == "selected_case_fingerprint_mismatch"
    assert result.selected_case_count == 1
    assert result.checkpoint_case_count == 1


def test_public_memory_benchmark_resumes_from_compatible_checkpoint(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
            memory_scope_external_ref="resume-scope",
            thread_external_ref="resume-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-two",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
            memory_scope_external_ref="resume-scope",
            thread_external_ref="resume-thread",
        ),
    )
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "status": "running",
                "dataset_hash": dataset_hash,
                "case_selection": {},
                "progress": {
                    "processed_case_count": 1,
                    "total_case_count": 2,
                    "seeded_source_count": 1,
                    "seed_source_attempt_count": 1,
                    "seed_cache_hit_count": 0,
                },
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-one",
                        "capability": "locomo_unknown",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk_shared"],
                        "latency_ms": 10.0,
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        resume_from_checkpoint=True,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is True
    assert [case["case_id"] for case in result["cases"]] == ["resume-one", "resume-two"]
    assert [path for path, _ in adapter.posts] == ["/v1/context"]
    assert result["metrics"]["seed_source_attempt_count"] == 2
    assert result["metrics"]["seeded_source_count"] == 1
    assert result["metrics"]["seed_cache_hit_count"] == 1
    assert result["metrics"]["resumed_case_count"] == 1
    assert result["metrics"]["pending_case_count"] == 1
    assert result["resume"] == {
        "requested": True,
        "status": "loaded",
        "reason": "compatible_checkpoint",
        "resume_reuse_policy": "successful_cases_only",
        "resumed_case_count": 1,
        "selected_case_count": 2,
        "checkpoint_case_count": 1,
        "checkpoint_success_case_count": 1,
        "checkpoint_failed_case_count": 0,
        "checkpoint_invalid_case_count": 0,
        "checkpoint_failure_diagnostic_count": 0,
        "checkpoint_failed_case_requeued_count": 0,
        "checkpoint_failed_case_ids": [],
        "checkpoint_failed_case_id_truncated_count": 0,
        "checkpoint_failures": [],
        "resumed_case_ids": ["locomo:resume-one"],
        "pending_case_ids": ["locomo:resume-two"],
        "resumed_case_id_truncated_count": 0,
        "pending_case_id_truncated_count": 0,
    }
    assert any(event["event_type"] == "run_resumed" for event in progress_events)
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )
    assert execution_configured["resumed_case_ids"] == ["locomo:resume-one"]
    assert execution_configured["pending_case_ids"] == ["locomo:resume-two"]
    assert execution_configured["resumed_case_id_truncated_count"] == 0
    assert execution_configured["pending_case_id_truncated_count"] == 0
    assert execution_configured["resume_reuse_policy"] == "successful_cases_only"
    assert execution_configured["checkpoint_failed_case_requeued_count"] == 0
    assert not any(
        event["event_type"] == "case_started" and event["case_id"] == "resume-one"
        for event in progress_events
    )


def test_public_memory_benchmark_resume_retries_checkpoint_failed_cases(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    shared_document = BenchmarkDocumentInput(
        title="Shared document",
        text="SHARED_MARKER lives in a shared public benchmark document.",
        source_external_id="shared-document",
    )
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-ok",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="resume-retry-scope",
            thread_external_ref="resume-retry-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-failed",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(shared_document,),
            memory_scope_external_ref="resume-retry-scope",
            thread_external_ref="resume-retry-thread",
        ),
    )
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "status": "running",
                "dataset_hash": dataset_hash,
                "case_selection": {},
                "progress": {
                    "processed_case_count": 2,
                    "total_case_count": 2,
                    "seeded_source_count": 1,
                    "seed_source_attempt_count": 1,
                    "seed_cache_hit_count": 0,
                },
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-ok",
                        "capability": "locomo_unknown",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk_shared"],
                        "latency_ms": 10.0,
                    },
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-failed",
                        "capability": "locomo_unknown",
                        "status": "failed",
                        "expected_ok": False,
                        "forbidden_ok": True,
                        "missing_terms": ["SHARED_MARKER"],
                        "leaked_terms": [],
                        "item_ids": [],
                        "latency_ms": 20.0,
                    },
                ],
                "failures": [
                    {
                        "case_id": "resume-failed",
                        "category": "locomo",
                        "reason": "missing_expected_terms",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        resume_from_checkpoint=True,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is True
    assert [case["case_id"] for case in result["cases"]] == [
        "resume-ok",
        "resume-failed",
    ]
    assert all(case["status"] == "ok" for case in result["cases"])
    assert result["failures"] == []
    assert [path for path, _ in adapter.posts] == ["/v1/context"]
    assert result["metrics"]["resumed_case_count"] == 1
    assert result["metrics"]["pending_case_count"] == 1
    assert result["resume"]["checkpoint_success_case_count"] == 1
    assert result["resume"]["checkpoint_failed_case_count"] == 1
    assert result["resume"]["checkpoint_invalid_case_count"] == 0
    assert result["resume"]["checkpoint_failure_diagnostic_count"] == 1
    assert result["resume"]["checkpoint_failed_case_requeued_count"] == 1
    assert result["resume"]["checkpoint_failed_case_ids"] == ["resume-failed"]
    assert result["resume"]["checkpoint_failed_case_id_truncated_count"] == 0
    assert result["resume"]["resume_reuse_policy"] == "successful_cases_only"
    assert result["resume"]["resumed_case_ids"] == ["locomo:resume-ok"]
    assert result["resume"]["pending_case_ids"] == ["locomo:resume-failed"]
    assert result["resume"]["resumed_case_id_truncated_count"] == 0
    assert result["resume"]["pending_case_id_truncated_count"] == 0
    assert result["resume"]["checkpoint_failures"] == [
        {
            "case_id": "resume-failed",
            "category": "locomo",
            "capability": "locomo_unknown",
            "reason": "missing_expected_terms",
            "missing_terms": ["SHARED_MARKER"],
            "leaked_terms": [],
            "checkpoint_status": "failed",
            "retry_pending": True,
            "from_checkpoint": True,
        }
    ]
    assert any(
        event["event_type"] == "run_resumed"
        and event["checkpoint_failure_diagnostic_count"] == 1
        and event["checkpoint_failed_case_requeued_count"] == 1
        and event["checkpoint_failed_case_ids"] == ["resume-failed"]
        and event["checkpoint_failed_case_id_truncated_count"] == 0
        and event["resume_reuse_policy"] == "successful_cases_only"
        for event in progress_events
    )
    execution_configured = next(
        event for event in progress_events if event["event_type"] == "run_execution_configured"
    )
    assert execution_configured["checkpoint_failed_case_requeued_count"] == 1
    assert execution_configured["checkpoint_failed_case_ids"] == ["resume-failed"]
    assert execution_configured["resume_reuse_policy"] == "successful_cases_only"
    assert result["metrics"]["checkpoint_failed_case_requeued_count"] == 1
    assert any(
        event["event_type"] == "case_started" and event["case_id"] == "resume-failed"
        for event in progress_events
    )
    assert not any(
        event["event_type"] == "case_started" and event["case_id"] == "resume-ok"
        for event in progress_events
    )


def test_public_memory_benchmark_resumes_seeded_corpus_by_stable_fingerprint(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()

    def documents() -> tuple[BenchmarkDocumentInput, ...]:
        return tuple(
            BenchmarkDocumentInput(
                title=f"Shared document {index}",
                text=f"SHARED_MARKER lives in shared document {index}.",
                source_external_id=f"shared-document-{index}",
            )
            for index in range(3)
        )

    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-corpus-one",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=documents(),
            memory_scope_external_ref="resume-corpus-scope",
            thread_external_ref="resume-corpus-thread",
        ),
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-corpus-two",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=documents(),
            memory_scope_external_ref="resume-corpus-scope",
            thread_external_ref="resume-corpus-thread",
        ),
    )
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "status": "running",
                "dataset_hash": dataset_hash,
                "case_selection": {},
                "progress": {
                    "processed_case_count": 1,
                    "total_case_count": 2,
                    "seeded_source_count": 3,
                    "seed_source_attempt_count": 3,
                    "seed_cache_hit_count": 0,
                },
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-corpus-one",
                        "capability": "locomo_unknown",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                        "missing_terms": [],
                        "leaked_terms": [],
                        "item_ids": ["chunk_shared"],
                        "latency_ms": 10.0,
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        resume_from_checkpoint=True,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    corpus_reused = next(
        event for event in progress_events if event["event_type"] == "source_seed_corpus_reused"
    )

    assert result["ok"] is True
    assert [path for path, _ in adapter.posts] == ["/v1/context"]
    assert result["metrics"]["resumed_case_count"] == 1
    assert result["metrics"]["pending_case_count"] == 1
    assert result["metrics"]["seed_source_attempt_count"] == 6
    assert result["metrics"]["seed_cache_hit_count"] == 3
    assert corpus_reused["case_id"] == "resume-corpus-two"
    assert corpus_reused["reused_source_count"] == 3
    assert corpus_reused["reused_source_kind_counts"] == {"document": 3}
    assert not any(event["event_type"] == "source_seed_reused" for event in progress_events)


def test_public_memory_benchmark_reports_resume_skip_reason(
    tmp_path: Path,
) -> None:
    adapter = _CountingBenchmarkAdapter()
    dataset = tmp_path / "dataset.json"
    progress_out = tmp_path / "progress.jsonl"
    checkpoint_out = tmp_path / "checkpoint.json"
    dataset.write_text("[]", encoding="utf-8")
    checkpoint_out.write_text(
        json.dumps(
            {
                "schema_version": "public-benchmark-checkpoint-v1",
                "status": "running",
                "dataset_hash": "different-dataset-hash",
                "case_selection": {},
                "cases": [
                    {
                        "benchmark": "locomo",
                        "case_id": "resume-skip",
                        "capability": "locomo_unknown",
                        "status": "ok",
                        "expected_ok": True,
                        "forbidden_ok": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cases = (
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id="resume-skip",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
            documents=(
                BenchmarkDocumentInput(
                    title="Shared document",
                    text="SHARED_MARKER lives in a shared public benchmark document.",
                    source_external_id="shared-document",
                ),
            ),
            memory_scope_external_ref="resume-skip-scope",
            thread_external_ref="resume-skip-thread",
        ),
    )

    result = _execute_cases(
        adapter=adapter,
        headers={"Authorization": "Bearer test-token"},
        cases=cases,
        dataset_path=dataset,
        min_accuracy=1.0,
        started=time.perf_counter(),
        progress_out=progress_out,
        checkpoint_out=checkpoint_out,
        checkpoint_every_cases=1,
        resume_from_checkpoint=True,
    )

    progress_events = [
        json.loads(line) for line in progress_out.read_text(encoding="utf-8").splitlines()
    ]
    resume_skipped = next(
        event for event in progress_events if event["event_type"] == "run_resume_skipped"
    )

    assert result["ok"] is True
    assert result["resume"] == {
        "requested": True,
        "status": "skipped",
        "reason": "dataset_hash_mismatch",
        "resume_reuse_policy": "successful_cases_only",
        "resumed_case_count": 0,
        "selected_case_count": 1,
        "checkpoint_case_count": 0,
        "checkpoint_success_case_count": 0,
        "checkpoint_failed_case_count": 0,
        "checkpoint_invalid_case_count": 0,
        "checkpoint_failure_diagnostic_count": 0,
        "checkpoint_failed_case_requeued_count": 0,
        "checkpoint_failed_case_ids": [],
        "checkpoint_failed_case_id_truncated_count": 0,
        "checkpoint_failures": [],
        "resumed_case_ids": [],
        "pending_case_ids": ["locomo:resume-skip"],
        "resumed_case_id_truncated_count": 0,
        "pending_case_id_truncated_count": 0,
    }
    assert result["metrics"]["resumed_case_count"] == 0
    assert result["metrics"]["pending_case_count"] == 1
    assert result["metrics"]["checkpoint_failed_case_requeued_count"] == 0
    assert resume_skipped["reason"] == "dataset_hash_mismatch"
    assert resume_skipped["resume_reuse_policy"] == "successful_cases_only"
    assert resume_skipped["checkpoint_failed_case_requeued_count"] == 0
    assert [path for path, _ in adapter.posts] == ["/v1/documents", "/v1/context"]


def test_public_benchmark_bounds_resume_case_id_details() -> None:
    cases = tuple(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=f"resume-detail-{index}",
            question="Where is the shared marker?",
            expected_terms=("SHARED_MARKER",),
        )
        for index in range(23)
    )

    case_ids, truncated_count = public_benchmark_module._bounded_case_id_details(cases)

    assert len(case_ids) == 20
    assert case_ids[0] == "locomo:resume-detail-0"
    assert case_ids[-1] == "locomo:resume-detail-19"
    assert truncated_count == 3


def test_public_memory_benchmark_accepts_official_locomo_shape(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo10-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-mini",
                    "conversation": {
                        "session_1_date_time": "7 May 2023",
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I went to the LGBTQ support group today.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "When did Caroline go to the LGBTQ support group?",
                            "answer": "7 May 2023",
                            "evidence": ["D1:1"],
                            "category": 2,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["benchmarks"][0]["name"] == "locomo"
    assert result["metrics"]["locomo_case_count"] == 1
    assert result["cases"][0]["case_id"] == "conv-mini:qa:1"
    assert result["cases"][0]["covered_terms"] == ["D1:1"]
    assert result["cases"][0]["covered_evidence_refs"] == ["D1:1"]
    assert result["cases"][0]["missing_evidence_refs"] == []
    assert result["cases"][0]["coverage"] == {
        "expected_term_count": 1,
        "covered_expected_term_count": 1,
        "expected_term_coverage": 1.0,
        "evidence_ref_count": 1,
        "covered_evidence_ref_count": 1,
        "evidence_ref_coverage": 1.0,
    }


def test_official_locomo_cases_preserve_answer_and_evidence_diagnostics(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-diagnostics-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-diagnostics-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "My friends and mentors support me.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Who supports Caroline?",
                            "answer": "Friends and mentors",
                            "evidence": ["D1:1"],
                            "category": 1,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_cases(dataset)

    assert cases[0].metadata["answer_preview"] == "Friends and mentors"
    assert cases[0].metadata["evidence"] == ["D1:1"]
    assert cases[0].metadata["evidence_previews"] == {
        "D1:1": "My friends and mentors support me.",
    }
    assert cases[0].expected_terms == ("D1:1",)


def test_public_memory_benchmark_skips_unsupported_official_locomo_inference(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-no-evidence-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-no-evidence-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I checked in with Melanie today.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Would Melanie be considered an ally?",
                            "answer": "Yes, she is supportive",
                            "evidence": [],
                            "category": 3,
                        },
                        {
                            "question": "What launch window did Caroline discuss?",
                            "answer": "Q4 launch window",
                            "evidence": [],
                            "category": 2,
                        },
                    ],
                    "session_summary": {
                        "session_1_summary": (
                            "Caroline discussed the Q4 launch window with Melanie."
                        )
                    },
                    "event_summary": [],
                    "observation": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_cases(dataset)
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert [case.case_id for case in cases] == ["conv-no-evidence-mini:qa:2"]
    assert cases[0].expected_terms == ("Q4 launch window",)
    assert result["ok"] is True
    assert result["metrics"]["locomo_case_count"] == 1


def test_public_memory_benchmark_indexes_official_locomo_visual_queries(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-visual-query-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-visual-query-mini",
                    "conversation": {
                        "session_1_date_time": "7 May 2023",
                        "session_1": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:12",
                                "text": "I made something new. Take a look at this.",
                                "blip_caption": ("a photo of a painting of a sunset over a lake"),
                                "query": "painting sunrise",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What creative activity did Melanie show?",
                            "answer": "painting sunrise",
                            "evidence": ["D1:12"],
                            "category": 2,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    session_doc = next(
        document for document in case.documents if document.source_type == "locomo_session"
    )
    turn_doc = next(
        document for document in case.documents if document.source_type == "locomo_turn"
    )
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert "D1:12 Melanie image caption: a photo of a painting" in session_doc.text
    assert "D1:12 Melanie visual query: painting sunrise" in session_doc.text
    assert turn_doc.source_external_id == "locomo:conv-visual-query-mini:session_1:D1:12:turn"
    assert "session_1 turn D1:12" in turn_doc.text
    assert "D1:12 Melanie: I made something new." in turn_doc.text
    assert "image caption: a photo of a painting" in turn_doc.text
    assert "visual query: painting sunrise" in turn_doc.text
    assert result["ok"] is True


def test_public_memory_benchmark_indexes_official_locomo_observations(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-observation-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-observation-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I am thinking about next steps.",
                            }
                        ],
                        "session_1_date_time": "11 March, 2023",
                    },
                    "qa": [
                        {
                            "question": "What field is Caroline considering for education?",
                            "answer": "Mental health counseling",
                            "evidence": ["D1:1"],
                            "category": 3,
                        }
                    ],
                    "observation": {
                        "session_1_observation": {
                            "Caroline": [
                                [
                                    "Caroline is considering mental health counseling education.",
                                    "D1:1",
                                ]
                            ]
                        }
                    },
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    observation_docs = [
        document for document in case.documents if document.source_type == "locomo_observation"
    ]
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert len(observation_docs) == 1
    assert "D1:1 Caroline: Caroline is considering mental health counseling education." in (
        observation_docs[0].text
    )
    assert "session_1 date: 11 March, 2023" in observation_docs[0].text
    assert result["ok"] is True


def test_public_memory_benchmark_recalls_locomo_classical_music_preference(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-music-preference-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-music-preference-mini",
                    "conversation": {
                        "session_15": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D15:28",
                                "text": (
                                    "I'm a fan of both classical like Bach and Mozart, "
                                    "as well as modern music like Ed Sheeran's Perfect."
                                ),
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D15:29",
                                "text": "I usually listen to podcasts instead.",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
                            ),
                            "answer": "Yes; it's classical music",
                            "evidence": ["D15:28"],
                            "category": 3,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_bought_items_aggregation(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-bought-items-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-bought-items-mini",
                    "conversation": {
                        "session_7": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D7:18",
                                "text": (
                                    "Luna and Oliver are so sweet and playful. "
                                    "Just got some new shoes, too!"
                                ),
                            }
                        ],
                        "session_19": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D19:2",
                                "text": (
                                    "These figurines I bought yesterday remind me of family love."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What items has Melanie bought?",
                            "answer": "Figurines, shoes",
                            "evidence": ["D19:2", "D7:18"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_event_help_aggregation(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-event-help-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-event-help-mini",
                    "conversation": {
                        "session_3": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D3:3",
                                "text": (
                                    "I felt powerful giving my school talk. I shared "
                                    "my journey and inspired people to be better allies."
                                ),
                            }
                        ],
                        "session_9": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D9:2",
                                "text": (
                                    "Last weekend I joined a mentorship program for "
                                    "LGBTQ youth. It is rewarding to help the community."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                "What events has Caroline participated in to help children?"
                            ),
                            "answer": "Mentoring program, school speech",
                            "evidence": ["D9:2", "D3:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_social_support_network(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-social-support-network-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-social-support-network-mini",
                    "conversation": {
                        "session_4": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D4:7",
                                "text": (
                                    "After the breakup, my mother Maya and my "
                                    "running coach Lena were there for me. They "
                                    "comforted me and helped me through it."
                                ),
                            }
                        ],
                        "session_5": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D5:2",
                                "text": (
                                    "I also helped review backend support notes "
                                    "for the provider integration."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Who helped Caroline through it?",
                            "answer": "Her mother Maya and coach Lena.",
                            "evidence": ["D4:7"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_support_role_inference(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-support-role-inference-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-support-role-inference-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D2:5",
                                "text": (
                                    "My friends and family support me and give "
                                    "me strength when I feel uncertain."
                                ),
                            }
                        ],
                        "session_9": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D9:2",
                                "text": (
                                    "Last weekend I joined a mentorship program "
                                    "for LGBTQ youth. I listened patiently and "
                                    "helped people feel safe in the community."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Would Caroline be a good mentor for Alex?",
                            "answer": (
                                "Yes, she joined a mentorship program, listened "
                                "patiently, and helped LGBTQ youth feel safe."
                            ),
                            "evidence": ["D9:2"],
                            "category": 3,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    pytest.importorskip("aiosqlite")
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_emotion_cause_paraphrase(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-emotion-cause-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-emotion-cause-mini",
                    "conversation": {
                        "session_5": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D5:1",
                                "text": (
                                    "Last week I went to an LGBTQ+ pride parade. "
                                    "Everyone was happy, and the parade made me "
                                    "feel at home in the community."
                                ),
                            }
                        ],
                        "session_6": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D6:4",
                                "text": (
                                    "I also joined an online support group for "
                                    "general planning advice."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What gave Caroline a sense of belonging?",
                            "answer": "The LGBTQ+ pride parade.",
                            "evidence": ["D5:1"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    pytest.importorskip("aiosqlite")
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_after_conversation_sequence(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-after-conversation-sequence-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-after-conversation-sequence-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D2:3",
                                "text": (
                                    "After talking with Sam about Atlas, I decided "
                                    "to wait for invoice approval before launch."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D3:5",
                                "text": (
                                    "After talking with Priya about Stripe, I changed "
                                    "the billing retry plan."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                "What did Alex decide after talking with Sam about Atlas?"
                            ),
                            "answer": "Wait for invoice approval before launch.",
                            "evidence": ["D2:3"],
                            "category": 3,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_conversation_counterparty(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-conversation-counterparty-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-conversation-counterparty-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D2:3",
                                "text": (
                                    "I talked with Sam about Project Atlas rollout "
                                    "and invoice approval."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D3:5",
                                "text": (
                                    "I talked with Priya about Stripe billing retries."
                                ),
                            }
                        ],
                        "session_4": [
                            {
                                "speaker": "Taylor",
                                "dia_id": "D4:7",
                                "text": (
                                    "Project Atlas was delayed, but there was no "
                                    "conversation with Alex."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Who did Alex talk to about Project Atlas?",
                            "answer": "Sam.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_conversation_topic(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-conversation-topic-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-conversation-topic-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D2:3",
                                "text": (
                                    "Alex and Maria talked about Project Atlas "
                                    "and invoice approval."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D3:5",
                                "text": "Alex and Maria talked after lunch.",
                            }
                        ],
                        "session_4": [
                            {
                                "speaker": "Maria",
                                "dia_id": "D4:7",
                                "text": (
                                    "Alex and Maria did not talk about Stripe "
                                    "billing retries."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What did Alex and Maria talk about?",
                            "answer": "Project Atlas and invoice approval.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_direct_recipient_action(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-direct-recipient-action-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-direct-recipient-action-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D2:3",
                                "text": (
                                    "I told Maria about the Project Atlas delay "
                                    "after the invoice approval call."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Maria",
                                "dia_id": "D3:5",
                                "text": (
                                    "I told Alex about the Project Atlas delay "
                                    "after the invoice approval call."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Who did Alex tell about the Project Atlas delay?",
                            "answer": "Maria.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_passive_task_recipient_action(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-passive-task-recipient-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-passive-task-recipient-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Alex",
                                "dia_id": "D2:3",
                                "text": (
                                    "I asked Maria to send the Project Atlas invoice "
                                    "after the approval call."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Maria",
                                "dia_id": "D3:5",
                                "text": (
                                    "I asked Alex to send the Project Atlas invoice "
                                    "after the approval call."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                "Who was asked to send the Project Atlas invoice by Alex?"
                            ),
                            "answer": "Maria.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_recommended_that_recipient(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-recommended-that-recipient-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-recommended-that-recipient-mini",
                    "conversation": {
                        "session_2": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D2:3",
                                "text": (
                                    "I recommended that Melanie read Becoming Nicole "
                                    "by Amy Ellis Nutt for book club."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D3:5",
                                "text": (
                                    "I recommended that Caroline read Becoming Nicole "
                                    "by Amy Ellis Nutt for book club."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "Who recommended that Melanie read Becoming Nicole?",
                            "answer": "Caroline.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        },
                        {
                            "question": "What book did Caroline recommend Melanie read?",
                            "answer": "Becoming Nicole by Amy Ellis Nutt.",
                            "evidence": ["D2:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert [case["missing_terms"] for case in result["cases"]] == [[], []]


def test_public_memory_benchmark_recalls_locomo_lgbtq_events_aggregation(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-lgbtq-events-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-lgbtq-events-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:3",
                                "text": (
                                    "I went to a LGBTQ support group yesterday and "
                                    "it was so powerful."
                                ),
                            }
                        ],
                        "session_3": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D3:1",
                                "text": (
                                    "I wanted to tell you about my school event last "
                                    "week. I talked about my transgender journey and "
                                    "encouraged students to get involved in the LGBTQ "
                                    "community."
                                ),
                            }
                        ],
                        "session_5": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D5:1",
                                "text": (
                                    "Last week I went to an LGBTQ+ pride parade. "
                                    "Everyone was happy and it made me feel like I "
                                    "belonged."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": ("What LGBTQ+ events has Caroline participated in?"),
                            "answer": "Pride parade, school speech, support group",
                            "evidence": ["D5:1", "D3:1", "D1:3"],
                            "category": 1,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_hike_count_adjacent_windows(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-hike-count-adjacent-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-hike-count-adjacent-mini",
                    "conversation": {
                        "session_11": [
                            {
                                "speaker": "Joanna",
                                "dia_id": "D11:3",
                                "text": (
                                    "I went hiking and found some more amazing trails "
                                    "in my town. It was such an awesome experience."
                                ),
                            },
                            {
                                "speaker": "Nate",
                                "dia_id": "D11:4",
                                "text": "Sounds great. Did you happen to take any photos?",
                            },
                            {
                                "speaker": "Joanna",
                                "dia_id": "D11:5",
                                "text": (
                                    "Yeah, I did! Loved this spot on the hike. "
                                    "The rush of the water was so soothing."
                                ),
                                "image_caption": (
                                    "a photo of a waterfall with a dark sky in the background"
                                ),
                                "visual_query": "waterfall lush greenery",
                            },
                        ],
                        "session_14": [
                            {
                                "speaker": "Joanna",
                                "dia_id": "D14:19",
                                "text": (
                                    "Yep, I'm hiking with some buddies this weekend. "
                                    "We're checking out a new trail with a rad waterfall."
                                ),
                            },
                            {
                                "speaker": "Nate",
                                "dia_id": "D14:20",
                                "text": (
                                    "Sounds great! I'm organizing a gaming party two "
                                    "weekends later."
                                ),
                            },
                            {
                                "speaker": "Joanna",
                                "dia_id": "D14:21",
                                "text": "Oh? Are you going to invite your tournament friends?",
                            },
                        ],
                        "session_28": [
                            {
                                "speaker": "Joanna",
                                "dia_id": "D28:22",
                                "text": (
                                    "I took that pic on a hike last summer near Fort Wayne. "
                                    "The sunset and beauty were inspiring."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "How many hikes has Joanna been on?",
                            "answer": "Three",
                            "evidence": ["D11:5", "D14:21", "D28:22"],
                            "category": 3,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_recalls_locomo_reliable_failure_bridges(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-reliable-bridges-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-reliable-bridges-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:4",
                                "text": (
                                    "I took the kids to the museum yesterday. "
                                    "The dinosaur exhibit made their eyes light up."
                                ),
                            },
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:8",
                                "text": (
                                    "We love painting nature-inspired scenes together as a family."
                                ),
                            },
                        ],
                        "session_2": [
                            {
                                "speaker": "Joanna",
                                "dia_id": "D2:23",
                                "text": (
                                    "I'm allergic to most reptiles and animals "
                                    "with fur. My face gets puffy and itchy."
                                ),
                            },
                            {
                                "speaker": "Joanna",
                                "dia_id": "D2:29",
                                "text": (
                                    "I recently found out I'm allergic to "
                                    "cockroaches too, so pets are tricky."
                                ),
                            },
                        ],
                        "session_3": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D3:11",
                                "text": (
                                    "I loved Becoming Nicole by Amy Ellis Nutt. "
                                    "It is an inspiring true story about a trans "
                                    "girl and her family."
                                ),
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": ("What activities has Melanie done with her family?"),
                            "answer": "Museum visits and painting.",
                            "evidence": ["D1:4", "D1:8"],
                            "category": 1,
                        },
                        {
                            "question": (
                                "What underlying condition might Joanna have "
                                "based on her allergies?"
                            ),
                            "answer": "A broad animal allergy.",
                            "evidence": ["D2:23", "D2:29"],
                            "category": 3,
                        },
                        {
                            "question": ("What book did Melanie read from Caroline's suggestion?"),
                            "answer": "Becoming Nicole by Amy Ellis Nutt.",
                            "evidence": ["D3:11"],
                            "category": 1,
                        },
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert [case["missing_terms"] for case in result["cases"]] == [[], [], []]


def test_public_memory_benchmark_recalls_locomo_current_goal_inference(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-current-goal-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-current-goal-mini",
                    "conversation": {
                        "session_19": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D19:1",
                                "text": (
                                    "I passed the adoption agency interviews last "
                                    "Friday. This is a big move towards my goal of "
                                    "having a family."
                                ),
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D19:3",
                                "text": (
                                    "I hope to build my own family and put a roof "
                                    "over kids who have not had that before. Adoption "
                                    "is a way of giving back."
                                ),
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                "Would Caroline want to move back to her home country soon?"
                            ),
                            "answer": ("No; she is in the process of adopting children."),
                            "evidence": ["D19:1", "D19:3"],
                            "category": 3,
                        }
                    ],
                    "event_summary": [],
                    "observation": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_links_observations_to_related_locomo_turn_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-related-observation-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-related-observation-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:9",
                                "text": (
                                    "Gonna continue my edu and check out career options, "
                                    "which is pretty exciting!"
                                ),
                            },
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:10",
                                "text": "Wow, what kind of jobs are you thinking of?",
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:11",
                                "text": (
                                    "I'm keen on counseling or working in mental health "
                                    "to support those with similar issues."
                                ),
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": (
                                "What fields would Caroline be likely to pursue in her educaton?"
                            ),
                            "answer": "Psychology, counseling certification",
                            "evidence": ["D1:9", "D1:11"],
                            "category": 3,
                        }
                    ],
                    "observation": {
                        "session_1_observation": {
                            "Caroline": [
                                [
                                    (
                                        "Caroline is planning to continue her education and "
                                        "explore career options in counseling or mental health "
                                        "to support those with similar issues."
                                    ),
                                    "D1:9",
                                ]
                            ]
                        }
                    },
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    observation_doc = next(
        document for document in case.documents if document.source_type == "locomo_observation"
    )
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert "D1:9 Caroline:" in observation_doc.text
    assert "Related turns: D1:11." in observation_doc.text
    assert "D1:10" not in observation_doc.text
    assert result["ok"] is True


def test_public_memory_benchmark_links_observations_to_adjacent_same_speaker_turn_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-adjacent-observation-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-adjacent-observation-mini",
                    "conversation": {
                        "session_14": [
                            {
                                "speaker": "Joanna",
                                "dia_id": "D14:19",
                                "text": (
                                    "I'm hiking with some buddies this weekend and "
                                    "checking out a new trail with a waterfall."
                                ),
                            },
                            {
                                "speaker": "Nate",
                                "dia_id": "D14:20",
                                "text": "Sounds great! Have fun with that.",
                            },
                            {
                                "speaker": "Joanna",
                                "dia_id": "D14:21",
                                "text": "Are you going to invite your tournament friends?",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": "How many hikes has Joanna been on?",
                            "answer": "one",
                            "evidence": ["D14:21"],
                            "category": 2,
                        }
                    ],
                    "observation": {
                        "session_14_observation": {
                            "Joanna": [
                                [
                                    (
                                        "Joanna is planning to go hiking with buddies "
                                        "to check out a new trail with a waterfall."
                                    ),
                                    "D14:19",
                                ]
                            ]
                        }
                    },
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    observation_doc = next(
        document for document in case.documents if document.source_type == "locomo_observation"
    )

    assert "D14:19 Joanna:" in observation_doc.text
    assert "Related turns: D14:21." in observation_doc.text
    assert "D14:20" not in observation_doc.text


def test_public_memory_benchmark_preserves_multiple_locomo_observation_evidence_ids(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-multi-observation-evidence-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-multi-observation-evidence-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I want to pursue counseling.",
                            },
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:2",
                                "text": "That sounds meaningful.",
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:4",
                                "text": "Mental health work feels like the right path.",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": "What field is Caroline likely to pursue?",
                            "answer": "counseling",
                            "evidence": ["D1:1", "D1:4"],
                            "category": 3,
                        }
                    ],
                    "observation": {
                        "session_1_observation": {
                            "Caroline": [
                                {
                                    "text": (
                                        "Caroline wants counseling and mental health "
                                        "work as her career path."
                                    ),
                                    "evidence_ids": ["D1:1", ["D1:4"]],
                                }
                            ]
                        }
                    },
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    observation_doc = next(
        document for document in case.documents if document.source_type == "locomo_observation"
    )

    assert "D1:1 Caroline:" in observation_doc.text
    assert "Related turns: D1:4." in observation_doc.text
    assert "D1:2" not in observation_doc.text


def test_public_memory_benchmark_accepts_nested_official_locomo_qa_evidence(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-nested-qa-evidence-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-nested-qa-evidence-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I want to pursue counseling.",
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:4",
                                "text": "Mental health work feels like the right path.",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": "What field is Caroline likely to pursue?",
                            "answer": "counseling",
                            "evidence": ["D1:1", ["D1:4", "D1:missing"]],
                            "category": 3,
                        }
                    ],
                    "observation": [],
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]

    assert case.expected_terms == ("D1:1", "D1:4")


def test_public_memory_benchmark_recalls_locomo_career_intent_synonyms(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-career-intent-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-career-intent-mini",
                    "conversation": {
                        "session_7": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D7:5",
                                "text": "I need to figure out what to do next.",
                            },
                            {
                                "speaker": "Caroline",
                                "dia_id": "D7:9",
                                "text": "I talked with Melanie about possible next steps.",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": ("Would Caroline pursue writing as a career option?"),
                            "answer": "No, she was looking into counseling jobs.",
                            "evidence": ["D7:5"],
                            "category": 3,
                        }
                    ],
                    "observation": {
                        "session_7_observation": {
                            "Caroline": [
                                [
                                    ("Caroline is looking into counseling and mental health jobs."),
                                    "D7:5",
                                ]
                            ]
                        }
                    },
                    "event_summary": [],
                    "session_summary": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    case = _load_cases(dataset)[0]
    observation_doc = next(
        document for document in case.documents if document.source_type == "locomo_observation"
    )
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert "D7:5 Caroline:" in observation_doc.text
    assert result["ok"] is True


def test_public_memory_benchmark_indexes_official_locomo_summaries(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "locomo10-summary-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-summary-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I checked in with Melanie today.",
                            }
                        ],
                        "session_1_date_time": "8 May, 2023",
                    },
                    "qa": [
                        {
                            "question": "What launch window did Caroline discuss?",
                            "answer": "Q4 launch window",
                            "evidence": [],
                            "category": 2,
                        },
                        {
                            "question": "What did Caroline decide during the event?",
                            "answer": "Atlas migration fallback",
                            "evidence": [],
                            "category": 3,
                        },
                    ],
                    "session_summary": {
                        "session_1_summary": (
                            "Caroline discussed the Q4 launch window with Melanie."
                        )
                    },
                    "event_summary": {
                        "events_session_1": {
                            "date": "8 May, 2023",
                            "Caroline": [
                                "Caroline decided the Atlas migration fallback during the event."
                            ],
                        }
                    },
                    "observation": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_cases(dataset)
    summary_docs = [
        document
        for case in cases
        for document in case.documents
        if document.source_type in {"locomo_session_summary", "locomo_event_summary"}
    ]
    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert {document.source_type for document in summary_docs} == {
        "locomo_session_summary",
        "locomo_event_summary",
    }
    assert any("Q4 launch window" in document.text for document in summary_docs)
    assert any("session_1 date: 8 May, 2023" in document.text for document in summary_docs)
    assert any("Atlas migration fallback" in document.text for document in summary_docs)
    assert result["ok"] is True
    assert result["benchmarks"][0]["metrics"]["capability_count"] == 2
    assert result["benchmarks"][0]["capability_breakdown"]["locomo_category_2"]["accuracy"] == 1.0
    assert result["benchmarks"][0]["capability_breakdown"]["locomo_category_3"]["case_count"] == 1


def test_public_memory_benchmark_accepts_official_longmemeval_shape(tmp_path: Path) -> None:
    dataset = tmp_path / "longmemeval_s_cleaned-mini.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "long-mini",
                    "question_type": "single-session-user",
                    "question": "What degree did I graduate with?",
                    "question_date": "2023/05/30 (Tue) 23:40",
                    "answer": "Business Administration",
                    "answer_session_ids": ["answer_session"],
                    "haystack_session_ids": ["answer_session"],
                    "haystack_dates": ["2023/05/20 (Sat) 02:21"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "I graduated with Business Administration.",
                            },
                            {
                                "role": "assistant",
                                "content": "Congratulations on the degree.",
                            },
                        ]
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["benchmarks"][0]["name"] == "longmemeval"
    assert result["metrics"]["longmemeval_case_count"] == 1
    assert result["cases"][0]["case_id"] == "long-mini"
    assert result["cases"][0]["capability"] == "information_extraction"
    assert (
        result["benchmarks"][0]["capability_breakdown"]["information_extraction"]["accuracy"] == 1.0
    )


def test_public_memory_benchmark_reports_longmemeval_capability_breakdown(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval_capabilities.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "long-knowledge-update",
                    "question_type": "knowledge-update",
                    "question": "Which provider should I use now?",
                    "question_date": "2023/06/01 (Thu) 10:00",
                    "answer": "Qdrant",
                    "answer_session_ids": ["answer_session"],
                    "haystack_session_ids": ["answer_session"],
                    "haystack_dates": ["2023/05/31 (Wed) 18:00"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "Use Qdrant as the current retrieval provider.",
                            }
                        ]
                    ],
                },
                {
                    "question_id": "long-temporal",
                    "question_type": "temporal-reasoning",
                    "question": "When did I review the launch notes?",
                    "question_date": "2023/06/01 (Thu) 10:00",
                    "answer": "Tuesday",
                    "answer_session_ids": ["temporal_session"],
                    "haystack_session_ids": ["temporal_session"],
                    "haystack_dates": ["2023/05/30 (Tue) 18:00"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "On Tuesday I reviewed the launch notes.",
                            }
                        ]
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)
    breakdown = result["benchmarks"][0]["capability_breakdown"]

    assert result["ok"] is True
    assert result["benchmarks"][0]["metrics"]["capability_count"] == 2
    assert breakdown["knowledge_update"]["case_count"] == 1
    assert breakdown["temporal_reasoning"]["accuracy"] == 1.0
    assert {case["capability"] for case in result["cases"]} == {
        "knowledge_update",
        "temporal_reasoning",
    }


def test_public_memory_benchmark_recalls_longmemeval_current_decision_without_now(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval_current_decision_no_now.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "long-current-decision-no-now",
                    "question_type": "knowledge-update",
                    "question": "What did I decide to use?",
                    "question_date": "2023/06/01 (Thu) 10:00",
                    "answer": "Qdrant",
                    "answer_session_ids": ["new_session"],
                    "haystack_session_ids": ["old_session", "new_session"],
                    "haystack_dates": [
                        "2023/05/20 (Sat) 10:00",
                        "2023/05/31 (Wed) 18:00",
                    ],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": (
                                    "Earlier I used Pinecone as the retrieval provider."
                                ),
                            }
                        ],
                        [
                            {
                                "role": "user",
                                "content": (
                                    "I switched away from Pinecone. Qdrant is the "
                                    "current retrieval provider I selected."
                                ),
                            }
                        ],
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["capability"] == "knowledge_update"
    assert result["cases"][0]["missing_terms"] == []


def test_public_memory_benchmark_accepts_longmemeval_numeric_answer(tmp_path: Path) -> None:
    dataset = tmp_path / "longmemeval_numeric_answer.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "long-numeric",
                    "question_type": "single-session-user",
                    "question": "How many pull requests did I review?",
                    "question_date": "2023/06/01 (Thu) 10:00",
                    "answer": 3,
                    "answer_session_ids": ["answer_session"],
                    "haystack_session_ids": ["answer_session"],
                    "haystack_dates": ["2023/05/31 (Wed) 18:00"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "I reviewed 3 pull requests today.",
                            }
                        ]
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["metrics"]["longmemeval_accuracy"] == 1.0


def test_public_memory_benchmark_uses_longmemeval_answer_session_ids_as_evidence(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "longmemeval_abstention_evidence.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "long-abstention",
                    "question_type": "single-session-user",
                    "question": "What pet did I mention named Luna instead of a hamster?",
                    "question_date": "2023/06/01 (Thu) 10:00",
                    "answer": (
                        "You did not mention this information. "
                        "You mentioned your cat Luna but not your hamster."
                    ),
                    "answer_session_ids": ["answer_session"],
                    "haystack_session_ids": ["answer_session", "distractor_session"],
                    "haystack_dates": [
                        "2023/05/31 (Wed) 18:00",
                        "2023/05/29 (Mon) 11:00",
                    ],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "My cat Luna needs a new carrier.",
                            }
                        ],
                        [
                            {
                                "role": "user",
                                "content": "I bought food for the neighbor's dog.",
                            }
                        ],
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_public_memory_benchmark(dataset_path=dataset, min_accuracy=1.0)

    assert result["ok"] is True
    assert result["cases"][0]["missing_terms"] == []
    assert result["metrics"]["longmemeval_accuracy"] == 1.0


def _longmemeval_row(
    case_id: str,
    question_type: str,
    question: str,
    marker: str,
) -> dict[str, object]:
    return {
        "benchmark": "longmemeval",
        "case_id": case_id,
        "question": question,
        "answer": marker,
        "documents": [{"title": case_id, "text": f"{case_id} stores {marker}."}],
        "metadata": {"question_type": question_type},
    }
