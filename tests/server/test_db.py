from __future__ import annotations

import argparse
import asyncio

import pytest
from infinity_context_server import db as subject


def test_locator_index_bootstrap_validates_builds_invokes_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class TestSettings:
        database_url = "postgresql+asyncpg://migrator:secret@db/infinity_context"

        def validate_for_startup(self) -> None:
            events.append("validated")

    class Engine:
        async def dispose(self) -> None:
            events.append("disposed")

    engine = Engine()

    def build(database_url: str) -> Engine:
        events.append(("build", database_url))
        return engine

    async def bootstrap(candidate: object) -> tuple[str, ...]:
        events.append(("bootstrap", candidate))
        return ("index_one", "index_two")

    monkeypatch.setattr(subject, "Settings", TestSettings)
    monkeypatch.setattr(subject, "build_async_engine", build)
    monkeypatch.setattr(subject, "build_locator_retrieval_indexes", bootstrap)

    result = asyncio.run(subject._run(argparse.Namespace(command="bootstrap-locator-indexes")))

    assert result == {
        "status": "ok",
        "operation": "bootstrap-locator-indexes",
        "indexes": ["index_one", "index_two"],
    }
    assert events == [
        "validated",
        ("build", TestSettings.database_url),
        ("bootstrap", engine),
        "disposed",
    ]


def test_locator_index_bootstrap_disposes_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False

    class TestSettings:
        database_url = "postgresql+asyncpg://migrator:secret@db/infinity_context"

        def validate_for_startup(self) -> None:
            pass

    class Engine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    async def fail(_engine: object) -> tuple[str, ...]:
        raise RuntimeError("index bootstrap failed")

    monkeypatch.setattr(subject, "Settings", TestSettings)
    monkeypatch.setattr(subject, "build_async_engine", lambda _url: Engine())
    monkeypatch.setattr(subject, "build_locator_retrieval_indexes", fail)

    with pytest.raises(RuntimeError, match="index bootstrap failed"):
        asyncio.run(subject.bootstrap_locator_indexes())

    assert disposed is True


def test_database_parser_exposes_locator_index_bootstrap() -> None:
    args = subject._parser().parse_args(["bootstrap-locator-indexes"])

    assert args.command == "bootstrap-locator-indexes"
