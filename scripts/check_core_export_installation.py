"""Verify frozen core compatibility APIs using only an explicit wheel installation."""

from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import importlib
import json
import pickle
import runpy
import sys
from pathlib import Path
from types import ModuleType


def _origins(target: Path) -> dict[str, str]:
    origins = {
        name: str(Path(module.__file__).resolve())
        for name, module in sys.modules.items()
        if name.startswith("infinity_context_") and getattr(module, "__file__", None)
    }
    assert origins and all(Path(path).is_relative_to(target) for path in origins.values())
    return origins


def _resolver_contract() -> None:
    from infinity_context_core.shared_kernel import lazy_exports

    original = lazy_exports.import_module
    error = ModuleNotFoundError("Synthetic missing dependency", name="synthetic_dependency")
    namespace = {}
    routes = {"Export": ("synthetic_owner", "Export")}

    def failed(_name):
        raise error

    try:
        lazy_exports.import_module = failed
        try:
            lazy_exports.resolve_lazy_export("Export", routes, namespace, "synthetic_package")
        except ModuleNotFoundError as caught:
            assert caught is error
        else:
            raise AssertionError("Real import error was swallowed")
        assert namespace == {}
        expected = object()
        owner = ModuleType("synthetic_owner")
        owner.Export = expected
        lazy_exports.import_module = lambda _name: owner
        assert (
            lazy_exports.resolve_lazy_export("Export", routes, namespace, "synthetic_package")
            is expected
        )
        assert namespace == {"Export": expected}
        module_namespace = {}
        assert (
            lazy_exports.resolve_lazy_export(
                "module_export",
                {"module_export": ("synthetic_owner", None)},
                module_namespace,
                "synthetic_package",
            )
            is owner
        )
        assert module_namespace == {"module_export": owner}
    finally:
        lazy_exports.import_module = original


def _verify(target: Path, fixture: Path) -> dict:
    assert sys.flags.isolated and sys.flags.no_site, "Invoke with python -I -S"
    assert not any(name.startswith("infinity_context_") for name in sys.modules)
    sys.path.insert(0, str(target))
    contract = json.loads(fixture.read_text())
    # Reuse the original stdlib-only inventory description, without importing any
    # source package or executing its before-source capture entrypoint.
    describe = runpy.run_path(
        str(Path(__file__).with_name("freeze_core_compatibility_exports.py"))
    )["describe"]
    modules = {}
    technical = {
        "infinity_context_core",
        "infinity_context_core.shared_kernel",
        "infinity_context_core.shared_kernel.lazy_exports",
    }
    for package, record in contract["packages"].items():
        module = importlib.import_module(package)
        modules[package] = module
        assert not any(name in vars(module) for name in record["all"])
        before = _origins(target)
        assert set(record["all"]) <= set(dir(module))
        assert _origins(target) == before, "dir() materialized lazy exports"
        expected_closure = technical | (
            {package, package + "._compatibility_exports"}
            if package.endswith(".application")
            else set()
        )
        assert set(before) == expected_closure
        assert type(module.__all__).__name__ == record["all_type"] == "list"
        assert module.__all__ == record["all"]
        missing = record["missing"]
        try:
            getattr(module, missing["name"])
        except AttributeError as caught:
            assert list(caught.args) == missing["args"]
        else:
            raise AssertionError("Unknown export did not raise AttributeError")

    from infinity_context_core.shared_kernel import lazy_exports

    root = modules["infinity_context_core"]
    calls = []
    original = lazy_exports.import_module

    def counted(name):
        calls.append(name)
        return original(name)

    try:
        lazy_exports.import_module = counted
        first = root.SourceRef
        assert root.SourceRef is first is root.__dict__["SourceRef"]
        assert calls == [contract["packages"][root.__name__]["exports"]["SourceRef"]["route"][0]]
    finally:
        lazy_exports.import_module = original

    for package, record in contract["packages"].items():
        module = modules[package]
        for name, expected in record["exports"].items():
            value = getattr(module, name)
            route_module, attribute = expected["route"]
            owner = importlib.import_module(route_module)
            assert value is (getattr(owner, attribute) if attribute else owner)
            assert module.__dict__[name] is value is getattr(module, name)
            assert describe(value) == {
                key: item for key, item in expected.items() if key != "route"
            }, (package, name)
            if "reference_pickle" in expected:
                assert pickle.loads(base64.b64decode(expected["reference_pickle"])) is value
                assert pickle.loads(pickle.dumps(value)) is value
        imported = {}
        exec(f"from {package} import " + ", ".join(record["all"]), imported)
        starred = {}
        exec(f"from {package} import *", starred)
        assert [name for name in starred if name != "__builtins__"] == record["all"]
        for name in record["all"]:
            assert imported[name] is starred[name] is getattr(module, name)
    application = modules["infinity_context_core.application"]
    for name in set(root.__all__) & set(application.__all__):
        assert getattr(root, name) is getattr(application, name)
    for sample in contract["instances"].values():
        value = pickle.loads(base64.b64decode(sample["pickle"]))
        cls = getattr(importlib.import_module(sample["module"]), sample["qualname"])
        assert type(value) is cls
        restored = pickle.loads(pickle.dumps(value))
        assert type(restored) is cls
        if dataclasses.is_dataclass(value):
            assert json.loads(json.dumps(dataclasses.asdict(value))) == sample["fields"]
            assert restored == value
        else:
            assert list(value.args) == list(restored.args) == sample["args"]
    _resolver_contract()
    origins = _origins(target)
    return {
        "ok": True,
        "target": str(target),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "exports": {
            package: len(record["all"]) for package, record in contract["packages"].items()
        },
        "instance_pickles": len(contract["instances"]),
        "origins": origins,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "tests/fixtures/core_compatibility_exports/contracts.json"
        ),
    )
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    report = _verify(arguments.target.resolve(strict=True), arguments.fixtures.resolve(strict=True))
    arguments.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "origins"}
            | {"module_count": len(report["origins"])}
        )
    )


if __name__ == "__main__":
    main()
