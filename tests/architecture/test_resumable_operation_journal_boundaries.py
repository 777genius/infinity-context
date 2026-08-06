"""Architecture constraints for the provider-neutral schema-v4 journal."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "resumable_operation_journal"
)
FORBIDDEN = {"fastapi", "graphiti", "httpx", "openai", "qdrant_client", "requests"}


def test_generic_policy_has_no_provider_sqlite_or_benchmark_dependency() -> None:
    violations: list[str] = []
    for filename in ("domain.py", "ports.py", "service.py", "replay.py", "crypto.py"):
        for imported in _imports(JOURNAL / filename):
            root = imported.split(".", 1)[0]
            if root in FORBIDDEN | {"sqlite3"} or "publishable_checkpoint" in imported:
                violations.append(f"{filename}: {imported}")
    assert not violations


def test_public_facade_is_lazy_about_sqlite_and_files_are_reviewable() -> None:
    assert not {name for name in _imports(JOURNAL / "__init__.py") if name.endswith(".sqlite")}
    assert all(len(path.read_text().splitlines()) < 1000 for path in JOURNAL.glob("*.py"))


def test_sqlite_is_strict_v4_and_materializes_manifest_in_one_batch() -> None:
    source = (JOURNAL / "sqlite.py").read_text()
    assert 'OPERATION_JOURNAL_SCHEMA_VERSION = "4"' in (JOURNAL / "domain.py").read_text()
    assert "executemany(" in source
    assert "BEGIN IMMEDIATE" in source
    assert "PRAGMA synchronous = FULL" in source
    assert "PRAGMA foreign_keys = ON" in source
    assert "fetchmany(" in source
    assert "fetchall(" not in source
    assert "events = tuple(" in source
    assert "cursor.close()" in source
    assert "return iter(events)" in source


def test_full_replay_is_confined_to_safe_control_plane_methods() -> None:
    tree = ast.parse((JOURNAL / "service.py").read_text())
    callers = {
        method.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for method in node.body
        if isinstance(method, ast.FunctionDef)
        for child in ast.walk(method)
        if isinstance(child, ast.Attribute) and child.attr == "_verify_replay"
    }
    assert callers == {"initialize", "resume", "seal", "snapshot"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported
