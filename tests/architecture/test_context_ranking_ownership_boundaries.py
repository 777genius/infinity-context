"""Bounded ranking owners cannot depend on their legacy compatibility facade."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "packages/infinity_context_core/infinity_context_core/application"
PREFIX = "infinity_context_core.application."
OWNERS = {
    "context_rank_dedupe",
    "context_rank_fusion",
    "context_bm25_ranking",
    "context_query_relevance_ranking",
    "context_keyword_ranking",
    "context_anchor_intent_ranking",
    "context_requirement_ranking",
    "context_requirement_signals",
    "context_rerank_relevance",
    "context_rerank_evidence_signals",
    "context_rerank_domain_heuristics",
    "context_deterministic_rerank_policy",
    "context_deterministic_rerank",
    "context_same_person_disambiguation",
}


def _dependencies(path):
    dependencies = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            dependencies.add(node.module)
        elif isinstance(node, ast.Import):
            dependencies.update(alias.name for alias in node.names)
    return dependencies


def test_ranking_owners_have_no_direct_or_transitive_facade_or_artifact_dependency():
    graph = {PREFIX + path.stem: _dependencies(path) for path in APP.glob("*.py")}
    forbidden = {PREFIX + "context_ranking", PREFIX + "context_artifact_evidence"}
    for owner in OWNERS:
        seen, pending = set(), [PREFIX + owner]
        while pending:
            module = pending.pop()
            assert module not in forbidden, (owner, module)
            if module in seen:
                continue
            seen.add(module)
            pending.extend(graph.get(module, ()))


def test_ranking_owner_graph_is_acyclic_and_uses_explicit_imports():
    graph = {
        name: {
            module.removeprefix(PREFIX)
            for module in _dependencies(APP / f"{name}.py")
            if module.removeprefix(PREFIX) in OWNERS
        }
        for name in OWNERS
    }

    def visit(name, path):
        assert name not in path, (*path, name)
        for dependency in graph[name]:
            visit(dependency, (*path, name))

    for name in OWNERS:
        visit(name, ())
        tree = ast.parse((APP / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                identifier = node.func.id if isinstance(node.func, ast.Name) else ""
                attribute = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert identifier not in {"__import__", "eval", "exec", "import_module"}, name
                assert attribute != "import_module", name


def test_facade_contains_only_thin_compatibility_adapters_and_batch_orchestration():
    tree = ast.parse((APP / "context_ranking.py").read_text())
    allowed = {"apply_deterministic_rerank_adjustments", "_provenance_flag_is_true"}
    for node in tree.body:
        assert not isinstance(node, ast.ClassDef)
        if not isinstance(node, ast.FunctionDef) or node.name in allowed:
            continue
        body = node.body[1:] if ast.get_docstring(node) else node.body
        assert len(body) == 1 and isinstance(body[0], ast.Return), node.name
        assert isinstance(body[0].value, ast.Call), node.name
    for owner in OWNERS | {"context_ranking"}:
        assert len((APP / f"{owner}.py").read_text().splitlines()) <= 1000
