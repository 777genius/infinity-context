"""Focused checks for historical PostgreSQL schema fixture ordering."""

from __future__ import annotations

import asyncio
from pathlib import Path

import postgres_versioned_schema_fixtures as fixtures


class _ConnectionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


class _Engine:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def connect(self) -> _ConnectionContext:
        return _ConnectionContext()

    async def dispose(self) -> None:
        self.events.append("dispose")


class _RawConnection:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def execute(self, sql: str) -> None:
        normalized = " ".join(sql.split())
        self.events.append(f"sql:{normalized}")

    async def executemany(self, sql: str, rows: list[tuple[str, str]]) -> None:
        del sql
        self.events.append("history:" + ",".join(row[0] for row in rows))

    async def close(self) -> None:
        return None


class _Database:
    app_url = "postgresql+asyncpg://fixture.invalid/test"

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def connect(self) -> _RawConnection:
        return _RawConnection(self.events)


def test_versioned_fixture_runs_only_historical_stages_in_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    for migration_id in (
        "0038_strict_v4_document_writer",
        "0039_locator_retrieval_attributes",
        "0040_locator_profile_lifecycle",
        "0041_locator_profile_attestation_fence",
    ):
        (tmp_path / f"{migration_id}.sql").write_text(
            f"SELECT '{migration_id}'",
            encoding="utf-8",
        )

    async def apply_stage(connection: object, *, migration_id: str) -> None:
        del connection
        events.append(f"stage:{migration_id}")

    monkeypatch.setattr(fixtures, "_MIGRATIONS", tmp_path)
    monkeypatch.setattr(fixtures, "build_async_engine", lambda url: _Engine(events))
    monkeypatch.setattr(fixtures, "apply_staged_locator_migration", apply_stage)

    asyncio.run(fixtures.install_versioned_schema_through(_Database(events), "0040_"))

    assert events[:5] == [
        "sql:SELECT '0038_strict_v4_document_writer'",
        "stage:0039_locator_retrieval_attributes",
        "sql:SELECT '0039_locator_retrieval_attributes'",
        "stage:0040_locator_profile_lifecycle",
        "sql:SELECT '0040_locator_profile_lifecycle'",
    ]
    assert not any("0041_locator_profile_attestation_fence" in event for event in events)
    assert events[-1].startswith("history:0038_strict_v4_document_writer,")
