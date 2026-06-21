from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from infinity_context_server.public_benchmark import (
    BenchmarkDocumentInput,
    BenchmarkHttpResponsePort,
    PublicBenchmarkCase,
    _execute_cases,
    _load_cases,
    load_public_benchmark_case_count,
    load_public_benchmark_dataset_profile,
    run_public_memory_benchmark,
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
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert "dataset_path" not in written
    assert written["dataset_path_label"] == dataset.name
    assert str(tmp_path) not in report.read_text(encoding="utf-8")
    assert written["dataset_hash"] == result["dataset_hash"]
    assert written["dataset_sources"] == result["dataset_sources"]
    assert written["provenance"]["generated_by"] == "infinity_context_server.public_benchmark"


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
    assert (
        load_public_benchmark_case_count(dataset_path=dataset, benchmark="longmemeval")
        == 1
    )
    profile = load_public_benchmark_dataset_profile(dataset_path=dataset)
    assert profile["case_count"] == 2
    assert profile["unique_case_id_count"] == 2
    assert profile["duplicate_case_id_count"] == 0
    assert profile["benchmark_counts"] == {"locomo": 1, "longmemeval": 1}
    assert profile["dataset_path_label"] == dataset.name
    assert len(str(profile["dataset_hash"])) == 64


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
    assert result["ok"] is True


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
