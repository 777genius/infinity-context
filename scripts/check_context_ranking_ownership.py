"""Audit single policy ownership against the immutable pre-refactor source blob.

This is development evidence, not a runtime import mechanism. Callback parameter
plumbing is normalized for body comparison; original functions and constants are
otherwise compared with the exact source SHA frozen before implementation.
"""

from __future__ import annotations

import ast
import copy
import dis
import hashlib
import importlib
import inspect
import json
import subprocess
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "infinity_context_core.application."
FACADE = PREFIX + "context_ranking"
BASE = "b0b87bd774f93c2bca9bec14c0efc072a2ba2de8"
OWNER_NAMES = (
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
)


def canonical(value):
    """Follow only explicit one-return facade adapters for this source audit."""
    value = inspect.unwrap(value)
    if inspect.isfunction(value) and value.__module__ == FACADE:
        tree = ast.parse(inspect.getsource(value))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        body = node.body[1:] if ast.get_docstring(node) else node.body
        if len(body) == 1 and isinstance(body[0], ast.Return):
            call = body[0].value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                target = value.__globals__.get(call.func.id)
                if inspect.isfunction(target) and target.__module__ != FACADE:
                    return target
    return value


class CallbackPlumbing(ast.NodeTransformer):
    RENAMES = {
        "query_terms_fn": "query_terms",
        "query_term_frequency_fn": "query_term_frequency",
        "query_expansion_terms_fn": "_query_expansion_terms",
        "text_variant_profile_fn": "text_variant_profile",
        "best_query_relevance_fn": "best_query_relevance",
        "normalize_context_diagnostics_fn": "normalize_context_diagnostics",
        "RequirementCoverageSignals": "_RequirementCoverageSignals",
    }

    def visit_Name(self, node):
        node.id = self.RENAMES.get(node.id, node.id)
        return node

    def visit_Call(self, node):
        node.keywords = [
            keyword
            for keyword in node.keywords
            if keyword.arg not in self.RENAMES and keyword.arg != "normalized"
        ]
        return self.generic_visit(node)

    def visit_Assign(self, node):
        # The standalone BM25 API supplies its owning default; the facade injects
        # the same original cached expansion adapter explicitly.
        if any(
            isinstance(target, ast.Name) and target.id == "query_expansion_terms_fn"
            for target in node.targets
        ):
            return None
        return self.generic_visit(node)


def normalized_body(node):
    body = copy.deepcopy(node.body)
    normalizer = CallbackPlumbing()
    module = ast.Module(body=body, type_ignores=[])
    return ast.dump(normalizer.visit(module), include_attributes=False)


def loaded_globals(code):
    names = {
        instruction.argval
        for instruction in dis.get_instructions(code)
        if instruction.opname == "LOAD_GLOBAL"
    }
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names.update(loaded_globals(constant))
    return names


def check():
    relative = "packages/infinity_context_core/infinity_context_core/application/context_ranking.py"
    source = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=ROOT)
    contract = json.loads(
        (ROOT / "tests/fixtures/context_policy_refactor/wave2_ranking/contracts.json").read_text()
    )
    assert hashlib.sha256(source).hexdigest() == contract["source_sha256"][relative]
    original = ast.parse(source)
    facade = importlib.import_module(FACADE)
    modules = [importlib.import_module(PREFIX + name) for name in OWNER_NAMES]
    originals = {
        node.name: node
        for node in original.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    # All old callable references still resolve; compare the actual owning body.
    count = 0
    for name, node in originals.items():
        current = canonical(getattr(facade, name))
        current_tree = ast.parse(inspect.getsource(current))
        current_node = next(
            n for n in current_tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        )
        assert normalized_body(current_node) == normalized_body(node), f"algorithm body: {name}"
        count += 1
    # Original module globals still refer to canonical definitions/import objects.
    # Explicit callback names are parameters, and existing behavior tests prove
    # their late-bound facade values reach every exercised path.
    binding_count = 0
    for name, definition in contract["definitions"].items():
        current = canonical(getattr(facade, name))
        if not inspect.isfunction(current):
            continue
        actual_names = loaded_globals(current.__code__)
        for global_name, (module_name, qualname) in definition["globals"].items():
            if global_name not in actual_names:
                continue  # dependency is now an explicit argument or in a comprehension
            actual = current.__globals__[global_name]
            if module_name == FACADE:
                expected = canonical(getattr(facade, qualname))
                if global_name == "_provenance_flag_is_true":
                    expected = facade.provenance_flag_is_true
                elif global_name == "_query_expansion_terms" and current.__module__.endswith(
                    "context_bm25_ranking"
                ):
                    expected = importlib.import_module(
                        PREFIX + "context_bm25_ranking"
                    )._query_expansion_terms
            else:
                expected = importlib.import_module(module_name)
                for part in qualname.split("."):
                    expected = getattr(expected, part)
            assert canonical(actual) is expected, f"global binding: {name}.{global_name}"
            binding_count += 1
    for module in modules:
        assert len(Path(module.__file__).read_text().splitlines()) <= 1000
    print(f"Verified {count} original callable bodies and {binding_count} actual global bindings")


if __name__ == "__main__":
    check()
