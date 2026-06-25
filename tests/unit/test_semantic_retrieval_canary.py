import json
from pathlib import Path

from infinity_context_server.eval import main
from infinity_context_server.eval_constants import (
    SEMANTIC_RETRIEVAL_API_CANARY_SUITE,
    SEMANTIC_RETRIEVAL_CANARY_SUITE,
)
from infinity_context_server.eval_semantic_retrieval_api_canary import (
    run_semantic_retrieval_api_canary,
)
from infinity_context_server.eval_semantic_retrieval_canary import (
    run_semantic_retrieval_canary,
)


def test_semantic_retrieval_canary_reports_false_positive_guards() -> None:
    result = run_semantic_retrieval_canary()

    assert result["suite"] == SEMANTIC_RETRIEVAL_CANARY_SUITE
    assert result["ok"] is True
    assert result["metrics"]["case_count"] == 7
    assert result["failures"] == []

    cases = {case["case_id"]: case for case in result["cases"]}
    ally = cases["ally_support_does_not_use_subject_identity_noise"]
    religious_noise = cases["religious_political_topic_penalized"]
    relative = cases["relative_time_message_query_keeps_conversation_recency"]

    assert "identity_bridge" not in ally["bounded_reasons"]
    assert "decomposition_ally_support_evidence" in ally["bounded_reasons"]
    assert religious_noise["signal_reason"] == "inference_religious_topic_only_noise"
    assert religious_noise["penalty"] > 0
    assert "decomposition_conversation_recency" in relative["bounded_reasons"]


def test_semantic_retrieval_canary_cli_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "semantic-retrieval-canary.json"

    main(
        [
            "run",
            "--suite",
            SEMANTIC_RETRIEVAL_CANARY_SUITE,
            "--report-out",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suite"] == SEMANTIC_RETRIEVAL_CANARY_SUITE
    assert report["ok"] is True
    assert report["gates"]["all_cases_passed"] is True


def test_semantic_retrieval_api_canary_proves_tight_context_precision() -> None:
    result = run_semantic_retrieval_api_canary()

    assert result["suite"] == SEMANTIC_RETRIEVAL_API_CANARY_SUITE
    assert result["ok"] is True
    assert result["metrics"]["case_count"] == 4
    assert result["metrics"]["top1_recall"] == 1.0
    assert result["metrics"]["top1_precision"] == 1.0
    assert result["metrics"]["tight_budget_forbidden_rendered_count"] == 0
    assert result["failures"] == []

    cases = {case["case_id"]: case for case in result["cases"]}
    assert cases["api_membership_self_identification_beats_ally_decoy"][
        "top_item_query_reason"
    ] == "community_membership_bridge"
    assert cases["api_ally_support_beats_subject_identity_decoy"][
        "top_item_query_reason"
    ] == "decomposition_ally_support_evidence"


def test_semantic_retrieval_api_canary_cli_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "semantic-retrieval-api-canary.json"

    main(
        [
            "run",
            "--suite",
            SEMANTIC_RETRIEVAL_API_CANARY_SUITE,
            "--report-out",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suite"] == SEMANTIC_RETRIEVAL_API_CANARY_SUITE
    assert report["ok"] is True
    assert report["gates"]["all_cases_passed"] is True
