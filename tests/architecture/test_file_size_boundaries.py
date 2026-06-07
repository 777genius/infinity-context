"""File size boundaries for maintainable Clean Architecture modules."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CODE_GLOBS = ("*.py", "*.js", "*.ts", "*.tsx", "*.rs")
CODE_ROOTS = ("packages", "scripts", "tests")
IGNORED_PATH_PARTS = {
    "__pycache__",
    "node_modules",
}

MAX_LINES = 2500
IDEAL_LINES = 1000

LEGACY_OVER_MAX_ALLOWLIST = {
    "packages/memo_stack_server/memo_stack_server/eval.py",
    "tests/unit/test_legacy_and_context_api.py",
}

IDEAL_OVER_1000_DEBT_ALLOWLIST = {
    *LEGACY_OVER_MAX_ALLOWLIST,
    "packages/memo_stack_mcp/memo_stack_mcp/agent_behavior_bench.py",
    "scripts/clean_full_smoke.py",
    "packages/memo_stack_adapters/memo_stack_adapters/postgres/repositories.py",
    "packages/memo_stack_mcp/memo_stack_mcp/application/service.py",
    "packages/memo_stack_mcp/memo_stack_mcp/plugin_hook.py",
    "packages/memo_stack_mcp/memo_stack_mcp/server.py",
    "packages/memo_stack_server/memo_stack_server/admin.py",
    "packages/memo_stack_server/memo_stack_server/public_benchmark.py",
    "packages/memo_stack_server/memo_stack_server/web/assets/memory-browser.js",
    "tests/e2e/test_memory_scale_chaos_load_e2e.py",
    "tests/unit/test_admin_tokens.py",
    "tests/unit/test_agent_behavior_bench.py",
    "tests/unit/test_capture_worker.py",
    "tests/unit/test_local_runbook.py",
    "tests/unit/test_mcp_adapter.py",
    "tests/unit/test_provider_adapters.py",
    "tests/unit/test_quality_evidence_bundle.py",
    "tests/unit/test_worker_eval.py",
    "tests/unit/test_worker_eval_scorecard.py",
}


def test_no_new_file_exceeds_hard_2500_line_ceiling() -> None:
    offenders = [
        f"{relative_path}: {line_count} lines"
        for relative_path, line_count in _code_file_line_counts()
        if line_count > MAX_LINES and relative_path not in LEGACY_OVER_MAX_ALLOWLIST
    ]

    assert offenders == []


def test_files_over_ideal_1000_line_target_are_explicit_debt() -> None:
    offenders = [
        f"{relative_path}: {line_count} lines"
        for relative_path, line_count in _code_file_line_counts()
        if line_count > IDEAL_LINES and relative_path not in IDEAL_OVER_1000_DEBT_ALLOWLIST
    ]

    assert offenders == []


def _code_file_line_counts() -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for root_name in CODE_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for glob in CODE_GLOBS:
            for path in root.rglob(glob):
                if IGNORED_PATH_PARTS.intersection(path.parts):
                    continue
                relative_path = path.relative_to(REPO_ROOT).as_posix()
                results.append((relative_path, _line_count(path)))
    return sorted(results)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())
