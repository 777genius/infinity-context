from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_core.features.context_building.public import RuntimeFenceOwner
from infinity_context_server.composition import Container
from infinity_context_server.retrieval_runtime_lifecycle import RetrievalRuntimeLifecycle

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def test_runtime_lifecycle_registers_and_retires_exactly_once() -> None:
    registry = _Registry()
    owner = _owner("generation-a")
    lifecycle = RetrievalRuntimeLifecycle(registry, owner)

    async def exercise() -> None:
        await asyncio.gather(lifecycle.start(now=NOW), lifecycle.start(now=NOW))
        await asyncio.gather(
            lifecycle.close(now=NOW + timedelta(seconds=1)),
            lifecycle.close(now=NOW + timedelta(seconds=1)),
        )

    asyncio.run(exercise())

    assert registry.calls == [("register", owner), ("retire", owner)]


def test_runtime_lifecycle_does_not_hide_competing_generation() -> None:
    registry = _Registry(register_error="retrieval_profile_runtime_generation_competing")
    lifecycle = RetrievalRuntimeLifecycle(registry, _owner("generation-b"))

    with pytest.raises(RuntimeError, match="runtime_generation_competing"):
        asyncio.run(lifecycle.start(now=NOW))

    assert [name for name, _owner_value in registry.calls] == ["register"]


def test_runtime_lifecycle_retries_failed_retirement_without_double_registration() -> None:
    registry = _Registry(retire_error="retrieval_profile_runtime_not_drained")
    lifecycle = RetrievalRuntimeLifecycle(registry, _owner("generation-c"))

    async def exercise() -> None:
        await lifecycle.start(now=NOW)
        with pytest.raises(RuntimeError, match="runtime_not_drained"):
            await lifecycle.close(now=NOW + timedelta(seconds=1))
        registry.retire_error = None
        await lifecycle.close(now=NOW + timedelta(seconds=2))

    asyncio.run(exercise())

    assert [name for name, _owner_value in registry.calls] == [
        "register",
        "retire",
        "retire",
    ]


def test_container_close_preserves_retirement_error_and_closes_resources() -> None:
    events: list[str] = []
    container = SimpleNamespace(
        retrieval_runtime_lifecycle=_FailingRuntimeClose(events),
        clock=SimpleNamespace(now=lambda: NOW),
        adapters=(_FailingResource(events),),
        cognee_memory=None,
        vector_index=None,
        graph_index=None,
        vector_projection_evidence=None,
        graph_projection_evidence=None,
        embedder=None,
        engine=_Engine(events),
    )

    with pytest.raises(RuntimeError, match="runtime_not_drained"):
        asyncio.run(Container.aclose(container))

    assert events == ["retire", "resource-close", "engine-dispose"]


def _owner(generation: str) -> RuntimeFenceOwner:
    return RuntimeFenceOwner.unrecoverable_current(
        instance_id="stable-runtime-instance",
        generation=generation,
        key_id="test-unrecoverable",
    )


class _Registry:
    def __init__(self, *, register_error: str | None = None, retire_error: str | None = None):
        self.register_error = register_error
        self.retire_error = retire_error
        self.calls: list[tuple[str, RuntimeFenceOwner]] = []

    async def register_runtime_incarnation(self, owner, *, now):
        del now
        self.calls.append(("register", owner))
        if self.register_error is not None:
            raise RuntimeError(self.register_error)

    async def retire_runtime_incarnation(self, owner, *, now):
        del now
        self.calls.append(("retire", owner))
        if self.retire_error is not None:
            raise RuntimeError(self.retire_error)


class _FailingRuntimeClose:
    def __init__(self, events: list[str]):
        self.events = events

    async def close(self, *, now):
        assert now == NOW
        self.events.append("retire")
        raise RuntimeError("retrieval_profile_runtime_not_drained")


class _FailingResource:
    def __init__(self, events: list[str]):
        self.events = events

    async def aclose(self):
        self.events.append("resource-close")
        raise RuntimeError("secondary_resource_failure")


class _Engine:
    def __init__(self, events: list[str]):
        self.events = events

    async def dispose(self):
        self.events.append("engine-dispose")
