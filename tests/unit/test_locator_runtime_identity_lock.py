import asyncio

import pytest
from infinity_context_adapters.postgres.locator_runtime_identity import (
    lock_runtime_instance,
)


class _RecordingSession:
    def __init__(self, dialect_name: str) -> None:
        dialect = type("Dialect", (), {"name": dialect_name})()
        self._bind = type("Bind", (), {"dialect": dialect})()
        self.executions: list[tuple[str, dict[str, object]]] = []

    def get_bind(self):
        return self._bind

    async def execute(self, statement, parameters) -> None:
        self.executions.append((str(statement), parameters))


def test_postgres_runtime_identity_lock_keeps_transaction_advisory_lock() -> None:
    session = _RecordingSession("postgresql")

    asyncio.run(lock_runtime_instance(session, "runtime-1"))

    assert session.executions == [
        (
            "SELECT pg_advisory_xact_lock(hashtextextended(:instance_id, 0))",
            {"instance_id": "runtime-1"},
        )
    ]


def test_sqlite_runtime_identity_lock_uses_transaction_serialization() -> None:
    session = _RecordingSession("sqlite")

    asyncio.run(lock_runtime_instance(session, "runtime-1"))

    assert session.executions == []


def test_runtime_identity_lock_rejects_unsupported_dialect() -> None:
    session = _RecordingSession("mysql")

    with pytest.raises(
        RuntimeError, match="retrieval_profile_runtime_lock_dialect_unsupported"
    ):
        asyncio.run(lock_runtime_instance(session, "runtime-1"))

    assert session.executions == []
