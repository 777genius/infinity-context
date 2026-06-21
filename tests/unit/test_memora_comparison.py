import ast
import importlib.util
import json
from pathlib import Path

from infinity_context_server.memora_comparison import (
    DIRECT_MEMORA_SMOKE_REQUIREMENTS,
    build_memora_agent_memory_comparison,
)


def _passing_memora_smoke() -> dict[str, object]:
    return {
        "system": "agentic-box/memora",
        "mode": "direct_mcp_stdio",
        "scenario_set": "prod_realistic_coding_agent_memory_v1",
        "scenarios": [
            {"id": "architecture_decision_remember"},
            {"id": "architecture_decision_update"},
            {"id": "cross_project_scope_filter"},
            {"id": "adr_document_fragment_recall"},
            {"id": "source_backed_digest"},
            {"id": "explicit_delete"},
            {"id": "portable_export"},
        ],
        "embedding_model": "tfidf",
        "llm_enabled": False,
        "tool_count": 42,
        "document_fragment_count": 4,
        "provenance": {
            "schema_version": 1,
            "generated_by": "scripts/memora_direct_mcp_smoke.py",
            "suite": "memora-direct-mcp-smoke",
            "run_id": "prod_realistic_coding_agent_memory_v1",
            "project": "infinity-context-competitor-evidence",
            "git": {"commit": "abc123", "short_commit": "abc123", "dirty": False},
            "runtime": {"python_version": "3.13.0", "platform": "unit"},
        },
        "checks": {check_id: True for check_id in DIRECT_MEMORA_SMOKE_REQUIREMENTS},
        "ok": True,
    }


def test_comparison_prefers_infinity_context_for_governed_agent_memory() -> None:
    report = build_memora_agent_memory_comparison(memora_direct_smoke=_passing_memora_smoke())

    assert report["overall"]["winner"] == "infinity_context"
    assert report["overall"]["infinity_context_score"] > report["overall"]["memora_score"]
    assert report["recommendations"][1]["winner"] == "infinity_context"


def test_comparison_credits_memora_direct_smoke_strengths() -> None:
    report = build_memora_agent_memory_comparison(memora_direct_smoke=_passing_memora_smoke())

    smoke = report["direct_memora_smoke"]
    assert smoke["status"] == "passed"
    assert smoke["tool_count"] == 42
    assert smoke["scenario_count"] == 7
    assert smoke["failed_checks"] == []
    assert smoke["provenance"]["generated_by"] == "scripts/memora_direct_mcp_smoke.py"
    assert smoke["provenance"]["git"]["commit"] == "abc123"

    by_id = {item["id"]: item for item in report["dimensions"]}
    assert by_id["retrieval_and_digest_quality"]["winner"] == "memora"
    assert by_id["retrieval_and_digest_quality"]["infinity_context_score"] == 7.8
    assert by_id["large_docs_and_architecture_notes"]["winner"] == "infinity_context"
    assert by_id["large_docs_and_architecture_notes"]["infinity_context_score"] >= 9.4
    assert by_id["local_mcp_visual_ux"]["winner"] == "memora"
    assert by_id["local_mcp_visual_ux"]["memora_score"] > by_id["local_mcp_visual_ux"][
        "infinity_context_score"
    ]
    assert by_id["graph_relationships"]["infinity_context_score"] > by_id["graph_relationships"][
        "memora_score"
    ]


def test_comparison_does_not_overclaim_when_memora_was_not_run() -> None:
    report = build_memora_agent_memory_comparison()

    assert report["direct_memora_smoke"]["status"] == "not_run"
    assert report["infinity_context_public_benchmark"]["status"] == "not_provided"
    assert report["infinity_context_production_audit"]["status"] == "not_provided"
    assert "provenance" not in report["direct_memora_smoke"]
    assert report["evidence_policy"]["competitor_paid_openai_llm_mode_verified"] is False
    assert (
        "Do not claim Memora failed production OpenAI mode."
        in report["evidence_policy"]["do_not_claim"]
    )
    assert (
        "Do not claim Infinity Context live provider proof is current "
        "unless production audit passes."
        in report["evidence_policy"]["do_not_claim"]
    )
    assert (
        "Do not claim Infinity Context has top-tier public retrieval "
        "quality without a fresh large LoCoMo/LongMemEval report."
        in report["evidence_policy"]["do_not_claim"]
    )


def test_comparison_summarizes_current_public_benchmark_and_audit_gaps() -> None:
    report = build_memora_agent_memory_comparison(
        public_benchmark_report={
            "ok": True,
            "suite": "public-memory-benchmark",
            "metrics": {
                "case_count": 1100,
                "accuracy": 0.8245,
                "locomo_accuracy": 0.7283,
                "longmemeval_accuracy": 0.94,
                "duplicate_case_id_count": 0,
            },
            "checks": {"unique_case_ids": True},
            "benchmarks": [
                {
                    "name": "locomo",
                    "capability_breakdown": {
                        "locomo_category_1": {"accuracy": 0.4286, "case_count": 126},
                        "locomo_category_2": {"accuracy": 0.9524, "case_count": 126},
                    },
                },
                {
                    "name": "longmemeval",
                    "capability_breakdown": {
                        "multi_session_reasoning": {"accuracy": 0.9023, "case_count": 133},
                    },
                },
            ],
            "provenance": {
                "generated_by": "infinity_context_server.official_public_benchmark",
                "suite": "public-memory-benchmark",
                "git": {"short_commit": "4bd72bf", "dirty": False},
            },
        },
        production_goal_audit={
            "ok": False,
            "git": {"short_commit": "4bd72bf", "dirty": False},
            "failures": ["Live provider proof must be generated for the current git commit"],
            "blocked_requirements": [{"area": "live_provider_proof"}],
            "reports": {"docker": {"ok": True}},
        },
    )

    benchmark = report["infinity_context_public_benchmark"]
    assert benchmark["status"] == "passed"
    assert benchmark["case_count"] == 1100
    assert benchmark["locomo_accuracy"] == 0.7283
    assert benchmark["weakest_capabilities"][0]["capability"] == "locomo_category_1"

    audit = report["infinity_context_production_audit"]
    assert audit["status"] == "blocked"
    assert audit["blocked_requirements"] == [{"area": "live_provider_proof"}]

    gap_ids = {item["id"] for item in report["current_gaps"]}
    assert gap_ids == {"current_live_provider_proof", "locomo_retrieval_reasoning"}


def test_comparison_module_does_not_import_competitor_runtime() -> None:
    module_path = (
        Path(__file__).parents[2]
        / "packages"
        / "infinity_context_server"
        / "infinity_context_server"
        / "memora_comparison.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])

    assert "memora" not in imported_roots
    assert "mcp" not in imported_roots


def test_memora_direct_smoke_script_writes_report_out(tmp_path, monkeypatch, capsys) -> None:
    script_path = Path(__file__).parents[2] / "scripts" / "memora_direct_mcp_smoke.py"
    spec = importlib.util.spec_from_file_location("memora_direct_mcp_smoke_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def fake_smoke() -> dict[str, object]:
        return {
            "system": "agentic-box/memora",
            "ok": True,
            "checks": {"has_core_tools": True},
        }

    report_path = tmp_path / "reports" / "memora.json"
    monkeypatch.setattr(module, "run_memora_direct_mcp_smoke", fake_smoke)

    exit_code = module.main(["--report-out", str(report_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert report_path.exists()
    assert json.loads(report_path.read_text(encoding="utf-8"))["ok"] is True
    written = json.loads(report_path.read_text(encoding="utf-8"))
    stdout = json.loads(captured.out)
    assert stdout["system"] == "agentic-box/memora"
    assert written["provenance"]["generated_by"] == "scripts/memora_direct_mcp_smoke.py"
    assert written["provenance"]["suite"] == "memora-direct-mcp-smoke"
    assert written["provenance"]["run_id"] == "unknown"
    assert stdout["provenance"] == written["provenance"]
