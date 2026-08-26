from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_server import worker as worker_module


def test_production_worker_registers_before_work_and_retires_afterward(monkeypatch) -> None:
    events: list[str] = []
    container = _Container(events)

    class Worker:
        def __init__(self, built_container, *, worker_filter):
            assert built_container is container
            del worker_filter

        async def run_once(self, *, limit, concurrency):
            events.append(f"run:{limit}:{concurrency}")
            return 0

    monkeypatch.setattr(worker_module, "build_container", lambda _settings: container)
    monkeypatch.setattr(worker_module, "OutboxWorker", Worker)

    asyncio.run(worker_module._run(_args()))

    assert events == ["register", "run:7:2", "retire"]


def test_production_worker_preserves_registration_failure_and_still_closes(monkeypatch) -> None:
    events: list[str] = []
    container = _Container(events, start_error="retrieval_profile_runtime_generation_competing")
    monkeypatch.setattr(worker_module, "build_container", lambda _settings: container)

    with pytest.raises(RuntimeError, match="runtime_generation_competing"):
        asyncio.run(worker_module._run(_args()))

    assert events == ["register", "retire"]


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        once=True,
        loop=False,
        limit=7,
        concurrency=2,
        sleep_seconds=0,
        role="all",
        workload_class=None,
        event_type=None,
    )


class _Container:
    def __init__(self, events: list[str], *, start_error: str | None = None):
        self.events = events
        self.start_error = start_error
        self.settings = SimpleNamespace(auto_create_schema=False)
        self.engine = object()

    async def start_retrieval_runtime(self) -> None:
        self.events.append("register")
        if self.start_error is not None:
            raise RuntimeError(self.start_error)

    async def aclose(self) -> None:
        self.events.append("retire")
