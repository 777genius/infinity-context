"""Architecture checks for the provider-neutral evaluation-journal boundary."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JOURNAL = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "publishable_checkpoint_journal"
)
POLICY_FILES = ("primitives.py", "domain.py", "ports.py", "service.py", "crypto.py")
SQLITE_FILES = (
    "sqlite_adapter.py",
    "sqlite_store.py",
    "sqlite_transaction.py",
    "sqlite_rows.py",
)
FORBIDDEN_TRANSPORTS = {
    "fastapi",
    "graphiti",
    "httpx",
    "openai",
    "qdrant_client",
    "requests",
    "sqlalchemy",
}


def test_policy_boundary_has_no_provider_transport_or_sqlite_dependency() -> None:
    violations: list[str] = []
    for filename in POLICY_FILES:
        for imported in _imports(JOURNAL / filename):
            if imported.split(".", 1)[0] in FORBIDDEN_TRANSPORTS | {"sqlite3"}:
                violations.append(f"{filename}: imports {imported}")
    assert not violations, "Evaluation policy boundary violations:\n" + "\n".join(violations)


def test_package_facade_does_not_eagerly_import_sqlite_adapter() -> None:
    package_imports = _imports(JOURNAL / "__init__.py")
    assert not {
        imported
        for imported in package_imports
        if imported.startswith("infinity_context_server.publishable_checkpoint_journal.sqlite")
    }


def test_domain_and_service_import_without_loading_sqlite() -> None:
    package_root = REPO_ROOT / "packages" / "infinity_context_server"
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(package_root) if not existing else f"{package_root}{os.pathsep}{existing}"
    )
    script = """
import sys
import infinity_context_server.publishable_checkpoint_journal.domain
import infinity_context_server.publishable_checkpoint_journal.service
assert "sqlite3" not in sys.modules
assert not any(
    name.endswith(".sqlite_store")
    or name.endswith(".sqlite_adapter")
    or name.endswith(".sqlite_transaction")
    or name.endswith(".sqlite_rows")
    for name in sys.modules
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr


def test_sqlite_adapters_are_local_only_and_stream_in_bounded_batches() -> None:
    imports = set().union(*(_imports(JOURNAL / filename) for filename in SQLITE_FILES))
    sources = "\n".join(
        (JOURNAL / filename).read_text(encoding="utf-8") for filename in SQLITE_FILES
    )

    assert "sqlite3" in imports
    assert not {imported.split(".", 1)[0] for imported in imports} & FORBIDDEN_TRANSPORTS
    assert "BEGIN IMMEDIATE" in sources
    assert "PRAGMA synchronous = FULL" in sources
    assert "PRAGMA foreign_keys = ON" in sources
    assert "fetchmany(" in sources
    assert "fetchall(" not in sources


def test_evaluation_seal_is_exact_and_service_avoids_all_row_materialization() -> None:
    source = (JOURNAL / "service.py").read_text(encoding="utf-8")
    domain_source = "\n".join(
        (JOURNAL / filename).read_text(encoding="utf-8")
        for filename in ("primitives.py", "domain.py")
    )

    assert "def seal_evaluation(" in source
    assert "def seal(" not in source
    assert "tuple(transaction.iter_" not in source
    assert "CallStage.EXTRACTION" not in domain_source
    assert "PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT = 6160" in domain_source
    assert "PUBLISHABLE_EXTRACTION_CALL_COUNT = 5882" in domain_source


def test_new_journal_modules_stay_reviewable_and_do_not_enable_publishable_profile() -> None:
    for path in JOURNAL.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) < 1000, path
        assert "memory_comparison_publishable_profile" not in source


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported
