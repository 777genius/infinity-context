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


def test_full_recovery_is_confined_to_safe_control_plane_methods() -> None:
    tree = ast.parse((JOURNAL / "service.py").read_text())
    callers = {
        method.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for method in node.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        for child in ast.walk(method)
        if isinstance(child, ast.Attribute) and child.attr == "_recover_transaction"
    }
    assert callers == {
        "initialize",
        "prove_pristine",
        "recover",
        "seal_with_checkpoint",
        "snapshot",
    }


def test_hot_transitions_use_checkpoint_and_never_scan_full_projections() -> None:
    tree = ast.parse((JOURNAL / "service.py").read_text())
    forbidden = {
        "iter_events",
        "iter_manifest",
        "iter_operations",
        "iter_verified_receipts",
        "phase_counts",
        "receipts_commitment",
        "state_commitment",
    }
    hot = {
        "commit_with_checkpoint",
        "current_checkpoint",
        "prepare_dispatch",
        "quarantine_dispatched",
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for method in node.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if method.name not in hot:
                continue
            calls = {child.attr for child in ast.walk(method) if isinstance(child, ast.Attribute)}
            for name in sorted(calls & forbidden):
                violations.append(f"{method.name}: {name}")
    assert not violations


def test_sqlite_phase_facts_have_no_growing_count_or_group_scan() -> None:
    source = (JOURNAL / "sqlite.py").read_text()
    schema = (JOURNAL / "sqlite_schema.py").read_text()
    assert "GROUP BY phase" not in source
    assert "SELECT COUNT(*) FROM operation_receipts" not in source
    assert "batch_size <= 512" in source
    assert "operation_checkpoints" in schema
    assert "operation_commitment_nodes" in schema


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            if node.module:
                imported.add(f"{prefix}{node.module}")
            else:
                imported.update(f"{prefix}{alias.name}" for alias in node.names)
    return imported


def test_relative_import_normalizer_preserves_levels_and_moduleless_aliases(
    tmp_path: Path,
) -> None:
    module = tmp_path / "facade.py"
    module.write_text(
        "from . import sqlite as backend\n"
        "from .. import adapters\n"
        "from .domain import OperationEvent\n"
    )

    assert _imports(module) == {".sqlite", "..adapters", ".domain"}
