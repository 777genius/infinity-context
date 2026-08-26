from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import locator_index_maintenance


class _Connection:
    def __init__(
        self,
        *,
        lock_result: bool | BaseException = True,
        unlock_result: bool | BaseException = True,
    ) -> None:
        self.lock_result = lock_result
        self.unlock_result = unlock_result
        self.invalidated = False
        self.closed = False
        self.statements: list[str] = []

    async def execution_options(self, **_kwargs):
        return self

    async def scalar(self, statement, *_args, **_kwargs):
        normalized = " ".join(str(statement).split())
        self.statements.append(normalized)
        result = (
            self.unlock_result
            if "pg_advisory_unlock" in normalized
            else self.lock_result
        )
        if isinstance(result, BaseException):
            raise result
        return result

    async def execute(self, statement, *_args, **_kwargs) -> None:
        self.statements.append(" ".join(str(statement).split()))

    async def invalidate(self) -> None:
        self.invalidated = True

    async def close(self) -> None:
        self.closed = True


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def connect(self) -> _Connection:
        return self.connection


@pytest.fixture(autouse=True)
def _isolate_index_work(monkeypatch) -> None:
    async def require_expand(_connection) -> None:
        return None

    class _Attestation:
        mismatches: tuple[object, ...] = ()

        def require_qualified(self) -> None:
            return None

    async def attest(_connection) -> _Attestation:
        return _Attestation()

    monkeypatch.setattr(locator_index_maintenance, "_require_expand_migration", require_expand)
    monkeypatch.setattr(locator_index_maintenance, "_maintenance_statements", lambda _sql: ())
    monkeypatch.setattr(locator_index_maintenance, "attest_locator_retrieval_catalog", attest)


@pytest.mark.parametrize(
    "acquisition_error",
    [OSError("connection lost"), asyncio.CancelledError("acquisition cancelled")],
)
def test_uncertain_acquisition_discards_connection(
    acquisition_error: BaseException,
) -> None:
    connection = _Connection(lock_result=acquisition_error)

    with pytest.raises(type(acquisition_error), match=str(acquisition_error)):
        asyncio.run(
            locator_index_maintenance.build_locator_retrieval_indexes(_Engine(connection))
        )

    assert connection.invalidated
    assert connection.closed


def test_completed_false_acquisition_closes_without_discard() -> None:
    connection = _Connection(lock_result=False)

    with pytest.raises(RuntimeError, match="already running"):
        asyncio.run(
            locator_index_maintenance.build_locator_retrieval_indexes(_Engine(connection))
        )

    assert not connection.invalidated
    assert connection.closed


@pytest.mark.parametrize(
    ("unlock_result", "error_type"),
    [
        (False, RuntimeError),
        (OSError("connection lost"), OSError),
        (asyncio.CancelledError("unlock cancelled"), asyncio.CancelledError),
    ],
)
def test_uncertain_unlock_discards_connection(
    unlock_result: bool | BaseException,
    error_type: type[BaseException],
) -> None:
    connection = _Connection(unlock_result=unlock_result)

    with pytest.raises(error_type):
        asyncio.run(
            locator_index_maintenance.build_locator_retrieval_indexes(_Engine(connection))
        )

    assert connection.invalidated
    assert connection.closed


@pytest.mark.parametrize(
    "unlock_result",
    [False, OSError("connection lost"), asyncio.CancelledError("unlock cancelled")],
)
def test_uncertain_unlock_preserves_application_error(
    monkeypatch,
    unlock_result: bool | BaseException,
) -> None:
    async def fail_attestation(_connection):
        raise LookupError("original application failure")

    monkeypatch.setattr(
        locator_index_maintenance,
        "attest_locator_retrieval_catalog",
        fail_attestation,
    )
    connection = _Connection(unlock_result=unlock_result)

    with pytest.raises(LookupError, match="original application failure"):
        asyncio.run(
            locator_index_maintenance.build_locator_retrieval_indexes(_Engine(connection))
        )

    assert connection.invalidated
    assert connection.closed
