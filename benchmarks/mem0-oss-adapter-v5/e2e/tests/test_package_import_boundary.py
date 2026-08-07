from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_readiness_import_does_not_preload_scenario_or_fake_runtime() -> None:
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import e2e.readiness
assert "e2e.scenario" not in sys.modules
assert "e2e.fake_runtime" not in sys.modules
"""
    completed = _run_isolated(script)

    assert completed.returncode == 0, completed.stderr


def test_readiness_module_execution_does_not_preload_heavy_scenario() -> None:
    script = f"""
import runpy
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.argv = ["e2e.readiness", "--once"]
try:
    runpy.run_module("e2e.readiness", run_name="__main__", alter_sys=True)
except SystemExit as error:
    assert error.code in (None, 0, 1)
assert "e2e.scenario" not in sys.modules
assert "e2e.fake_runtime" not in sys.modules
"""
    completed = _run_isolated(script)

    assert completed.returncode == 0, completed.stderr
    assert "RuntimeWarning" not in completed.stderr


def test_fake_runtime_module_execution_has_no_preload_warning() -> None:
    script = f"""
import runpy
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.argv = ["e2e.fake_runtime", "--help"]
try:
    runpy.run_module("e2e.fake_runtime", run_name="__main__", alter_sys=True)
except SystemExit as error:
    assert error.code in (None, 0)
"""
    completed = _run_isolated(script)

    assert completed.returncode == 0, completed.stderr
    assert "RuntimeWarning" not in completed.stderr


def test_public_exports_are_lazy_cached_and_preserve_import_star() -> None:
    import e2e as package
    from e2e.contracts import RunFixture, SyntheticUnit
    from e2e.scenario import E2EResult, ProviderFreeE2EScenario

    implementations = {
        "E2EResult": E2EResult,
        "ProviderFreeE2EScenario": ProviderFreeE2EScenario,
        "RunFixture": RunFixture,
        "SyntheticUnit": SyntheticUnit,
    }
    for name in implementations:
        package.__dict__.pop(name, None)

    namespace: dict[str, object] = {}
    exec("from e2e import *", namespace)

    for name, implementation in implementations.items():
        assert namespace[name] is implementation
        assert getattr(package, name) is implementation
        assert package.__dict__[name] is implementation


def test_unknown_package_attribute_is_rejected_exactly() -> None:
    import e2e as package

    name = "missing_public_export"
    expected = f"module {package.__name__!r} has no attribute {name!r}"
    with pytest.raises(AttributeError, match=f"^{re.escape(expected)}$"):
        getattr(package, name)
