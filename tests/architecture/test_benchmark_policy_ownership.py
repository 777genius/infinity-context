"""Standalone benchmark policies own their definitions and have an acyclic import graph."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "infinity_context_benchmarks.retrieval_intent"
POLICY = ROOT / "packages/infinity_context_benchmarks/infinity_context_benchmarks/retrieval_intent"
MANIFEST = ROOT / "tests/fixtures/benchmark_retrieval_intent/ownership.json"


def test_intent_imports_only_stdlib_and_its_own_acyclic_capsule():
    graph = {}
    for path in POLICY.glob("*.py"):
        module = PREFIX if path.stem == "__init__" else PREFIX + "." + path.stem
        tree = ast.parse(path.read_text())
        graph[module] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, path
                imports = [node.module]
            else:
                imports = []
            for imported in imports:
                if imported.startswith(PREFIX + "."):
                    graph[module].add(imported)
                else:
                    assert imported in {"__future__", "re", "collections.abc", "dataclasses"}, (
                        path,
                        imported,
                    )
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert name not in {"__import__", "eval", "exec", "import_module"}, path
                assert attr != "import_module", path
            assert not (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "sys"
                and node.attr == "modules"
            ), path

    def visit(module, ancestors):
        assert module not in ancestors, (module, ancestors)
        for dependency in graph[module]:
            visit(dependency, (*ancestors, module))

    for module in graph:
        visit(module, ())


def test_every_original_definition_has_exactly_one_declared_canonical_owner():
    owners = json.loads(MANIFEST.read_text())["owners"]
    definitions = {}
    for path in POLICY.glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                definitions.setdefault(node.name, []).append(PREFIX + "." + path.stem)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        definitions.setdefault(target.id, []).append(PREFIX + "." + path.stem)
    for name, owner in owners.items():
        assert definitions[name] == [owner], (name, definitions[name], owner)
    facade = ROOT / (
        "packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py"
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.ClassDef))
        for node in ast.parse(facade.read_text()).body
    )


def test_complete_score_capsule_is_standalone_acyclic_and_owns_original_definitions():
    prefix = "infinity_context_benchmarks.rerank_policy"
    root = POLICY.parent / "rerank_policy"
    manifest = json.loads(
        (ROOT / "tests/fixtures/benchmark_rerank_policy/ownership.json").read_text()
    )
    graph, definitions = {}, {}
    for path in root.glob("*.py"):
        module = prefix if path.stem == "__init__" else prefix + "." + path.stem
        tree = ast.parse(path.read_text())
        graph[module] = set()
        definitions[module] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0
                imports = [node.module]
            else:
                imports = []
            for imported in imports:
                if imported.startswith(prefix + "."):
                    graph[module].add(imported)
                else:
                    assert imported in {"__future__", "collections.abc", "dataclasses", "typing"}
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert name not in {"__import__", "exec", "eval", "import_module"}
                assert attr != "import_module"
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                definitions[module][node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        definitions[module][target.id] = node

    def visit(module, ancestors):
        assert module not in ancestors, (module, ancestors)
        for dependency in graph[module]:
            visit(dependency, (*ancestors, module))

    for module in graph:
        visit(module, ())
    for qualified, owner in manifest["owners"].items():
        name = qualified.rsplit(".", 1)[-1]
        assert name in definitions[owner]
    for filename in ("memory_comparison_rerank_policy.py", "memory_comparison_rerank_policies.py"):
        facade = ROOT / "packages/infinity_context_server/infinity_context_server" / filename
        assert not any(
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            for node in ast.parse(facade.read_text()).body
        )
