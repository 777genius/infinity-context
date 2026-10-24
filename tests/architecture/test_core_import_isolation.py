"""Fresh-interpreter dependency closures for demand-loaded compatibility exports."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / "packages/infinity_context_core"
CORE = "infinity_context_core"
TECHNICAL = {CORE, f"{CORE}.shared_kernel", f"{CORE}.shared_kernel.lazy_exports"}
APPLICATION = TECHNICAL | {f"{CORE}.application", f"{CORE}.application._compatibility_exports"}
FIXTURE = ROOT / "tests/fixtures/core_compatibility_exports/contracts.json"
CONTRACT = json.loads(FIXTURE.read_text())


def fresh(code):
    """Pin this checkout even when the frozen venv has another editable installation."""
    preamble = f"""
import importlib, json, pathlib, sys
sys.path.insert(0, {str(CORE_PATH)!r})
"""
    origin_check = f"""
for name, module in tuple(sys.modules.items()):
    if name == {CORE!r} or name.startswith({CORE + "."!r}):
        assert module.__file__, name
        assert pathlib.Path(module.__file__).resolve().is_relative_to(
            pathlib.Path({str(CORE_PATH)!r}).resolve()
        ), (name, module.__file__)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", preamble + code + origin_check],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("target", "exact", "allowed_roots"),
    [
        (CORE, TECHNICAL, ()),
        (f"{CORE}.application", APPLICATION, ()),
        (f"{CORE}.domain.entities", TECHNICAL, (f"{CORE}.domain",)),
        (f"{CORE}.ports", TECHNICAL, (f"{CORE}.domain", f"{CORE}.ports")),
        (
            f"{CORE}.features.agent_authorization.domain",
            TECHNICAL | {f"{CORE}.features", f"{CORE}.features.agent_authorization"},
            (f"{CORE}.features.agent_authorization.domain",),
        ),
        (
            f"{CORE}.application.dto",
            APPLICATION | {f"{CORE}.features"},
            (
                f"{CORE}.domain",
                f"{CORE}.ports",
                f"{CORE}.features.memory_facts",
                f"{CORE}.features.review_governance",
            ),
        ),
        (f"{CORE}.sensitive_text", TECHNICAL | {f"{CORE}.sensitive_text"}, ()),
        (
            f"{CORE}.application.safe_payload",
            APPLICATION
            | {
                f"{CORE}.application.safe_payload",
                f"{CORE}.application.sensitive_text",
                f"{CORE}.application.context_retrieval_performance",
                f"{CORE}.sensitive_text",
            },
            (),
        ),
    ],
)
def test_complete_fresh_import_closure(target, exact, allowed_roots):
    loaded = set(
        fresh(
            f"importlib.import_module({target!r})\n"
            f"print(json.dumps(sorted(n for n in sys.modules "
            f"if n == {CORE!r} or n.startswith({CORE + '.'!r}))))\n"
        )
    )
    if target == f"{CORE}.application.dto":
        # These existing DTO modules consume feature-owned public contracts. No
        # other legacy application module is permitted by this aggregate import.
        exact = exact | DTO_MODULES
    assert exact <= loaded
    unexpected = {
        name
        for name in loaded - exact
        if not any(name == root or name.startswith(root + ".") for root in allowed_roots)
    }
    assert not unexpected


def test_dir_is_lazy_and_first_export_access_caches_the_defining_object():
    assert fresh(
        """
import infinity_context_core as core
before = set(sys.modules)
assert set(core.__all__) <= set(dir(core))
assert not (set(core.__all__) & set(vars(core)))
assert set(sys.modules) == before
calls = []
original = core.resolve_lazy_export
def record(*args):
    calls.append(args[0])
    return original(*args)
core.resolve_lazy_export = record
first = core.SourceRef
assert core.SourceRef is first
assert first is importlib.import_module('infinity_context_core.domain.entities').SourceRef
assert calls == ['SourceRef']
print(json.dumps(True))
"""
    )


@pytest.mark.parametrize("package", CONTRACT["packages"])
def test_star_import_order_and_identity_in_fresh_process(package):
    expected = CONTRACT["packages"][package]["all"]
    assert fresh(
        f"""
module = importlib.import_module({package!r})
assert set(module.__all__) <= set(dir(module))
assert not (set(module.__all__) & set(vars(module)))
namespace = {{}}
exec('from {package} import *', namespace)
assert [n for n in namespace if n != '__builtins__'] == {expected!r}
assert all(namespace[n] is getattr(module, n) for n in module.__all__)
print(json.dumps(True))
"""
    )


def test_initializers_declare_static_types_without_runtime_business_imports():
    for package, record in CONTRACT["packages"].items():
        tree = ast.parse((ROOT / record["source_path"]).read_text())
        static_names = set()
        static_routes = {}
        allowed = {
            "__future__",
            "typing",
            f"{CORE}.shared_kernel.lazy_exports",
            f"{CORE}.application._compatibility_exports",
        }
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert isinstance(node, ast.ImportFrom) and node.module in allowed
            elif isinstance(node, ast.If):
                assert isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                assert not node.orelse
                for declaration in node.body:
                    if isinstance(declaration, (ast.Import, ast.ImportFrom)):
                        static_names.update(a.asname or a.name for a in declaration.names)
                        for alias in declaration.names:
                            static_routes[alias.asname or alias.name] = (
                                (declaration.module, alias.name)
                                if isinstance(declaration, ast.ImportFrom)
                                else (alias.name, None)
                            )
                    elif isinstance(declaration, ast.Assign):
                        static_names.update(
                            t.id for t in declaration.targets if isinstance(t, ast.Name)
                        )
                        value = declaration.value
                        if isinstance(value, ast.Name):
                            route = static_routes[value.id]
                        else:
                            assert isinstance(value, ast.Attribute)
                            assert isinstance(value.value, ast.Name)
                            route = (static_routes[value.value.id][0], value.attr)
                        for target in declaration.targets:
                            assert isinstance(target, ast.Name)
                            static_routes[target.id] = route
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node))
        assert set(record["all"]) <= static_names, package
        assert {name: list(static_routes[name]) for name in record["all"]} == {
            name: record["exports"][name]["route"] for name in record["all"]
        }
    helper = ast.parse((CORE_PATH / CORE / "shared_kernel/lazy_exports.py").read_text())
    assert {node.module for node in ast.walk(helper) if isinstance(node, ast.ImportFrom)} <= {
        "__future__",
        "collections.abc",
        "importlib",
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(helper))


DTO_MODULES = {
    f"{CORE}.application.{name}"
    for name in (
        "dto",
        "dto_anchors",
        "dto_assets",
        "dto_context",
        "dto_context_links",
        "dto_facts",
        "dto_suggestions_capture",
        "dto_workspace",
    )
}
