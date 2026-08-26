from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_server import main as main_module


def test_lifespan_registers_runtime_after_schema_and_before_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    container = _Container(events)
    monkeypatch.setattr(main_module, "build_container", lambda _settings: container)
    monkeypatch.setattr(main_module, "create_schema", _record_schema(events))
    monkeypatch.setattr(main_module, "ProjectionOutboxProcess", _Process)

    app = main_module.create_app()

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            events.append("serve")

    asyncio.run(exercise())

    assert events == ["schema", "register", "reconcile", "serve", "retire"]


def test_registration_failure_prevents_serving_and_still_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    container = _Container(events, start_error="runtime_generation_competing")
    monkeypatch.setattr(main_module, "build_container", lambda _settings: container)
    monkeypatch.setattr(main_module, "create_schema", _record_schema(events))
    monkeypatch.setattr(main_module, "ProjectionOutboxProcess", _Process)

    app = main_module.create_app()

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            events.append("serve")

    with pytest.raises(RuntimeError, match="runtime_generation_competing"):
        asyncio.run(exercise())

    assert events == ["schema", "register", "retire"]


class _Container:
    def __init__(self, events: list[str], *, start_error: str | None = None):
        self.events = events
        self.start_error = start_error
        self.settings = SimpleNamespace(
            auto_create_schema=True,
            legacy_client_enabled=False,
            ui_enabled=False,
        )
        self.engine = object()
        self.locator_retrieval = None

    async def start_retrieval_runtime(self) -> None:
        self.events.append("register")
        if self.start_error is not None:
            raise RuntimeError(self.start_error)

    async def aclose(self) -> None:
        self.events.append("retire")


class _Process:
    def __init__(self, container: _Container):
        self.events = container.events

    async def reconcile_vector_tombstones(self, *, limit: int) -> None:
        assert limit == 100
        self.events.append("reconcile")


def _record_schema(events: list[str]):
    async def create_schema(engine: object) -> None:
        assert engine is not None
        events.append("schema")

    return create_schema
