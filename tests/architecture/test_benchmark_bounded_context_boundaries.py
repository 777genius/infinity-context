"""Freeze benchmark debt and keep external-runtime details out of product layers."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = (
    REPO_ROOT / "packages" / "infinity_context_server" / "infinity_context_server"
)
CORE_ROOT = REPO_ROOT / "packages" / "infinity_context_core" / "infinity_context_core"
BRIDGE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_runtime_bridge"
    / "infinity_context_runtime_bridge"
)
SERVER_DEBT_MAX_FILES = 453
SERVER_DEBT_MAX_LINES = 203_124
CORE_DEBT_MAX_FILES = 21
CORE_DEBT_MAX_LINES = 7_205


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _line_count(paths: tuple[Path, ...]) -> int:
    return sum(len(path.read_bytes().splitlines()) for path in paths)


def _server_benchmark_debt() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in SERVER_ROOT.rglob("*.py")
            if any(
                part.startswith(("memory_comparison", "publishable_"))
                for part in path.relative_to(SERVER_ROOT).parts
            )
        )
    )


def _core_benchmark_debt() -> tuple[Path, ...]:
    markers = ("benchmark", "managed_cleanup", "managed_mem0", "memory_comparison")
    return tuple(
        sorted(
            path
            for path in CORE_ROOT.rglob("*.py")
            if any(marker in path.name for marker in markers)
        )
    )


def test_external_runtime_bridge_is_not_owned_by_product_server() -> None:
    assert BRIDGE_ROOT.is_dir()
    assert not (
        SERVER_ROOT / "features" / "subscription_runtime_bridge"
    ).exists()


def test_external_runtime_bridge_does_not_depend_on_product_layers() -> None:
    forbidden = (
        "infinity_context_adapters",
        "infinity_context_core",
        "infinity_context_server",
    )
    violations: list[str] = []
    for path in sorted(BRIDGE_ROOT.rglob("*.py")):
        for imported in sorted(_imports(path)):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {imported}")
    assert not violations, "runtime bridge depends inward on product layers:\n" + "\n".join(
        violations
    )


def test_core_does_not_depend_on_runtime_or_server_details() -> None:
    forbidden = ("infinity_context_runtime_bridge", "infinity_context_server")
    violations: list[str] = []
    for path in sorted(CORE_ROOT.rglob("*.py")):
        for imported in sorted(_imports(path)):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {imported}")
    assert not violations, "core depends on outer runtime details:\n" + "\n".join(violations)


def test_benchmark_debt_cannot_grow_inside_product_packages() -> None:
    server = _server_benchmark_debt()
    core = _core_benchmark_debt()
    assert len(server) <= SERVER_DEBT_MAX_FILES
    assert _line_count(server) <= SERVER_DEBT_MAX_LINES
    assert len(core) <= CORE_DEBT_MAX_FILES
    assert _line_count(core) <= CORE_DEBT_MAX_LINES
