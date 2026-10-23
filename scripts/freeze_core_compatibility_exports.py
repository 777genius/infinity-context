"""Freeze complete compatibility exports before changing package initialization."""

from __future__ import annotations

import ast
import base64
import dataclasses
import hashlib
import importlib
import inspect
import json
import pickle
import subprocess
import types
from pathlib import Path
from typing import get_type_hints

ROOT = Path(__file__).resolve().parents[1]
BASE = "ab834d55a3e6123655a8db974559228ccc8b107b"
PACKAGES = ("infinity_context_core", "infinity_context_core.application")
OUTPUT = ROOT / "tests/fixtures/core_compatibility_exports/contracts.json"


def source_routes(source: str):
    routes = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                routes[alias.asname or alias.name] = (alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                routes[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            parent = node.value.value
            if isinstance(parent, ast.Name) and parent.id in routes:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        routes[target.id] = (routes[parent.id][0], node.value.attr)
    return routes


def evaluated_hints(value):
    try:
        return {"values": {name: str(hint) for name, hint in get_type_hints(value).items()}}
    except (NameError, TypeError) as error:
        return {"error_type": type(error).__name__, "error": str(error)}


def signature(value):
    try:
        return {"value": str(inspect.signature(value))}
    except (TypeError, ValueError) as error:
        return {"error_type": type(error).__name__, "error": str(error)}


def describe(value):
    if isinstance(value, types.ModuleType):
        return {"kind": "module", "module": value.__name__}
    if inspect.isclass(value) or inspect.isfunction(value):
        return {
            "kind": "class" if inspect.isclass(value) else "function",
            "module": value.__module__,
            "qualname": value.__qualname__,
            "signature": signature(value),
            "hints": evaluated_hints(value),
            "reference_pickle": base64.b64encode(pickle.dumps(value)).decode(),
        }
    return {"kind": "value", "type": type(value).__qualname__, "value": value}


def main():
    assert not OUTPUT.exists(), "Never replace before-source export evidence"
    records = {}
    for package in PACKAGES:
        path = "packages/infinity_context_core/" + package.replace(".", "/") + "/__init__.py"
        source = (ROOT / path).read_bytes()
        original = subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT)
        assert source == original, f"Initializer changed before capture: {path}"
        routes = source_routes(source.decode())
        module = importlib.import_module(package)
        names = list(module.__all__)
        missing = "__synthetic_missing_export__"
        try:
            getattr(module, missing)
        except AttributeError as error:
            absent = {"name": missing, "args": list(error.args)}
        else:
            raise AssertionError("Synthetic missing export unexpectedly exists")
        records[package] = {
            "source_path": path,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "all": names,
            "all_type": type(module.__all__).__name__,
            "missing": absent,
            "exports": {
                name: {"route": list(routes[name]), **describe(getattr(module, name))}
                for name in names
            },
        }
    core = importlib.import_module(PACKAGES[0])
    application = importlib.import_module(PACKAGES[1])
    source_ref = core.SourceRef(source_type="note", source_id="synthetic:core-exports")
    item = application.ContextItem(
        item_id="export-item",
        item_type="chunk",
        text="Evidence",
        score=0.7,
        source_refs=(source_ref,),
    )
    samples = {
        "source_ref": source_ref,
        "context_item": item,
        "validation_error": core.MemoryValidationError("Synthetic contract error"),
    }
    instances = {}
    for name, instance in samples.items():
        instances[name] = {
            "pickle": base64.b64encode(pickle.dumps(instance)).decode(),
            "module": type(instance).__module__,
            "qualname": type(instance).__qualname__,
            "fields": json.loads(json.dumps(dataclasses.asdict(instance)))
            if dataclasses.is_dataclass(instance)
            else None,
            "args": list(instance.args) if isinstance(instance, Exception) else None,
        }
    payload = {
        "base_sha": BASE,
        "packages": records,
        "instances": instances,
        "procedure": "Worktree packages and repository root on PYTHONPATH; run this script",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        {
            "exports": {name: len(record["all"]) for name, record in records.items()},
            "fixture_bytes": OUTPUT.stat().st_size,
        }
    )


if __name__ == "__main__":
    main()
