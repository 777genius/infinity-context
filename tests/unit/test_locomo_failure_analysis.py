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
    assert summary["top_missing_evidence_sources"] == {"D1": 2, "D4": 1}
    assert summary["top_missing_evidence_ref_previews"] == {
        "D1:2: Maria visited Spain.": 1
    }
    assert json.loads(summary_out.read_text(encoding="utf-8"))["failure_count"] == 2


def test_locomo_failure_analysis_reads_failure_analysis_entries() -> None:
    report = {
        "failure_analysis": [
            {
                "case_id": "locomo:conv-1:qa:1",
                "capability": "locomo_category_2",
                "reason": "retrieval_or_judgment_failed",
                "missing_evidence_terms": ["D2:4", "source_session_turn_refs:D2:5"],
            }
        ]
    }

    summary = _summary(_failures(report), top=5)

    assert summary["failure_count"] == 1
    assert summary["case_ids"] == ["locomo:conv-1:qa:1"]
    assert summary["top_missing_evidence_refs"] == {
        "D2:4": 1,
        "source_session_turn_refs:D2:5": 1,
    }
    assert summary["top_missing_evidence_sources"] == {"D2": 2}


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


def test_locomo_failure_analysis_groups_prefixed_missing_evidence_refs_by_source() -> None:
    report = {
        "failures": [
            {
                "case_id": "prefixed",
                "diagnostics": {
                    "missing_evidence_terms": [
                        "source_turn_refs:D7:2",
                        "source_session_turn_refs:session_1:D7:3",
                        "locomo:private-conv:session_1:D8:4:raw-turn-id",
                        "unparseable-ref-without-turn",
                    ],
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=5)

    assert summary["top_missing_evidence_sources"] == {"D7": 2, "D8": 1}


def test_locomo_failure_analysis_filters_by_root_cause_for_gap_reruns(tmp_path) -> None:
    report = {
        "failures": [
            {
                "case_id": "window-miss",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["missing_evidence_refs"],
                "diagnostics": {
                    "missing_evidence_source_locality": {
                        "missing_turn_ref_count": 1,
                        "same_source_missing_count": 1,
                        "near_retrieved_window_count": 1,
                    }
                },
            },
            {
                "case_id": "answer-context-fallback",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["answer_context_fallback"],
            },
            {
                "case_id": "plain-missing-ref",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["missing_evidence_refs"],
            },
        ]
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    case_ids = tmp_path / "source-window-miss-case-ids.txt"
    benchmark_args = tmp_path / "source-window-miss.args"

    assert (
        main(
            (
                str(path),
                "--root-cause",
                "source-window-miss",
                "--case-id-out",
                str(case_ids),
                "--benchmark-args-out",
                str(benchmark_args),
            )
        )
        == 0
    )

    assert case_ids.read_text(encoding="utf-8").splitlines() == ["window-miss"]
    assert benchmark_args.read_text(encoding="utf-8") == "--case-id window-miss\n"


def test_filter_failures_matches_full_root_cause_tag() -> None:
    failures = (
        {
            "case_id": "fallback",
            "diagnostic_reason_codes": ["answer_context_fallback"],
        },
        {
            "case_id": "missing-ref",
            "diagnostic_reason_codes": ["missing_evidence_refs"],
        },
    )

    filtered = _filter_failures(
        failures,
        capabilities=(),
        reasons=(),
        root_causes=("answer_context:fallback",),
    )

    assert [item["case_id"] for item in filtered] == ["fallback"]


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


def test_locomo_failure_analysis_decomposes_bounded_list_answer_shape() -> None:
    report = {
        "failures": [
            {
                "case_id": "bounded-list",
                "capability": "locomo_category_1",
                "reason": "missing_expected_terms",
                "question": "Which two friends joined Maria for dinner?",
            },
            {
                "case_id": "who-list",
                "capability": "locomo_category_1",
                "reason": "missing_expected_terms",
                "question": "Who were Maria's dinner guests?",
            },
        ]
    }

    summary = _summary(_failures(report), top=5)

    assert summary["answer_shape_count"] == {"list": 2}
    assert summary["answer_shape_component_count"] == {"list": 2, "count": 1}


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
                    "selected_bundle_source_refless_evidence",
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
    assert (
        summary["root_cause_tag_count"]["evidence:selected_bundle_source_refless"]
        == 1
    )
    assert summary["root_cause_tag_count"]["bundle:missing_role:bridge"] == 1
    assert summary["root_cause_tag_count"]["bundle:risk:low_answerability"] == 1
    assert summary["top_missing_evidence_refs"] == {"D1:2": 1, "D1:3": 1, "D4:5": 1}
    assert summary["top_missing_evidence_sources"] == {"D1": 2, "D4": 1}
    assert summary["root_cause_examples"]["retrieval:partial_expected_term_support"] == [
        {
            "case_id": "locomo:conv-1:qa:1",
            "capability": "locomo_category_2",
            "reason": "expected_terms_missing",
            "root_cause_tags": [
                "retrieval:partial_expected_term_support",
                "evidence:missing_refs",
                "evidence:selected_bundle_source_refless",
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
                "selected_bundle_source_refless_evidence",
                "bundle_incomplete",
                "missing_required_roles",
                "weak_evidence_bundle",
            ],
            "missing_required_roles": ["bridge"],
            "missing_evidence_ref_count": 2,
        }
    ]


def test_locomo_failure_analysis_tags_missing_evidence_source_locality() -> None:
    report = {
        "failures": [
            {
                "case_id": "window-miss",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["missing_evidence_refs"],
                "diagnostics": {
                    "missing_evidence_terms": ["D1:9"],
                    "missing_evidence_source_locality": {
                        "missing_turn_ref_count": 1,
                        "same_source_missing_count": 1,
                        "near_retrieved_window_count": 1,
                        "source_absent_count": 0,
                    },
                },
            },
            {
                "case_id": "source-absent",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["missing_evidence_refs"],
                "diagnostics": {
                    "missing_evidence_terms": ["D7:2"],
                    "missing_evidence_source_locality": {
                        "missing_turn_ref_count": 1,
                        "same_source_missing_count": 0,
                        "near_retrieved_window_count": 0,
                        "source_absent_count": 1,
                    },
                },
            },
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["root_cause_tag_count"]["evidence:source_window_miss"] == 1
    assert summary["root_cause_tag_count"]["evidence:missing_source_absent"] == 1
    assert summary["provenance_gap_cause_count"] == {
        "near_retrieved_window": 1,
        "source_absent": 1,
    }
    assert summary["root_cause_examples"]["evidence:missing_refs"][0][
        "missing_evidence_source_locality"
    ] == {
        "missing_turn_ref_count": 1,
        "same_source_missing_count": 1,
        "near_retrieved_window_count": 1,
        "source_absent_count": 0,
        "cause_counts": {"near_retrieved_window": 1},
    }


def test_locomo_failure_analysis_prefers_reported_provenance_gap_causes() -> None:
    report = {
        "failures": [
            {
                "case_id": "same-source-far",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": ["missing_evidence_refs"],
                "diagnostics": {
                    "missing_evidence_terms": ["D4:9"],
                    "missing_evidence_source_locality": {
                        "missing_turn_ref_count": 1,
                        "same_source_missing_count": 1,
                        "near_retrieved_window_count": 0,
                        "source_absent_count": 0,
                        "cause_counts": {"same_source_miss": 1},
                    },
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["provenance_gap_cause_count"] == {"same_source_miss": 1}
    assert summary["root_cause_examples"]["evidence:missing_refs"][0][
        "missing_evidence_source_locality"
    ]["cause_counts"] == {"same_source_miss": 1}


def test_locomo_failure_analysis_tags_answer_context_gaps() -> None:
    report = {
        "failures": [
            {
                "case_id": "answer-context-gap",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": [
                    "answer_context_fallback",
                    "answer_context_source_refless",
                    "answer_context_missing_required_roles",
                    "answer_context_backfilled_retrieval",
                    "answer_context_risk_reasons_present",
                ],
                "diagnostics": {
                    "answer_context": {
                        "present": True,
                        "source": "retrieval_slice",
                        "fallback_reason": "no_bundle_items_within_cutoff",
                        "memory_count": 2,
                        "source_ref_item_count": 0,
                        "source_refless_item_count": 2,
                        "backfilled_retrieval_item_count": 1,
                        "missing_required_roles": ["bridge"],
                        "risk_reason_codes": ["risk:retrieval_backfill"],
                    },
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["root_cause_tag_count"]["answer_context:fallback"] == 1
    assert summary["root_cause_tag_count"]["answer_context:source_refless"] == 1
    assert (
        summary["root_cause_tag_count"]["answer_context:missing_required_roles"] == 1
    )
    assert summary["root_cause_tag_count"]["answer_context:backfilled_retrieval"] == 1
    assert summary["root_cause_tag_count"]["answer_context:risk_reasons"] == 1
    assert (
        summary["root_cause_tag_count"]["answer_context:risk:retrieval_backfill"]
        == 1
    )
    assert summary["answer_context_risk_reason_count"] == {
        "risk:retrieval_backfill": 1
    }
    assert summary["root_cause_examples"]["answer_context:fallback"] == [
        {
            "case_id": "answer-context-gap",
            "capability": "locomo_category_2",
            "reason": "expected_terms_missing",
            "root_cause_tags": [
                "answer_context:fallback",
                "answer_context:source_refless",
                "answer_context:missing_required_roles",
                "answer_context:backfilled_retrieval",
                "answer_context:risk_reasons",
                "answer_context:risk:retrieval_backfill",
            ],
            "diagnostic_reason_codes": [
                "answer_context_fallback",
                "answer_context_source_refless",
                "answer_context_missing_required_roles",
                "answer_context_backfilled_retrieval",
                "answer_context_risk_reasons_present",
            ],
            "answer_context": {
                "source": "retrieval_slice",
                "memory_count": 2,
                "source_ref_item_count": 0,
                "source_refless_item_count": 2,
                "backfilled_retrieval_item_count": 1,
                "fallback_reason": "no_bundle_items_within_cutoff",
                "missing_required_roles": ["bridge"],
                "risk_reason_codes": ["risk:retrieval_backfill"],
            },
        }
    ]


def test_locomo_failure_analysis_counts_answer_context_identity_provenance() -> None:
    report = {
        "failures": [
            {
                "case_id": "identity-only",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": [
                    "answer_context_fallback",
                    "answer_context_source_refless",
                ],
                "diagnostics": {
                    "answer_context": {
                        "present": True,
                        "source": "retrieval_slice",
                        "fallback_reason": "no_bundle_items_within_cutoff",
                        "memory_count": 2,
                        "source_ref_count": 0,
                        "source_ref_item_count": 0,
                        "source_refless_item_count": 2,
                        "source_identity_ref_count": 3,
                        "source_identity_item_count": 2,
                        "source_identity_ref_omitted_count": 1,
                        "source_identity_ref_sample_limit": 8,
                        "source_identity_item_omitted_count": 1,
                        "source_identity_item_sample_limit": 8,
                        "backfilled_retrieval_item_count": 1,
                    },
                },
            },
            {
                "case_id": "source-ref-grounded",
                "capability": "locomo_category_1",
                "reason": "expected_terms_missing",
                "diagnostics": {
                    "answer_context": {
                        "present": True,
                        "source": "evidence_bundle",
                        "memory_count": 1,
                        "source_ref_count": 1,
                        "source_ref_item_count": 1,
                        "source_refless_item_count": 0,
                    },
                },
            },
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["answer_context_provenance_count"] == {
        "present": 2,
        "source_refless_items_present": 1,
        "source_identity_refs_present": 1,
        "source_identity_items_present": 1,
        "identity_only_provenance_present": 1,
        "source_identity_ref_samples_omitted": 1,
        "source_identity_item_samples_omitted": 1,
        "fallback_present": 1,
        "backfilled_retrieval_present": 1,
        "source_refs_present": 1,
    }
    assert (
        summary["root_cause_tag_count"][
            "answer_context:identity_only_provenance"
        ]
        == 1
    )
    assert summary["root_cause_examples"]["answer_context:fallback"][0][
        "answer_context"
    ] == {
        "source": "retrieval_slice",
        "memory_count": 2,
        "source_ref_item_count": 0,
        "source_refless_item_count": 2,
        "backfilled_retrieval_item_count": 1,
        "source_identity_ref_count": 3,
        "source_identity_ref_omitted_count": 1,
        "source_identity_ref_sample_limit": 8,
        "source_identity_item_count": 2,
        "source_identity_item_omitted_count": 1,
        "source_identity_item_sample_limit": 8,
        "fallback_reason": "no_bundle_items_within_cutoff",
    }


def test_locomo_failure_analysis_tags_selected_evidence_weakness() -> None:
    report = {
        "failures": [
            {
                "case_id": "weak-selected-evidence",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": [
                    "selected_low_answerability_evidence",
                    "selected_weak_source_locality_evidence",
                ],
                "diagnostics": {
                    "bundle": {
                        "selected_low_answerability_count": 2,
                        "selected_weak_source_locality_count": 1,
                    }
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["primary_root_cause_count"] == {
        "evidence:selected_low_answerability": 1
    }
    assert summary["root_cause_tag_count"][
        "evidence:selected_low_answerability"
    ] == 1
    assert summary["root_cause_tag_count"][
        "evidence:selected_weak_source_locality"
    ] == 1
    assert summary["root_cause_examples"]["evidence:selected_low_answerability"] == [
        {
            "case_id": "weak-selected-evidence",
            "capability": "locomo_category_2",
            "reason": "expected_terms_missing",
            "root_cause_tags": [
                "evidence:selected_low_answerability",
                "evidence:selected_weak_source_locality",
            ],
            "diagnostic_reason_codes": [
                "selected_low_answerability_evidence",
                "selected_weak_source_locality_evidence",
            ],
            "selected_evidence_weakness": {
                "selected_low_answerability_count": 2,
                "selected_weak_source_locality_count": 1,
            },
        }
    ]


def test_locomo_failure_analysis_summarizes_temporal_grounding_issue_causes() -> None:
    report = {
        "failures": [
            {
                "case_id": "temporal-gap",
                "capability": "locomo_category_5",
                "reason": "expected_terms_missing",
                "diagnostic_reason_codes": [
                    "selected_temporal_grounding_issues"
                ],
                "diagnostics": {
                    "temporal_grounding": {
                        "schema_version": "failure_temporal_grounding.v1",
                        "temporal_case": True,
                        "selected_item_count": 7,
                        "strong_item_count": 0,
                        "issue_item_count": 7,
                        "issue_reason_counts": {
                            "missing_source_window": 7,
                            "missing_date_or_range": 7,
                        },
                        "issue_samples": [
                            {
                                "case_id": "temporal-gap",
                                "group": "temporal",
                                "item_id": f"temporal-gap-{index}",
                                "role": "temporal_support",
                                "query_roles": ["temporal_support"],
                                "source_refs": [],
                                "issue_reasons": [
                                    "missing_source_window",
                                    "missing_date_or_range",
                                ],
                                "grounding_signals": {
                                    "source_window": False,
                                    "session_boundary": False,
                                    "date_or_range": False,
                                    "temporal_order": False,
                                },
                                "text": "must not be copied",
                            }
                            for index in range(4)
                        ],
                    }
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["temporal_grounding_issue_reason_count"] == {
        "missing_source_window": 7,
        "missing_date_or_range": 7,
    }
    assert summary["root_cause_tag_count"]["temporal_grounding:issue"] == 1
    assert (
        summary["root_cause_tag_count"]["temporal_grounding:missing_source_window"]
        == 1
    )
    assert summary["temporal_grounding_issue_examples"]["missing_source_window"] == [
        {
            "case_id": "temporal-gap",
            "capability": "locomo_category_5",
            "reason": "expected_terms_missing",
            "issue_reason": "missing_source_window",
            "issue_reason_count": 7,
            "issue_samples": [
                {
                    "case_id": "temporal-gap",
                    "group": "temporal",
                    "item_id": "temporal-gap-0",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                    "source_refs": [],
                    "issue_reasons": [
                        "missing_source_window",
                        "missing_date_or_range",
                    ],
                    "grounding_signals": {
                        "source_window": False,
                        "session_boundary": False,
                        "date_or_range": False,
                        "temporal_order": False,
                    },
                },
                {
                    "case_id": "temporal-gap",
                    "group": "temporal",
                    "item_id": "temporal-gap-1",
                    "role": "temporal_support",
                    "query_roles": ["temporal_support"],
                    "source_refs": [],
                    "issue_reasons": [
                        "missing_source_window",
                        "missing_date_or_range",
                    ],
                    "grounding_signals": {
                        "source_window": False,
                        "session_boundary": False,
                        "date_or_range": False,
                        "temporal_order": False,
                    },
                },
            ],
        }
    ]
    assert "text" not in summary["temporal_grounding_issue_examples"][
        "missing_source_window"
    ][0]["issue_samples"][0]
    assert len(
        summary["root_cause_examples"]["temporal_grounding:issue"][0][
            "temporal_grounding"
        ]["issue_samples"]
    ) == 2


def test_locomo_failure_analysis_summarizes_query_role_gap_causes() -> None:
    report = {
        "failures": [
            {
                "case_id": "query-role-gap",
                "capability": "locomo_category_2",
                "reason": "expected_terms_missing",
                "diagnostics": {
                    "query_role_gap_breakdown": {
                        "role_gap_count": 1,
                        "role_family_gap_count": 1,
                        "required_role_coverage_gap_count": 1,
                        "role_gaps": {
                            "multi_hop_bridge": {
                                "candidate_count": 3,
                                "lifted_candidate_count": 1,
                                "selected_item_count": 0,
                                "bridge_query_hit_candidate_count": 2,
                                "bridge_query_hit_selected_count": 0,
                                "gap_reasons": [
                                    "not_selected",
                                    "bridge_hit_not_selected",
                                ],
                                "samples": ["raw text must not be copied"],
                            }
                        },
                        "role_family_gaps": {
                            "multi_hop": {
                                "candidate_count": 3,
                                "lifted_candidate_count": 1,
                                "selected_item_count": 0,
                                "gap_reasons": ["not_selected"],
                            }
                        },
                    }
                },
            }
        ]
    }

    summary = _summary(_failures(report), top=10)

    assert summary["primary_root_cause_count"] == {"query_role_gap:present": 1}
    assert summary["root_cause_tag_count"] == {
        "query_role_gap:present": 1,
        "query_role_gap:not_selected": 1,
        "query_role_gap:bridge_hit_not_selected": 1,
        "query_role_gap:required_role_coverage": 1,
    }
    assert summary["query_role_gap_reason_count"] == {
        "not_selected": 2,
        "bridge_hit_not_selected": 1,
    }
    assert summary["query_role_gap_role_count"] == {
        "multi_hop_bridge": 1,
        "multi_hop": 1,
    }
    assert summary["root_cause_examples"]["query_role_gap:present"] == [
        {
            "case_id": "query-role-gap",
            "capability": "locomo_category_2",
            "reason": "expected_terms_missing",
            "root_cause_tags": [
                "query_role_gap:present",
                "query_role_gap:not_selected",
                "query_role_gap:bridge_hit_not_selected",
                "query_role_gap:required_role_coverage",
            ],
            "query_role_gap": {
                "role_gap_count": 1,
                "role_family_gap_count": 1,
                "required_role_coverage_gap_count": 1,
                "gap_reason_counts": {
                    "not_selected": 2,
                    "bridge_hit_not_selected": 1,
                },
                "gap_role_counts": {
                    "multi_hop_bridge": 1,
                    "multi_hop": 1,
                },
                "top_role_gaps": [
                    {
                        "role": "multi_hop_bridge",
                        "gap_reasons": [
                            "not_selected",
                            "bridge_hit_not_selected",
                        ],
                        "candidate_count": 3,
                        "lifted_candidate_count": 1,
                        "bridge_query_hit_candidate_count": 2,
                    }
                ],
                "top_role_family_gaps": [
                    {
                        "role": "multi_hop",
                        "gap_reasons": ["not_selected"],
                        "candidate_count": 3,
                        "lifted_candidate_count": 1,
                    }
                ],
            },
        }
    ]
    assert "raw text must not be copied" not in json.dumps(summary)


def test_locomo_failure_analysis_summary_bounds_text_lists_and_dynamic_keys() -> None:
    long_text = "x" * 320
    failures = [
        {
            "case_id": f"case-{index}",
            "capability": f"capability-{index}",
            "reason": f"reason-{index}-{long_text}",
            "question": f"What places are relevant? {long_text}",
            "diagnostic_reason_codes": [
                "answer_context_fallback",
                "answer_context_missing_required_roles",
                *[f"diagnostic-{item}" for item in range(12)],
            ],
            "diagnostics": {
                "answer_context": {
                    "present": True,
                    "source": "retrieval_slice",
                    "memory_count": 2,
                    "source_ref_item_count": 0,
                    "source_refless_item_count": 2,
                    "backfilled_retrieval_item_count": 1,
                    "fallback_reason": long_text,
                    "missing_required_roles": [
                        f"role-{item}" for item in range(12)
                    ],
                    "risk_reason_codes": [f"risk-{item}" for item in range(12)],
                },
                "temporal_grounding": {
                    "issue_item_count": 1,
                    "issue_reason_counts": {
                        f"issue-{index}-{item}-{long_text}": 1
                        for item in range(4)
                    },
                    "issue_samples": [
                        {
                            "case_id": f"case-{index}",
                            "source_refs": [f"D1:{item}" for item in range(12)],
                            "issue_reasons": [
                                f"issue-{index}-{item}-{long_text}"
                                for item in range(12)
                            ],
                            "grounding_signals": {
                                f"signal-{item}": True for item in range(30)
                            },
                            "text": "raw temporal text must stay out",
                        }
                    ],
                },
            },
        }
        for index in range(6)
    ]

    summary = _summary(failures, top=3)

    assert len(summary["case_ids"]) == 3
    assert len(summary["capability_failure_count"]) == 3
    assert len(summary["reason_count"]) == 3
    assert len(summary["capability_reason_count"]) == 3
    assert len(summary["temporal_grounding_issue_reason_count"]) == 3
    answer_context = summary["root_cause_examples"]["temporal_grounding:issue"][0][
        "answer_context"
    ]
    assert answer_context["fallback_reason"] == f"{long_text[:237]}..."
    assert len(answer_context["missing_required_roles"]) == 8
    assert len(answer_context["risk_reason_codes"]) == 8
    example = next(iter(summary["temporal_grounding_issue_examples"].values()))[0]
    sample = example["issue_samples"][0]
    assert len(sample["source_refs"]) == 8
    assert len(sample["issue_reasons"]) == 8
    assert len(sample["grounding_signals"]) == 20
    serialized = json.dumps(summary, sort_keys=True)
    assert long_text not in serialized
    assert "raw temporal text must stay out" not in serialized


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
