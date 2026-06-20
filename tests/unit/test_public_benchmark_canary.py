from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server import official_public_benchmark as canary

ROOT = Path(__file__).parents[2]


def test_official_public_benchmark_canary_merges_locomo_and_longmemeval_reports(
    tmp_path: Path,
) -> None:
    locomo = tmp_path / "locomo10-mini.json"
    longmemeval = tmp_path / "longmemeval-mini.json"
    report = tmp_path / "official-public-report.json"
    locomo.write_text(
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
                }
            ]
        ),
        encoding="utf-8",
    )
    longmemeval.write_text(
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
                            }
                        ]
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = canary.run_official_public_benchmark_canary(
        locomo_dataset=locomo,
        longmemeval_dataset=longmemeval,
        max_cases=1,
        min_accuracy=1.0,
        competitive_floor=True,
        report_out=report,
    )

    assert result["ok"] is True
    assert result["suite"] == "public-memory-benchmark"
    assert result["benchmark_scope"] == "official_public_memory_retrieval_canary"
    assert result["metrics"]["benchmark_count"] == 2
    assert result["metrics"]["case_count"] == 2
    assert result["metrics"]["unique_case_id_count"] == 2
    assert result["metrics"]["duplicate_case_id_count"] == 0
    assert result["metrics"]["accuracy"] == 1.0
    assert result["checks"]["unique_case_ids"] is True
    assert result["competitive_floor_mode"] is True
    assert result["publishable_public_benchmark_candidate"] is True
    assert result["requested_max_cases"] == 1
    assert result["requested_min_accuracy"] == 1.0
    assert result["effective_case_limits"] == {"locomo": 600, "longmemeval": 500}
    assert result["effective_accuracy_floors"] == {"locomo": 1.0, "longmemeval": 1.0}
    assert result["competitive_floor_requirements"]["locomo"] == {
        "min_accuracy": 0.947,
        "min_case_count": 600,
    }
    assert {item["name"] for item in result["benchmarks"]} == {"locomo", "longmemeval"}
    assert set(result["dataset_hashes"]) == {"locomo", "longmemeval"}
    assert all(len(value) == 64 for value in result["dataset_hashes"].values())
    assert set(result["dataset_sources"]) == {"locomo", "longmemeval"}
    assert result["dataset_sources"]["locomo"]["source_kind"] == "local_override"
    assert result["dataset_sources"]["locomo"]["official_url"] == canary.LOCOMO_URL
    assert result["dataset_sources"]["locomo"]["path_label"] == locomo.name
    assert result["dataset_sources"]["locomo"]["sha256"] == result["dataset_hashes"][
        "locomo"
    ]
    assert result["dataset_sources"]["locomo"]["size_bytes"] == locomo.stat().st_size
    assert result["dataset_sources"]["locomo"]["case_count"] == 1
    assert result["provenance"]["generated_by"] == (
        "infinity_context_server.official_public_benchmark"
    )
    assert result["provenance"]["suite"] == "public-memory-benchmark"
    assert result["provenance"]["git"]["dirty"] in {True, False}
    assert report.exists()
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert written["provenance"]["generated_by"] == (
        "infinity_context_server.official_public_benchmark"
    )


def test_official_public_benchmark_canary_can_run_single_dataset(tmp_path: Path) -> None:
    locomo = tmp_path / "locomo10-mini.json"
    locomo.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-mini",
                    "conversation": {
                        "session_1": [
                            {
                                "speaker": "A",
                                "dia_id": "D1:1",
                                "text": "The project codename is Atlas.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What is the project codename?",
                            "answer": "Atlas",
                            "evidence": ["D1:1"],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = canary.run_official_public_benchmark_canary(
        benchmark="locomo",
        locomo_dataset=locomo,
        max_cases=1,
        min_accuracy=1.0,
    )

    assert result["ok"] is True
    assert result["metrics"]["benchmark_count"] == 1
    assert result["metrics"]["locomo_case_count"] == 1
    assert result["metrics"]["unique_case_id_count"] == 1
    assert result["metrics"]["duplicate_case_id_count"] == 0
    assert result["checks"]["unique_case_ids"] is True
    assert set(result["dataset_hashes"]) == {"locomo"}
    assert set(result["dataset_sources"]) == {"locomo"}
    assert result["dataset_sources"]["locomo"]["source_kind"] == "local_override"
    assert result["dataset_sources"]["locomo"]["sha256"] == result["dataset_hashes"][
        "locomo"
    ]
    assert result["source_urls"] == {"locomo": canary.LOCOMO_URL}
    assert result["competitive_floor_mode"] is False
    assert result["publishable_public_benchmark_candidate"] is False


def test_official_public_benchmark_script_is_thin_wrapper() -> None:
    script = (ROOT / "scripts" / "official_public_benchmark_canary.py").read_text(
        encoding="utf-8"
    )

    assert "from infinity_context_server.official_public_benchmark import main" in script
    assert "run_public_memory_benchmark" not in script
    assert "urllib.request" not in script
