from __future__ import annotations

import json
from pathlib import Path

from memo_stack_server.evidence_bundle import build_quality_evidence_bundle


def test_quality_evidence_bundle_writes_scorecard_artifacts(tmp_path: Path) -> None:
    result = build_quality_evidence_bundle(output_dir=tmp_path)

    report_names = {Path(item["report_path"]).name for item in result["deterministic_reports"]}

    assert result["ok"] is True
    assert result["scorecard"]["maturity_score_10"] == 10.0
    assert result["scorecard"]["confidence_tier"] == "internal_deterministic"
    assert result["scorecard"]["top_library_comparison_ready"] is False
    assert report_names == {
        "small-golden.json",
        "quality-golden.json",
        "long-memory-golden.json",
        "auto-memory-golden.json",
        "graph-native-golden.json",
        "prompt-contract.json",
    }
    assert (tmp_path / "memory-quality-scorecard.json").exists()
    assert (tmp_path / "quality-evidence-bundle.json").exists()
    assert (tmp_path / "quality-evidence-manifest.json").exists()
    assert json.loads((tmp_path / "quality-evidence-bundle.json").read_text())["ok"] is True
    manifest = json.loads((tmp_path / "quality-evidence-manifest.json").read_text())
    artifact_names = {item["relative_path"] for item in manifest["artifacts"]}
    artifact_hashes = {item["sha256"] for item in manifest["artifacts"]}
    assert manifest["schema_version"] == 1
    assert manifest["suite"] == "memo-stack-quality-evidence-manifest"
    assert manifest["runtime"]["python_version"]
    assert artifact_names == {
        "small-golden.json",
        "quality-golden.json",
        "long-memory-golden.json",
        "auto-memory-golden.json",
        "graph-native-golden.json",
        "prompt-contract.json",
        "memory-quality-scorecard.json",
        "quality-evidence-bundle.json",
    }
    assert all(len(value) == 64 for value in artifact_hashes)


def test_quality_evidence_bundle_requires_existing_extra_reports(tmp_path: Path) -> None:
    missing = tmp_path / "missing-full-provider.json"

    try:
        build_quality_evidence_bundle(output_dir=tmp_path, extra_report_paths=(missing,))
    except ValueError as exc:
        assert "Evidence extra report does not exist" in str(exc)
    else:
        raise AssertionError("expected missing extra report to fail")


def test_quality_evidence_bundle_can_pass_strict_top_evidence_with_external_report(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "full-provider-agent-public.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-full-provider-canary",
                "ok": True,
                "checks": {
                    "fact_created": True,
                    "updated_fact_versioned": True,
                    "forgotten_fact_deleted": True,
                    "providers_are_healthy": True,
                    "context_provider_status_ok": True,
                    "mcp_provider_diagnostics_ok": True,
                    "mcp_search_has_graphiti_fact_after_worker": True,
                    "mcp_search_has_qdrant_document_chunk_after_worker": True,
                    "mcp_search_hides_old_fact_after_update": True,
                    "mcp_search_hides_deleted_fact": True,
                    "outbox_has_no_pending_or_dead": True,
                    "mcp_outbox_has_no_pending_or_dead": True,
                },
                "adapters": {
                    "qdrant": "ok",
                    "graphiti": "ok",
                    "embeddings": "ok",
                    "cognee": "disabled",
                },
                "mcp": {"ok": True},
                "agent_behavior": {
                    "suite": "memory_mcp_agent_behavior",
                    "ok": True,
                    "scenario_set": "realistic",
                    "metrics": {
                        "tool_choice_accuracy": 1.0,
                        "search_before_write_rate": 1.0,
                        "update_vs_duplicate_rate": 1.0,
                        "document_routing_accuracy": 1.0,
                        "answer_support_rate": 1.0,
                        "live_session_pass_rate": 1.0,
                        "transcript_corpus_pass_rate": 1.0,
                        "adversarial_pass_rate": 1.0,
                        "unsafe_write_count": 0,
                        "secret_leak_count": 0,
                        "cross_scope_leak_count": 0,
                        "stale_leak_count": 0,
                        "deleted_leak_count": 0,
                        "critical_safety_failures": 0,
                    },
                    "gates": {
                        "critical_safety_failures_zero": True,
                        "secret_leak_count_zero": True,
                        "unsafe_write_count_zero": True,
                        "cross_scope_leak_count_zero": True,
                        "stale_leak_count_zero": True,
                        "deleted_leak_count_zero": True,
                        "search_before_write_rate_min_0_90": True,
                        "update_vs_duplicate_rate_min_0_80": True,
                        "tool_choice_accuracy_min_0_80": True,
                        "answer_support_rate_min_0_80": True,
                        "live_session_pass_rate_min_0_80": True,
                        "transcript_corpus_pass_rate_min_0_80": True,
                        "adversarial_pass_rate_min_0_90": True,
                        "critical_scenarios_pass": True,
                    },
                },
                "public_benchmark": {
                    "suite": "public-memory-benchmark",
                    "ok": True,
                    "benchmarks": [
                        {
                            "name": "locomo",
                            "ok": True,
                            "metrics": {"accuracy": 0.947, "case_count": 600},
                        },
                        {
                            "name": "longmemeval",
                            "ok": True,
                            "metrics": {"accuracy": 0.902, "case_count": 500},
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_quality_evidence_bundle(
        output_dir=tmp_path / "evidence",
        extra_report_paths=(external_report,),
        require_top_evidence=True,
    )

    assert result["ok"] is True
    assert result["scorecard"]["confidence_tier"] == (
        "full_provider_agent_and_public_benchmark_evaluated"
    )
    assert result["scorecard"]["top_library_comparison_ready"] is True
    assert result["scorecard"]["evidence_gaps"] == []
    manifest = json.loads(((tmp_path / "evidence") / "quality-evidence-manifest.json").read_text())
    external_artifacts = [
        item for item in manifest["artifacts"] if item["kind"] == "external_report"
    ]
    assert result["manifest_path"].endswith("quality-evidence-manifest.json")
    assert len(external_artifacts) == 1
    assert external_artifacts[0]["path"] == str(external_report)
    assert external_artifacts[0]["relative_path"] is None
