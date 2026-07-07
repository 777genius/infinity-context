from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_quality_risk_helpers_import_without_benchmark_model_dependencies() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join(
        (
            str(repo_root / "packages" / "infinity_context_server"),
            str(repo_root / "packages" / "infinity_context_core"),
            str(repo_root),
            os.environ.get("PYTHONPATH", ""),
        )
    )
    code = "\n".join(
        (
            "import sys",
            "import infinity_context_server.memory_comparison_candidate_risks",
            "import infinity_context_server.memory_comparison_answer_context_risks",
            "assert 'infinity_context_server.memory_comparison_models' not in sys.modules",
            "assert 'infinity_context_server.public_benchmark_models' not in sys.modules",
        )
    )

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
    )


def test_top_evidence_preflight_imports_without_http_client_dependencies() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join(
        (
            str(repo_root / "packages" / "infinity_context_server"),
            str(repo_root / "packages" / "infinity_context_core"),
            str(repo_root),
            os.environ.get("PYTHONPATH", ""),
        )
    )
    code = "\n".join(
        (
            "import sys",
            "import infinity_context_server.top_evidence_preflight",
            "assert 'httpx' not in sys.modules",
        )
    )

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
    )

def test_top_evidence_preflight_import_does_not_require_httpx() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join(
        (
            str(repo_root / "packages" / "infinity_context_server"),
            str(repo_root / "packages" / "infinity_context_core"),
            str(repo_root),
            os.environ.get("PYTHONPATH", ""),
        )
    )
    script = """
import builtins

original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "httpx" or name.startswith("httpx."):
        raise ModuleNotFoundError("No module named httpx")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
try:
    import infinity_context_server.top_evidence_preflight as module
finally:
    builtins.__import__ = original_import

assert module.TOP_EVIDENCE_PREFLIGHT_SCHEMA_VERSION == "top-evidence-preflight.v1"
"""

    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
    )
