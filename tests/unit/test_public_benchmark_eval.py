from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server.public_benchmark import (
    load_public_benchmark_case_count,
    load_public_benchmark_dataset_profile,
    run_public_memory_benchmark,
)


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
