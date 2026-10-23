"""Keep evidence bundle policies independent from their composition facade."""

from __future__ import annotations

import ast
from pathlib import Path

SERVER = (
    Path(__file__).resolve().parents[2]
    / 'packages/infinity_context_benchmarks/infinity_context_benchmarks/evidence_bundle'
)
PREFIX = 'infinity_context_benchmarks.evidence_bundle.'
DEPENDENCIES = {
    'models': set(),
    'source_policy': {'models'},
    'candidate_policy': {'models', 'source_policy'},
    'role_support': {'models', 'source_policy', 'candidate_policy'},
    'ordering': {'models', 'source_policy', 'candidate_policy', 'role_support'},
    'role_repair': {'models', 'role_support', 'ordering'},
    'quality': {'models', 'source_policy', 'candidate_policy', 'role_support', 'ordering'},
}


def test_bundle_policies_have_no_facade_backedge_or_higher_policy_dependency() -> None:
    for policy, allowed in DEPENDENCIES.items():
        path = SERVER / f'{policy}.py'
        imported = _imports(path)
        assert 'infinity_context_server.memory_comparison_bundle_planner' not in imported, path.name
        actual = {
            module.removeprefix(PREFIX)
            for module in imported
            if module.startswith(PREFIX) and module.removeprefix(PREFIX) in DEPENDENCIES
        }
        assert actual <= allowed, (path.name, actual - allowed)


def test_bundle_policy_slice_remains_provider_free() -> None:
    forbidden = {'fastapi', 'sqlalchemy', 'httpx', 'openai', 'qdrant_client', 'graphiti'}
    for policy in DEPENDENCIES:
        path = SERVER / f'{policy}.py'
        assert not {module.split('.', 1)[0] for module in _imports(path)} & forbidden


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported
