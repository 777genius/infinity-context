from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
