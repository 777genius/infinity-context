import json

from scripts.locomo_failure_analysis import _failures, _filter_failures, _summary, main


def test_locomo_failure_analysis_summarizes_failure_patterns(tmp_path) -> None:
    report = {
        "failures": [
            {
                "case_id": "locomo:conv-1:qa:1",
                "capability": "locomo_category_1",
                "reason": "missing_expected_terms",
                "question": "Which places did Maria visit?",
                "missing_terms": ["Spain", "dog shelter"],
                "missing_evidence_refs": ["D1:2", "D1:3"],
                "missing_evidence_ref_previews": ["D1:2: Maria visited Spain."],
            },
            {
                "case_id": "locomo:conv-2:qa:7",
                "capability": "locomo_category_3",
                "reason": "missing_expected_terms",
                "question": "Why did Maria pursue a new job?",
                "missing_terms": ["Spain"],
                "missing_evidence_refs": ["D4:5"],
            },
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    case_ids = tmp_path / "failed-case-ids.txt"
    summary_out = tmp_path / "summary.json"

    assert (
        main(
            (
                str(path),
                "--case-id-out",
                str(case_ids),
                "--summary-out",
                str(summary_out),
                "--top",
                "5",
            )
        )
        == 0
    )

    assert case_ids.read_text(encoding="utf-8").splitlines() == [
        "locomo:conv-1:qa:1",
        "locomo:conv-2:qa:7",
    ]
    summary = _summary(_failures(report), top=5)
    assert summary["failure_count"] == 2
    assert summary["capability_failure_count"] == {
        "locomo_category_1": 1,
        "locomo_category_3": 1,
    }
    assert summary["answer_shape_count"] == {"list": 1, "why": 1}
    assert summary["top_missing_terms"]["Spain"] == 2
    assert summary["top_missing_evidence_ref_previews"] == {
        "D1:2: Maria visited Spain.": 1
    }
    assert json.loads(summary_out.read_text(encoding="utf-8"))["failure_count"] == 2


def test_locomo_failure_analysis_filters_and_writes_benchmark_args(tmp_path) -> None:
    report = {
        "failures": [
            {
                "case_id": "locomo:conv-1:qa:1",
                "capability": "locomo_category_1",
                "reason": "missing_expected_terms",
            },
            {
                "case_id": "locomo:conv-2:qa:7",
                "capability": "locomo_category_3",
                "reason": "forbidden_terms_leaked",
            },
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    case_ids = tmp_path / "category-1-case-ids.txt"
    benchmark_args = tmp_path / "category-1.args"

    assert (
        main(
            (
                str(path),
                "--capability",
                "category_1",
                "--case-id-out",
                str(case_ids),
                "--benchmark-args-out",
                str(benchmark_args),
            )
        )
        == 0
    )

    assert case_ids.read_text(encoding="utf-8").splitlines() == [
        "locomo:conv-1:qa:1"
    ]
    assert benchmark_args.read_text(encoding="utf-8") == "--case-id locomo:conv-1:qa:1\n"


def test_filter_failures_matches_reason_and_capability() -> None:
    failures = (
        {
            "case_id": "a",
            "capability": "locomo_category_1",
            "reason": "missing_expected_terms",
        },
        {
            "case_id": "b",
            "capability": "locomo_category_1",
            "reason": "forbidden_terms_leaked",
        },
        {
            "case_id": "c",
            "capability": "locomo_category_3",
            "reason": "missing_expected_terms",
        },
    )

    filtered = _filter_failures(
        failures,
        capabilities=("locomo_category_1",),
        reasons=("missing_expected_terms",),
    )

    assert [item["case_id"] for item in filtered] == ["a"]


def test_locomo_failure_analysis_uses_question_preview_for_shapes_and_patterns() -> None:
    report = {
        "failures": [
            {
                "case_id": "a",
                "capability": "locomo_category_1",
                "reason": "missing_expected_terms",
                "question_preview": "What books has Maria read?",
            },
            {
                "case_id": "b",
                "capability": "locomo_category_5",
                "reason": "missing_expected_terms",
                "question_preview": "What is Maria's bowl a reminder of?",
            },
        ]
    }

    summary = _summary(_failures(report), top=5)

    assert summary["answer_shape_count"] == {"list": 1, "what": 1}
    assert summary["query_pattern_count"] == {
        "list_inventory": 1,
        "sentimental_reminder": 1,
    }
    assert summary["query_pattern_examples"]["list_inventory"] == [
        {"case_id": "a", "question": "What books has Maria read?"}
    ]


def test_locomo_failure_analysis_groups_root_cause_tags_from_diagnostics() -> None:
    report = {
        "failures": [
            {
                "case_id": "locomo:conv-1:qa:1",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "question_preview": "Why did Maria leave early?",
                "diagnostic_reason_codes": [
                    "judge_score_below_threshold",
                    "partial_expected_term_support",
                    "missing_evidence_refs",
                    "bundle_incomplete",
                    "missing_required_roles",
                    "weak_evidence_bundle",
                ],
                "diagnostics": {
                    "missing_evidence_terms": ["D1:2", "D1:3"],
                    "bundle": {
                        "missing_required_roles": ["bridge"],
                        "reason_codes": ["risk:low_answerability"],
                    },
                },
            },
            {
                "case_id": "locomo:conv-2:qa:4",
                "capability": "locomo_category_3",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": [
                    "judge_score_below_threshold",
                    "no_expected_term_support",
                    "missing_evidence_refs",
                ],
                "diagnostics": {"missing_evidence_terms": ["D4:5"]},
            },
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["primary_root_cause_count"] == {
        "retrieval:partial_expected_term_support": 1,
        "retrieval:no_expected_term_support": 1,
    }
    assert summary["root_cause_tag_count"]["evidence:missing_refs"] == 2
    assert summary["root_cause_tag_count"]["bundle:missing_role:bridge"] == 1
    assert summary["root_cause_tag_count"]["bundle:risk:low_answerability"] == 1
    assert summary["top_missing_evidence_refs"] == {"D1:2": 1, "D1:3": 1, "D4:5": 1}
    assert summary["root_cause_examples"]["retrieval:partial_expected_term_support"] == [
        {
            "case_id": "locomo:conv-1:qa:1",
            "capability": "locomo_category_2",
            "reason": "expected_terms_missing",
            "root_cause_tags": [
                "retrieval:partial_expected_term_support",
                "evidence:missing_refs",
                "bundle:missing_role:bridge",
                "bundle:incomplete",
                "bundle:weak",
                "bundle:risk:low_answerability",
                "judgment:score_below_threshold",
            ],
            "question": "Why did Maria leave early?",
            "diagnostic_reason_codes": [
                "judge_score_below_threshold",
                "partial_expected_term_support",
                "missing_evidence_refs",
                "bundle_incomplete",
                "missing_required_roles",
                "weak_evidence_bundle",
            ],
            "missing_required_roles": ["bridge"],
            "missing_evidence_ref_count": 2,
        }
    ]


def test_locomo_failure_analysis_limit_makes_small_canary_args(tmp_path) -> None:
    report = {
        "failures": [
            {"case_id": "a", "capability": "locomo_category_1"},
            {"case_id": "b", "capability": "locomo_category_1"},
            {"case_id": "c", "capability": "locomo_category_1"},
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    benchmark_args = tmp_path / "canary.args"

    assert (
        main(
            (
                str(path),
                "--limit",
                "2",
                "--benchmark-args-out",
                str(benchmark_args),
            )
        )
        == 0
    )

    assert benchmark_args.read_text(encoding="utf-8") == "--case-id a\n--case-id b\n"
