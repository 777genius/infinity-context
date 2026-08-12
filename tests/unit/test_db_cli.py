from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import pytest
from infinity_context_server import db


@dataclass
class _Dialect:
    name: str


class _DriverConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


class _RawConnection:
    def __init__(self, driver: _DriverConnection) -> None:
        self.driver_connection = driver


class _Connection:
    def __init__(self, driver: _DriverConnection) -> None:
        self._driver = driver

    async def get_raw_connection(self) -> _RawConnection:
        return _RawConnection(self._driver)


class _Begin:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _Connection:
        return self._connection

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Engine:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = _Dialect(dialect_name)
        self.driver = _DriverConnection()
        self.disposed = False

    def begin(self) -> _Begin:
        return _Begin(_Connection(self.driver))

    async def dispose(self) -> None:
        self.disposed = True


class _Settings:
    database_url = "postgresql+asyncpg://admin@db/infinity_context"

    def validate_for_startup(self) -> None:
        return None


def _install_engine(monkeypatch: pytest.MonkeyPatch, engine: _Engine) -> None:
    monkeypatch.setattr(db, "Settings", _Settings)
    monkeypatch.setattr(db, "build_async_engine", lambda _url: engine)


def test_provision_strict_v4_roles_executes_packaged_sql_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine("postgresql")
    _install_engine(monkeypatch, engine)
    monkeypatch.setattr(db, "_strict_v4_roles_sql", lambda: "ROLE PROVISIONING SQL")

    result = asyncio.run(db.provision_strict_v4_roles())

    assert result == {
        "status": "ok",
        "operation": "provision-strict-v4-roles",
    }
    assert engine.driver.statements == ["ROLE PROVISIONING SQL"]
    assert engine.disposed is True


def test_provision_strict_v4_roles_rejects_non_postgres_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine("sqlite")
    _install_engine(monkeypatch, engine)

    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        asyncio.run(db.provision_strict_v4_roles())

    assert engine.driver.statements == []
    assert engine.disposed is True


def test_db_cli_dispatches_role_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provision() -> dict[str, object]:
        return {"status": "ok"}

    monkeypatch.setattr(db, "provision_strict_v4_roles", provision)

    result = asyncio.run(db._run(argparse.Namespace(command="provision-strict-v4-roles")))

    assert result == {"status": "ok"}
