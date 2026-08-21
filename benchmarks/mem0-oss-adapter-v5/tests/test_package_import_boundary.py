from __future__ import annotations

import importlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]


def test_pytest_imports_exact_infinity_context_source_packages() -> None:
    pytest_config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]
    assert pytest_config["ini_options"]["pythonpath"] == [
        ".",
        "deployment",
        "../../packages/infinity_context_core",
        "../../packages/infinity_context_server",
        "../../packages/infinity_context_runtime_bridge",
        "../../packages/infinity_context_adapters",
    ]

    for package_name, package_root in (
        ("infinity_context_core", "infinity_context_core"),
        ("infinity_context_server", "infinity_context_server"),
        ("infinity_context_adapters", "infinity_context_adapters"),
        ("infinity_context_runtime_bridge", "infinity_context_runtime_bridge"),
    ):
        package = importlib.import_module(package_name)
        assert Path(package.__file__).resolve() == (
            REPOSITORY_ROOT / "packages" / package_root / package_name / "__init__.py"
        ).resolve()


def test_source_authority_import_needs_only_the_standard_library() -> None:
    script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from mem0_oss_adapter_v5.source_authority import verify_source_authority
assert callable(verify_source_authority)
assert "site" not in sys.modules
assert "fastapi" not in sys.modules
assert "mem0_oss_adapter_v5.app" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_public_create_app_is_lazy_and_cached() -> None:
    import mem0_oss_adapter_v5 as package
    from mem0_oss_adapter_v5.app import create_app as implementation

    package.__dict__.pop("create_app", None)

    from mem0_oss_adapter_v5 import create_app

    assert create_app is implementation
    assert package.create_app is implementation
    assert package.__dict__["create_app"] is implementation


def test_unknown_package_attribute_is_rejected_exactly() -> None:
    import mem0_oss_adapter_v5 as package

    name = "missing_public_export"
    expected = f"module {package.__name__!r} has no attribute {name!r}"
    with pytest.raises(AttributeError, match=f"^{re.escape(expected)}$"):
        getattr(package, name)
