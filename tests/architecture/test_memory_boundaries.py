"""Static architecture checks for Infinity Context package boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _python_files(package: str) -> list[Path]:
    return sorted((REPO_ROOT / package).rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
                imported.update(
                    f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
                )
            elif node.level:
                imported.update(alias.name for alias in node.names)
    return imported


def _assert_no_imports(package: str, forbidden_roots: set[str]) -> None:
    violations: list[str] = []
    for path in _python_files(package):
        for imported in sorted(_imports(path)):
            root = imported.split(".", 1)[0]
            if root in forbidden_roots:
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert not violations, "Forbidden architecture imports:\n" + "\n".join(violations)


def _assert_no_import_prefixes(package: str, forbidden_prefixes: set[str]) -> None:
    violations: list[str] = []
    for path in _python_files(package):
        for imported in sorted(_imports(path)):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            ):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert not violations, "Forbidden architecture imports:\n" + "\n".join(violations)


def _assert_file_no_imports(relative_path: str, forbidden_imports: set[str]) -> None:
    path = REPO_ROOT / relative_path
    violations = []
    for imported in sorted(_imports(path)):
        root = imported.split(".", 1)[0]
        if root in forbidden_imports or imported in forbidden_imports:
            violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")

    assert not violations, "Forbidden architecture imports:\n" + "\n".join(violations)


def test_memory_core_has_no_infrastructure_dependencies() -> None:
    _assert_no_imports(
        "packages/infinity_context_core/infinity_context_core",
        {
            "anthropic",
            "fastapi",
            "graphiti",
            "httpx",
            "infinity_context_adapters",
            "infinity_context_mcp",
            "infinity_context_server",
            "mcp",
            "openai",
            "qdrant_client",
            "sqlalchemy",
        },
    )


def test_memory_core_ports_do_not_depend_on_application_or_features() -> None:
    _assert_no_import_prefixes(
        "packages/infinity_context_core/infinity_context_core/ports",
        {
            "application",
            "features",
            "infinity_context_core.application",
            "infinity_context_core.features",
        },
    )


def test_import_parser_expands_from_import_members(tmp_path: Path) -> None:
    source = tmp_path / "forbidden_port_import.py"
    source.write_text("from infinity_context_core import features\n", encoding="utf-8")

    assert "infinity_context_core.features" in _imports(source)


def test_memory_adapters_do_not_depend_on_api_or_mcp_layers() -> None:
    _assert_no_imports(
        "packages/infinity_context_adapters/infinity_context_adapters",
        {
            "fastapi",
            "infinity_context_mcp",
            "infinity_context_server",
            "mcp",
        },
    )


def test_memory_mcp_does_not_depend_on_server_adapters_or_providers() -> None:
    _assert_no_imports(
        "packages/infinity_context_mcp/infinity_context_mcp",
        {
            "anthropic",
            "fastapi",
            "graphiti",
            "infinity_context_adapters",
            "infinity_context_server",
            "openai",
            "qdrant_client",
            "sqlalchemy",
        },
    )


def test_memory_server_does_not_depend_on_mcp_adapter_layer() -> None:
    _assert_no_imports(
        "packages/infinity_context_server/infinity_context_server",
        {
            "mcp",
            "infinity_context_mcp",
        },
    )


def test_top_evidence_policy_stays_lightweight() -> None:
    _assert_file_no_imports(
        "packages/infinity_context_server/infinity_context_server/top_evidence_policy.py",
        {
            "anthropic",
            "fastapi",
            "graphiti",
            "httpx",
            "infinity_context_adapters",
            "infinity_context_mcp",
            "infinity_context_server.eval",
            "infinity_context_server.main",
            "mcp",
            "openai",
            "qdrant_client",
            "sqlalchemy",
        },
    )


def test_memory_sdk_stays_transport_client_only() -> None:
    _assert_no_imports(
        "packages/infinity_context_sdk/infinity_context_sdk",
        {
            "anthropic",
            "fastapi",
            "graphiti",
            "infinity_context_adapters",
            "infinity_context_core",
            "infinity_context_mcp",
            "infinity_context_server",
            "mcp",
            "openai",
            "qdrant_client",
            "sqlalchemy",
        },
    )
