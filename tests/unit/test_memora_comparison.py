import ast
import importlib.util
import json
from pathlib import Path

from memo_stack_server.memora_comparison import (
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
        "checks": {check_id: True for check_id in DIRECT_MEMORA_SMOKE_REQUIREMENTS},
        "ok": True,
    }


def test_comparison_prefers_memo_stack_for_governed_agent_memory() -> None:
    report = build_memora_agent_memory_comparison(memora_direct_smoke=_passing_memora_smoke())

    assert report["overall"]["winner"] == "memo_stack"
    assert report["overall"]["memo_stack_score"] > report["overall"]["memora_score"]
    assert report["recommendations"][1]["winner"] == "memo_stack"


def test_comparison_credits_memora_direct_smoke_strengths() -> None:
    report = build_memora_agent_memory_comparison(memora_direct_smoke=_passing_memora_smoke())

    smoke = report["direct_memora_smoke"]
    assert smoke["status"] == "passed"
    assert smoke["tool_count"] == 42
    assert smoke["scenario_count"] == 7
    assert smoke["failed_checks"] == []

    by_id = {item["id"]: item for item in report["dimensions"]}
    assert by_id["retrieval_and_digest_quality"]["winner"] == "memo_stack"
    assert by_id["large_docs_and_architecture_notes"]["winner"] == "memo_stack"
    assert by_id["large_docs_and_architecture_notes"]["memo_stack_score"] >= 9.4
    assert by_id["graph_relationships"]["memo_stack_score"] > by_id["graph_relationships"][
        "memora_score"
    ]


def test_comparison_does_not_overclaim_when_memora_was_not_run() -> None:
    report = build_memora_agent_memory_comparison()

    assert report["direct_memora_smoke"]["status"] == "not_run"
    assert report["evidence_policy"]["competitor_paid_openai_llm_mode_verified"] is False
    assert (
        "Do not claim Memora failed production OpenAI mode."
        in report["evidence_policy"]["do_not_claim"]
    )


def test_comparison_module_does_not_import_competitor_runtime() -> None:
    module_path = (
        Path(__file__).parents[2]
        / "packages"
        / "memo_stack_server"
        / "memo_stack_server"
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
    assert json.loads(captured.out)["system"] == "agentic-box/memora"
