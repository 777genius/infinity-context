from __future__ import annotations

import json
from pathlib import Path

from memo_stack_server.evidence_bundle import build_quality_evidence_bundle


def _strict_provenance(
    *,
    generated_by: str,
    suite: str,
    commit: str = "abc123",
    dirty: bool | None = False,
    schema_version: int = 1,
    include_runtime: bool = True,
) -> dict[str, object]:
    provenance: dict[str, object] = {
        "schema_version": schema_version,
        "generated_by": generated_by,
        "suite": suite,
        "git": {"commit": commit},
    }
    if dirty is not None:
        provenance["git"]["dirty"] = dirty
    if include_runtime:
        provenance["runtime"] = {
            "python_version": "3.13.0",
            "platform": "darwin",
        }
    return provenance


def _minimal_full_provider_report(
    *,
    agent_behavior: dict[str, object] | None = None,
    public_benchmark: dict[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "suite": "memo-stack-full-provider-canary",
        "ok": True,
        "provenance": _strict_provenance(
            generated_by="scripts/clean_full_smoke.py",
            suite="memo-stack-full-provider-canary",
        ),
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
    }
    if agent_behavior is not None:
        report["agent_behavior"] = agent_behavior
    if public_benchmark is not None:
        report["public_benchmark"] = public_benchmark
    return report


def _minimal_agent_behavior_report(
    *,
    include_provenance: bool = True,
    commit: str = "abc123",
    dirty: bool = False,
) -> dict[str, object]:
    report: dict[str, object] = {
        "suite": "memory_mcp_agent_behavior",
        "ok": True,
        "scenario_set": "all",
        "metrics": {
            "scenario_count": 41,
            "tool_choice_accuracy": 1.0,
            "search_before_write_rate": 1.0,
            "update_vs_duplicate_rate": 1.0,
            "document_routing_accuracy": 1.0,
            "answer_support_rate": 1.0,
            "live_session_case_count": 11,
            "live_session_pass_rate": 1.0,
            "transcript_corpus_case_count": 5,
            "transcript_corpus_pass_rate": 1.0,
            "adversarial_case_count": 9,
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
        "scenarios": _agent_behavior_scenario_reports(),
    }
    if include_provenance:
        report["provenance"] = _strict_provenance(
            generated_by="memo_stack_mcp.agent_behavior_bench",
            suite="memory_mcp_agent_behavior",
            commit=commit,
            dirty=dirty,
        )
    return report


def _agent_behavior_scenario_reports() -> list[dict[str, object]]:
    scenarios: list[dict[str, object]] = []
    for index in range(5):
        scenarios.append(
            _agent_behavior_scenario_report(
                index,
                tags=("live_session", "transcript_corpus", "adversarial"),
            )
        )
    for _ in range(4):
        scenarios.append(
            _agent_behavior_scenario_report(
                len(scenarios),
                tags=("live_session", "adversarial"),
            )
        )
    while sum("live_session" in scenario["tags"] for scenario in scenarios) < 11:
        scenarios.append(
            _agent_behavior_scenario_report(len(scenarios), tags=("live_session",))
        )
    while len(scenarios) < 41:
        scenarios.append(_agent_behavior_scenario_report(len(scenarios), tags=("core",)))
    return scenarios


def _agent_behavior_scenario_report(
    index: int,
    *,
    tags: tuple[str, ...],
) -> dict[str, object]:
    return {
        "id": f"agent-scenario-{index}",
        "category": "answer",
        "tags": list(tags),
        "critical": True,
        "status": "passed",
        "tool_calls": [],
        "failures": [],
        "memory_checks": [],
    }


def _minimal_public_benchmark_report(
    *,
    include_provenance: bool = True,
    commit: str = "abc123",
    dirty: bool = False,
) -> dict[str, object]:
    report: dict[str, object] = {
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
    }
    if include_provenance:
        report["provenance"] = _strict_provenance(
            generated_by="memo_stack_server.official_public_benchmark",
            suite="public-memory-benchmark",
            commit=commit,
            dirty=dirty,
        )
    return report


def test_quality_evidence_bundle_writes_scorecard_artifacts(tmp_path: Path) -> None:
    result = build_quality_evidence_bundle(output_dir=tmp_path)

    report_names = {Path(item["report_path"]).name for item in result["deterministic_reports"]}

    assert result["ok"] is True
    assert result["scorecard"]["maturity_score_10"] == 10.0
    assert result["scorecard"]["confidence_tier"] == "internal_deterministic"
    assert result["scorecard"]["top_library_comparison_ready"] is False
    assert result["allow_dirty_top_evidence"] is False
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
    assert manifest["policy"]["schema_version"] == 1
    assert manifest["policy"]["suite"] == "memory-quality-scorecard"
    assert manifest["policy"]["require_top_evidence"] is False
    assert manifest["allow_dirty_top_evidence"] is False
    assert manifest["expected_git_commit"] is None
    assert manifest["policy"]["minimum_maturity_score_10"] == 9.0
    assert "auto-memory-golden" in manifest["policy"]["required_suites"]
    reports_by_name = {item["relative_path"]: item["report"] for item in manifest["artifacts"]}
    assert reports_by_name["small-golden.json"]["suite"] == "small-golden"
    assert reports_by_name["small-golden.json"]["ok"] is True
    assert reports_by_name["memory-quality-scorecard.json"]["suite"] == (
        "memory-quality-scorecard"
    )
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
                "provenance": {
                    "schema_version": 1,
                    "generated_by": "scripts/clean_full_smoke.py",
                    "suite": "memo-stack-full-provider-canary",
                    "run_id": "unit-run",
                    "project": "unit-project",
                    "git": {
                        "commit": "abc123",
                        "short_commit": "abc123",
                        "dirty": False,
                    },
                    "runtime": {
                        "python_version": "3.13.0",
                        "platform": "darwin",
                    },
                },
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
                    "scenario_set": "all",
                    "provenance": _strict_provenance(
                        generated_by="memo_stack_mcp.agent_behavior_bench",
                        suite="memory_mcp_agent_behavior",
                    ),
                    "metrics": {
                        "scenario_count": 41,
                        "tool_choice_accuracy": 1.0,
                        "search_before_write_rate": 1.0,
                        "update_vs_duplicate_rate": 1.0,
                        "document_routing_accuracy": 1.0,
                        "answer_support_rate": 1.0,
                        "live_session_case_count": 11,
                        "live_session_pass_rate": 1.0,
                        "transcript_corpus_case_count": 5,
                        "transcript_corpus_pass_rate": 1.0,
                        "adversarial_case_count": 9,
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
                    "scenarios": _agent_behavior_scenario_reports(),
                },
                "public_benchmark": {
                    "suite": "public-memory-benchmark",
                    "ok": True,
                    "provenance": _strict_provenance(
                        generated_by="memo_stack_server.official_public_benchmark",
                        suite="public-memory-benchmark",
                    ),
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
        expected_git_commit="abc123",
    )

    assert result["ok"] is True
    assert result["expected_git_commit"] == "abc123"
    assert result["allow_dirty_top_evidence"] is False
    assert result["scorecard"]["confidence_tier"] == (
        "full_provider_agent_and_public_benchmark_evaluated"
    )
    assert result["scorecard"]["top_library_comparison_ready"] is True
    assert result["scorecard"]["evidence_gaps"] == []
    manifest = json.loads(((tmp_path / "evidence") / "quality-evidence-manifest.json").read_text())
    policy = manifest["policy"]
    external_artifacts = [
        item for item in manifest["artifacts"] if item["kind"] == "external_report"
    ]
    assert policy["require_top_evidence"] is True
    assert manifest["allow_dirty_top_evidence"] is False
    assert manifest["expected_git_commit"] == "abc123"
    assert policy["full_provider"]["required_adapters"] == [
        "qdrant",
        "graphiti",
        "embeddings",
    ]
    assert "mcp_search_has_graphiti_fact_after_worker" in (
        policy["full_provider"]["required_checks"]
    )
    assert policy["agent_behavior"]["rate_floors"]["search_before_write_rate"] == 0.9
    assert "secret_leak_count" in policy["agent_behavior"]["zero_count_metrics"]
    assert policy["public_benchmark"]["competitive_floors"]["locomo"] == {
        "min_accuracy": 0.947,
        "min_case_count": 600,
    }
    assert policy["public_benchmark"]["competitive_floors"]["longmemeval"] == {
        "min_accuracy": 0.902,
        "min_case_count": 500,
    }
    assert result["manifest_path"].endswith("quality-evidence-manifest.json")
    assert len(external_artifacts) == 1
    assert external_artifacts[0]["path"] == str(external_report)
    assert external_artifacts[0]["relative_path"] is None
    assert external_artifacts[0]["report"]["suite"] == "memo-stack-full-provider-canary"
    assert external_artifacts[0]["report"]["provenance"]["generated_by"] == (
        "scripts/clean_full_smoke.py"
    )
    assert external_artifacts[0]["report"]["provenance"]["git"]["commit"] == "abc123"


def test_quality_evidence_bundle_requires_full_provider_nested_agent_provenance(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "full-provider-missing-agent-provenance.json"
    external_report.write_text(
        json.dumps(
            _minimal_full_provider_report(
                agent_behavior=_minimal_agent_behavior_report(include_provenance=False),
                public_benchmark=_minimal_public_benchmark_report(),
            )
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "missing provenance" in str(exc)
        assert "#agent_behavior" in str(exc)
    else:
        raise AssertionError("expected missing nested agent provenance to fail")


def test_quality_evidence_bundle_rejects_full_provider_nested_public_commit_mismatch(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "full-provider-stale-public-benchmark.json"
    external_report.write_text(
        json.dumps(
            _minimal_full_provider_report(
                agent_behavior=_minimal_agent_behavior_report(),
                public_benchmark=_minimal_public_benchmark_report(commit="old-commit"),
            )
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "commit mismatch" in str(exc)
        assert "#public_benchmark" in str(exc)
        assert "expected abc123, got old-commit" in str(exc)
    else:
        raise AssertionError("expected stale nested public benchmark evidence to fail")


def test_quality_evidence_bundle_rejects_full_provider_nested_agent_dirty_state(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "full-provider-dirty-agent-benchmark.json"
    external_report.write_text(
        json.dumps(
            _minimal_full_provider_report(
                agent_behavior=_minimal_agent_behavior_report(dirty=True),
                public_benchmark=_minimal_public_benchmark_report(),
            )
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "dirty worktree" in str(exc)
        assert "#agent_behavior" in str(exc)
    else:
        raise AssertionError("expected dirty nested agent evidence to fail")


def test_quality_evidence_bundle_rejects_stale_top_evidence_report(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "stale-full-provider.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-full-provider-canary",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="scripts/clean_full_smoke.py",
                    suite="memo-stack-full-provider-canary",
                    commit="old-commit",
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="new-commit",
        )
    except ValueError as exc:
        assert "commit mismatch" in str(exc)
        assert "expected new-commit, got old-commit" in str(exc)
    else:
        raise AssertionError("expected stale full-provider evidence to fail")


def test_quality_evidence_bundle_rejects_dirty_top_evidence_report(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "dirty-full-provider.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-full-provider-canary",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="scripts/clean_full_smoke.py",
                    suite="memo-stack-full-provider-canary",
                    dirty=True,
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "dirty worktree" in str(exc)
    else:
        raise AssertionError("expected dirty full-provider evidence to fail")


def test_quality_evidence_bundle_can_allow_dirty_top_evidence_for_local_diagnostics(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "dirty-diagnostic-full-provider.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-full-provider-canary",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="scripts/clean_full_smoke.py",
                    suite="memo-stack-full-provider-canary",
                    dirty=True,
                ),
            }
        ),
        encoding="utf-8",
    )

    result = build_quality_evidence_bundle(
        output_dir=tmp_path / "evidence",
        extra_report_paths=(external_report,),
        require_top_evidence=True,
        expected_git_commit="abc123",
        allow_dirty_top_evidence=True,
    )

    assert result["allow_dirty_top_evidence"] is True
    assert result["scorecard"]["top_library_comparison_ready"] is False
    manifest = json.loads(((tmp_path / "evidence") / "quality-evidence-manifest.json").read_text())
    external_artifact = next(
        item for item in manifest["artifacts"] if item["kind"] == "external_report"
    )
    assert manifest["allow_dirty_top_evidence"] is True
    assert external_artifact["report"]["provenance"]["git"]["dirty"] is True


def test_quality_evidence_bundle_requires_top_evidence_dirty_state(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "missing-dirty-full-provider.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memo-stack-full-provider-canary",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="scripts/clean_full_smoke.py",
                    suite="memo-stack-full-provider-canary",
                    dirty=None,
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "missing provenance dirty state" in str(exc)
    else:
        raise AssertionError("expected missing dirty state to fail")


def test_quality_evidence_bundle_requires_top_evidence_provenance(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "missing-provenance-full-provider.json"
    external_report.write_text(
        json.dumps({"suite": "memo-stack-full-provider-canary", "ok": True}),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="expected-commit",
        )
    except ValueError as exc:
        assert "missing provenance" in str(exc)
    else:
        raise AssertionError("expected missing full-provider provenance to fail")


def test_quality_evidence_bundle_requires_standalone_agent_top_evidence_provenance(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "agent-behavior.json"
    external_report.write_text(
        json.dumps({"suite": "memory_mcp_agent_behavior", "ok": True}),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="expected-commit",
        )
    except ValueError as exc:
        assert "missing provenance" in str(exc)
    else:
        raise AssertionError("expected missing standalone agent provenance to fail")


def test_quality_evidence_bundle_requires_standalone_public_benchmark_provenance(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "public-benchmark.json"
    external_report.write_text(
        json.dumps({"suite": "public-memory-benchmark", "ok": True}),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="expected-commit",
        )
    except ValueError as exc:
        assert "missing provenance" in str(exc)
    else:
        raise AssertionError("expected missing standalone public benchmark provenance to fail")


def test_quality_evidence_bundle_rejects_wrong_standalone_top_evidence_generator(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "agent-behavior-wrong-generator.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memory_mcp_agent_behavior",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="scripts/clean_full_smoke.py",
                    suite="memory_mcp_agent_behavior",
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "unsupported provenance generator" in str(exc)
    else:
        raise AssertionError("expected unsupported standalone top evidence generator to fail")


def test_quality_evidence_bundle_accepts_provenanced_standalone_top_reports(
    tmp_path: Path,
) -> None:
    agent_report = tmp_path / "agent-behavior.json"
    public_report = tmp_path / "public-benchmark.json"
    agent_report.write_text(
        json.dumps(
            {
                "suite": "memory_mcp_agent_behavior",
                "ok": True,
                "scenario_set": "all",
                "provenance": _strict_provenance(
                    generated_by="memo_stack_mcp.agent_behavior_bench",
                    suite="memory_mcp_agent_behavior",
                ),
                "metrics": {
                    "scenario_count": 41,
                    "tool_choice_accuracy": 1.0,
                    "search_before_write_rate": 1.0,
                    "update_vs_duplicate_rate": 1.0,
                    "document_routing_accuracy": 1.0,
                    "answer_support_rate": 1.0,
                    "live_session_case_count": 11,
                    "live_session_pass_rate": 1.0,
                    "transcript_corpus_case_count": 5,
                    "transcript_corpus_pass_rate": 1.0,
                    "adversarial_case_count": 9,
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
                "scenarios": _agent_behavior_scenario_reports(),
            }
        ),
        encoding="utf-8",
    )
    public_report.write_text(
        json.dumps(
            {
                "suite": "public-memory-benchmark",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="memo_stack_server.official_public_benchmark",
                    suite="public-memory-benchmark",
                ),
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
            }
        ),
        encoding="utf-8",
    )

    result = build_quality_evidence_bundle(
        output_dir=tmp_path / "evidence",
        extra_report_paths=(agent_report, public_report),
        require_top_evidence=True,
        expected_git_commit="abc123",
    )

    assert result["ok"] is False
    assert result["scorecard"]["top_library_comparison_ready"] is False
    assert result["scorecard"]["evidence_gaps"] == ["full_provider_canary_missing"]


def test_quality_evidence_bundle_rejects_wrong_top_evidence_schema_version(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "wrong-schema-agent-behavior.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memory_mcp_agent_behavior",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="memo_stack_mcp.agent_behavior_bench",
                    suite="memory_mcp_agent_behavior",
                    schema_version=2,
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "unsupported provenance schema" in str(exc)
    else:
        raise AssertionError("expected wrong provenance schema to fail")


def test_quality_evidence_bundle_rejects_top_evidence_suite_mismatch(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "suite-mismatch-public-benchmark.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "public-memory-benchmark",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="memo_stack_server.official_public_benchmark",
                    suite="memory_mcp_agent_behavior",
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "provenance suite mismatch" in str(exc)
    else:
        raise AssertionError("expected provenance suite mismatch to fail")


def test_quality_evidence_bundle_requires_top_evidence_runtime(
    tmp_path: Path,
) -> None:
    external_report = tmp_path / "missing-runtime-agent-behavior.json"
    external_report.write_text(
        json.dumps(
            {
                "suite": "memory_mcp_agent_behavior",
                "ok": True,
                "provenance": _strict_provenance(
                    generated_by="memo_stack_mcp.agent_behavior_bench",
                    suite="memory_mcp_agent_behavior",
                    include_runtime=False,
                ),
            }
        ),
        encoding="utf-8",
    )

    try:
        build_quality_evidence_bundle(
            output_dir=tmp_path / "evidence",
            extra_report_paths=(external_report,),
            require_top_evidence=True,
            expected_git_commit="abc123",
        )
    except ValueError as exc:
        assert "missing provenance runtime python_version" in str(exc)
    else:
        raise AssertionError("expected missing provenance runtime to fail")
