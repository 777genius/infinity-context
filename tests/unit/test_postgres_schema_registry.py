"""Import-order proofs for the explicit SQLAlchemy schema registry."""

from __future__ import annotations

import subprocess
import sys

_FIRST_MODULES = (
    "infinity_context_adapters.postgres.feature_models",
    "infinity_context_adapters.postgres.outbox_models",
    "infinity_context_adapters.postgres.temporal_models",
)


def test_schema_registry_is_complete_after_any_supported_first_import() -> None:
    processes = [
        (first_module, _start_registry_probe(first_module)) for first_module in _FIRST_MODULES
    ]
    try:
        for first_module, process in processes:
            stdout, stderr = process.communicate(timeout=300)
            assert process.returncode == 0, f"{first_module}: {stderr or stdout}"
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def _start_registry_probe(first_module: str) -> subprocess.Popen[str]:
    script = f"""
from importlib import import_module
from sqlalchemy import create_engine

import_module({first_module!r})
from infinity_context_adapters.postgres.schema_registry import load_schema_metadata

metadata = load_schema_metadata()
engine = create_engine("sqlite://")
metadata.create_all(engine)
assert {{
    "memory_facts",
    "memory_fact_temporal_decisions",
    "suggestion_resolution_receipts",
    "memory_outbox",
    "memory_comparison_strict_v4_preparations",
}} <= set(metadata.tables)
"""
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
