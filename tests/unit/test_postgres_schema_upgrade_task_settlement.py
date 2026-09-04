"""Provider-free regression for concurrent schema-upgrade task settlement."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

_E2E_TESTS = Path(__file__).resolve().parents[1] / "e2e"
sys.path.insert(0, str(_E2E_TESTS))
schema_upgrade_e2e = importlib.import_module("test_postgres_schema_upgrade_e2e")
sys.path.pop(0)


def test_failed_upgrade_settles_sibling_before_caller_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    sibling_started = asyncio.Event()
    never_finishes = asyncio.Event()
    call_count = 0

    async def fake_upgrade_schema(_engine: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await sibling_started.wait()
            raise RuntimeError("primary upgrade failure")

        sibling_started.set()
        try:
            await never_finishes.wait()
        finally:
            events.append("sibling settled")

    async def exercise() -> None:
        monkeypatch.setattr(schema_upgrade_e2e, "upgrade_schema", fake_upgrade_schema)
        with pytest.raises(RuntimeError, match="primary upgrade failure"):
            await schema_upgrade_e2e._run_concurrent_schema_upgrades(object())
        events.append("caller cleanup")

    asyncio.run(exercise())

    assert events == ["sibling settled", "caller cleanup"]
