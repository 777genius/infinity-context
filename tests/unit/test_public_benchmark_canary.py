from __future__ import annotations

import json
from pathlib import Path

from infinity_context_server import official_public_benchmark as canary

ROOT = Path(__file__).parents[2]


def test_official_public_benchmark_case_ids_route_by_benchmark_prefix() -> None:
    assert canary._case_ids_for_benchmark(  # noqa: SLF001
        ("locomo:conv-26:qa:70", "shared-case", "longmemeval:abc"),
        benchmark="locomo",
    ) == ("locomo:conv-26:qa:70", "shared-case")
    assert canary._case_ids_for_benchmark(  # noqa: SLF001
        ("locomo:conv-26:qa:70", "shared-case", "longmemeval:abc"),
        benchmark="longmemeval",
    ) == ("shared-case", "longmemeval:abc")


def test_official_public_benchmark_reports_unrouted_case_ids(tmp_path: Path) -> None:
    progress = tmp_path / "unrouted-progress.jsonl"
    result = canary.run_official_public_benchmark_canary(
        benchmark="longmemeval",
        max_cases=1,
        min_accuracy=1.0,
        case_ids=("locomo:conv-26:qa:70",),
        progress_out=progress,
    )
    progress_events = [
        json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is False
    assert result["metrics"]["benchmark_count"] == 0
    assert result["metrics"]["selected_benchmark_count"] == 1
    assert result["metrics"]["case_count"] == 0
    assert result["metrics"]["skipped_benchmark_count"] == 1
    assert result["checks"]["requested_case_ids_routed"] is False
    assert result["case_id_routing"] == {
        "longmemeval": {
            "requested_case_ids": [],
            "requested_case_id_count": 0,
            "skipped": True,
            "reason": "case_ids_target_other_benchmark",
        }
    }
    assert result["skipped_benchmarks"] == ["longmemeval"]
    assert result["dataset_sources"] == {}
    assert result["failures"] == [
        {
            "case_id": None,
            "category": "setup",
            "reason": "no_requested_case_ids_matched_selected_benchmarks",
            "requested_case_ids": ["locomo:conv-26:qa:70"],
            "selected_benchmarks": ["longmemeval"],
        }
    ]
    assert [event["event_type"] for event in progress_events] == [
        "official_suite_started",
        "official_benchmark_skipped",
        "official_suite_completed",
    ]
    assert progress_events[1]["benchmark"] == "longmemeval"
    assert progress_events[1]["reason"] == "case_ids_target_other_benchmark"
    assert progress_events[-1]["ok"] is False
    assert progress_events[-1]["skipped_benchmark_count"] == 1


def test_official_public_benchmark_cli_writes_interrupted_report(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    report = tmp_path / "interrupted-report.json"

    def interrupting_run(**_: object) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(canary, "run_official_public_benchmark_canary", interrupting_run)

    exit_code = canary.main(
        [
            "--benchmark",
            "locomo",
            "--report-out",
            str(report),
            "--case-id",
            "locomo:conv-26:qa:70",
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    written = json.loads(report.read_text(encoding="utf-8"))

    assert exit_code == 130
    assert printed["status"] == "interrupted"
    assert printed["ok"] is False
    assert printed["artifact_labels"] == {
        "progress": "interrupted-report.progress.jsonl",
        "checkpoint": "interrupted-report.checkpoint.json",
    }
    assert written["status"] == "interrupted"
    assert written["failures"] == [
        {
            "case_id": None,
            "category": "setup",
            "reason": "keyboard_interrupt",
        }
    ]


def test_official_public_benchmark_surfaces_missing_case_ids(
    tmp_path: Path,
) -> None:
    longmemeval = tmp_path / "longmemeval-mini.json"
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
        benchmark="longmemeval",
        longmemeval_dataset=longmemeval,
        max_cases=1,
        min_accuracy=1.0,
        case_ids=("longmemeval:long-mini", "longmemeval:missing-case"),
    )

    assert result["ok"] is False
    assert result["checks"]["requested_case_ids_found"] is False
    assert result["metrics"]["missing_case_id_count"] == 1
    assert result["case_selection"]["longmemeval"]["missing_case_ids"] == [
        "longmemeval:missing-case"
    ]
    assert {
        "case_id": "longmemeval:missing-case",
        "category": "setup",
        "reason": "requested_case_id_not_found",
    } in result["failures"]


def test_official_public_benchmark_surfaces_unsupported_locomo_case_ids(
    tmp_path: Path,
) -> None:
    locomo = tmp_path / "locomo-no-evidence-mini.json"
    locomo.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-no-evidence-mini",
                    "conversation": {
                        "session_1_date_time": "7 May 2023",
                        "session_1": [
                            {
                                "speaker": "Caroline",
                                "dia_id": "D1:1",
                                "text": "I joined a community event yesterday.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What event did Caroline join?",
                            "answer": "A community event",
                            "evidence": ["D1:1"],
                            "category": 1,
                        },
                        {
                            "question": "Would Melanie be considered a member?",
                            "answer": "Likely no",
                            "evidence": [],
                            "category": 3,
                        },
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
        case_ids=("locomo:conv-no-evidence-mini:qa:2",),
    )

    assert result["ok"] is False
    assert result["checks"]["requested_case_ids_found"] is True
    assert result["checks"]["requested_case_ids_supported"] is False
    assert result["metrics"]["unsupported_case_id_count"] == 1
    assert result["failures"] == []
    assert result["unsupported_cases"] == [
        {
            "case_id": "locomo:conv-no-evidence-mini:qa:2",
            "category": "unsupported",
            "reason": "requested_case_id_not_supported",
            "unsupported_reason": "official_locomo.no_retrieval_terms",
        }
    ]


def test_official_public_benchmark_filters_requested_capabilities(
    tmp_path: Path,
) -> None:
    longmemeval = tmp_path / "longmemeval-capability-filter.json"
    longmemeval.write_text(
        json.dumps(
            [
                {
                    "question_id": "info-mini",
                    "question_type": "single-session-user",
                    "question": "What city did I visit?",
                    "question_date": "2023/05/30 (Tue) 23:40",
                    "answer": "Lisbon",
                    "answer_session_ids": ["info_session"],
                    "haystack_session_ids": ["info_session"],
                    "haystack_dates": ["2023/05/20 (Sat) 02:21"],
                    "haystack_sessions": [[{"role": "user", "content": "I visited Lisbon."}]],
                },
                {
                    "question_id": "temporal-mini",
                    "question_type": "temporal-reasoning",
                    "question": "What degree did I graduate with?",
                    "question_date": "2023/06/01 (Thu) 12:00",
                    "answer": "Business Administration",
                    "answer_session_ids": ["answer_session"],
                    "haystack_session_ids": ["answer_session"],
                    "haystack_dates": ["2023/05/21 (Sun) 02:21"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "I graduated with Business Administration.",
                            }
                        ]
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    result = canary.run_official_public_benchmark_canary(
        benchmark="longmemeval",
        longmemeval_dataset=longmemeval,
        max_cases=5,
        min_accuracy=1.0,
        capabilities=("temporal-reasoning",),
    )

    assert result["ok"] is True
    assert result["requested_capabilities"] == ["temporal_reasoning"]
    assert result["checks"]["requested_capabilities_found"] is True
    assert result["metrics"]["case_count"] == 1
    assert result["metrics"]["missing_capability_count"] == 0
    assert [case["case_id"] for case in result["cases"]] == ["temporal-mini"]
    assert result["case_selection"]["longmemeval"]["requested_capabilities"] == [
        "temporal_reasoning"
    ]
    assert result["case_selection"]["longmemeval"]["selection_pool_case_count"] == 1


def test_official_public_benchmark_reports_missing_requested_capabilities(
    tmp_path: Path,
) -> None:
    longmemeval = tmp_path / "longmemeval-missing-capability.json"
    longmemeval.write_text(
        json.dumps(
            [
                {
                    "question_id": "info-mini",
                    "question_type": "single-session-user",
                    "question": "What city did I visit?",
                    "question_date": "2023/05/30 (Tue) 23:40",
                    "answer": "Lisbon",
                    "answer_session_ids": ["info_session"],
                    "haystack_session_ids": ["info_session"],
                    "haystack_dates": ["2023/05/20 (Sat) 02:21"],
                    "haystack_sessions": [[{"role": "user", "content": "I visited Lisbon."}]],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = canary.run_official_public_benchmark_canary(
        benchmark="longmemeval",
        longmemeval_dataset=longmemeval,
        max_cases=5,
        min_accuracy=1.0,
        capabilities=("temporal_reasoning",),
    )

    assert result["ok"] is False
    assert result["requested_capabilities"] == ["temporal_reasoning"]
    assert result["checks"]["requested_capabilities_found"] is False
    assert result["metrics"]["case_count"] == 0
    assert result["metrics"]["missing_capability_count"] == 1
    assert result["case_selection"]["longmemeval"]["missing_capabilities"] == ["temporal_reasoning"]
    assert {
        "case_id": "case_selection",
        "category": "setup",
        "reason": "requested_capability_not_found",
        "capability": "temporal_reasoning",
    } in result["failures"]


def test_official_public_benchmark_cli_reads_capability_env(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {}

    def capturing_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "status": "ok"}

    monkeypatch.setenv(
        "MEMORY_PUBLIC_BENCHMARK_CAPABILITIES",
        "temporal-reasoning,longmemeval:knowledge-update",
    )
    monkeypatch.setattr(canary, "run_official_public_benchmark_canary", capturing_run)

    exit_code = canary.main(["--benchmark", "longmemeval"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert captured["capabilities"] == (
        "temporal_reasoning",
        "longmemeval:knowledge_update",
    )


def test_official_public_benchmark_canary_merges_locomo_and_longmemeval_reports(
    tmp_path: Path,
) -> None:
    locomo = tmp_path / "locomo10-mini.json"
    longmemeval = tmp_path / "longmemeval-mini.json"
    report = tmp_path / "official-public-report.json"
    progress = tmp_path / "official-public-report.progress.jsonl"
    locomo_checkpoint = tmp_path / "official-public-report.checkpoint.locomo.json"
    longmemeval_checkpoint = tmp_path / "official-public-report.checkpoint.longmemeval.json"
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
    assert result["metrics"]["cases_per_second"] > 0
    assert result["metrics"]["estimated_remaining_ms"] == 0.0
    assert result["metrics"]["requested_parallelism_max"] == 1
    assert result["metrics"]["effective_parallelism_max"] == 1
    assert result["metrics"]["parallelism_degraded_count"] == 0
    assert result["metrics"]["parallelism_degraded"] is False
    assert result["checks"]["unique_case_ids"] is True
    assert result["competitive_floor_mode"] is True
    assert result["publishable_public_benchmark_candidate"] is True
    assert result["requested_max_cases"] == 1
    assert result["requested_min_accuracy"] == 1.0
    assert result["case_selection_strategy"] == canary.DEFAULT_CASE_SELECTION_STRATEGY
    assert result["artifact_labels"] == {
        "progress": progress.name,
        "checkpoint": "official-public-report.checkpoint.json",
    }
    assert set(result["case_selection"]) == {"locomo", "longmemeval"}
    assert result["case_selection"]["locomo"]["strategy"] == (
        canary.DEFAULT_CASE_SELECTION_STRATEGY
    )
    assert result["case_selection"]["longmemeval"]["strategy"] == (
        canary.DEFAULT_CASE_SELECTION_STRATEGY
    )
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
    assert result["dataset_sources"]["locomo"]["sha256"] == result["dataset_hashes"]["locomo"]
    assert result["dataset_sources"]["locomo"]["size_bytes"] == locomo.stat().st_size
    assert result["dataset_sources"]["locomo"]["case_count"] == 1
    assert result["provenance"]["generated_by"] == (
        "infinity_context_server.official_public_benchmark"
    )
    assert result["provenance"]["suite"] == "public-memory-benchmark"
    assert result["provenance"]["git"]["dirty"] in {True, False}
    assert report.exists()
    assert progress.exists()
    assert locomo_checkpoint.exists()
    assert longmemeval_checkpoint.exists()
    written = json.loads(report.read_text(encoding="utf-8"))
    progress_events = [
        json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()
    ]
    locomo_progress = json.loads(locomo_checkpoint.read_text(encoding="utf-8"))["progress"]
    longmemeval_progress = json.loads(longmemeval_checkpoint.read_text(encoding="utf-8"))[
        "progress"
    ]
    assert written["ok"] is True
    assert written["provenance"]["generated_by"] == (
        "infinity_context_server.official_public_benchmark"
    )
    event_types = [event["event_type"] for event in progress_events]
    official_events = [event for event in progress_events if "official_event_index" in event]
    assert event_types.count("run_started") == 2
    assert event_types.count("official_benchmark_started") == 2
    assert event_types.count("official_benchmark_completed") == 2
    assert event_types[0] == "official_suite_started"
    assert event_types[-1] == "official_suite_completed"
    assert [event["official_event_index"] for event in official_events] == list(
        range(1, len(official_events) + 1)
    )
    assert official_events[0]["selected_benchmarks"] == ["locomo", "longmemeval"]
    assert official_events[-1]["ok"] is True
    assert official_events[-1]["benchmark_count"] == 2
    assert official_events[-1]["case_count"] == 2
    assert locomo_progress["processed_case_count"] == 1
    assert longmemeval_progress["processed_case_count"] == 1


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
    assert result["dataset_sources"]["locomo"]["sha256"] == result["dataset_hashes"]["locomo"]
    assert result["source_urls"] == {"locomo": canary.LOCOMO_URL}
    assert result["competitive_floor_mode"] is False
    assert result["publishable_public_benchmark_candidate"] is False


def test_official_public_benchmark_reports_local_parallel_degraded_reason(
    tmp_path: Path,
) -> None:
    locomo = tmp_path / "locomo10-mini.json"
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
                            },
                            {
                                "speaker": "Melanie",
                                "dia_id": "D1:2",
                                "text": "I painted a blue sunrise yesterday.",
                            },
                        ],
                    },
                    "qa": [
                        {
                            "question": "Where did Caroline go?",
                            "answer": "LGBTQ support group",
                            "evidence": ["D1:1"],
                            "category": 1,
                        },
                        {
                            "question": "What did Melanie paint?",
                            "answer": "blue sunrise",
                            "evidence": ["D1:2"],
                            "category": 1,
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = canary.run_official_public_benchmark_canary(
        benchmark="locomo",
        locomo_dataset=locomo,
        max_cases=2,
        min_accuracy=1.0,
        case_selection_strategy=canary.CASE_SELECTION_FIRST,
        parallelism=2,
    )

    assert result["ok"] is True
    assert result["metrics"]["requested_parallelism_max"] == 2
    assert result["metrics"]["effective_parallelism_max"] == 1
    assert result["metrics"]["parallelism_degraded"] is True
    assert result["metrics"]["parallelism_degraded_count"] == 1
    assert result["metrics"]["parallelism_degraded_reasons"] == ["local_in_process_transport"]


def test_official_public_benchmark_script_is_thin_wrapper() -> None:
    script = (ROOT / "scripts" / "official_public_benchmark_canary.py").read_text(encoding="utf-8")

    assert "from infinity_context_server.official_public_benchmark import main" in script
    assert "run_public_memory_benchmark" not in script
    assert "urllib.request" not in script
