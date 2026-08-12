"""Hostile real-PostgreSQL drift checks for the canonical writer predicate."""

from __future__ import annotations

import asyncio
import os

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from postgres_test_database import PostgresTestDatabase

_CANONICAL_ROLE = "infinity_context_canonical_writer"


def test_canonical_checker_rejects_capability_drift_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_canonical_checker_rejects_capability_drift(database_url))


async def _assert_canonical_checker_rejects_capability_drift(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="strict_v4_checker_drift",
        asyncpg=asyncpg,
    )
    await database.recreate()
    runtime_role = ""
    try:
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
        finally:
            await engine.dispose()

        runtime_role = await database.create_runtime_role(
            capability_role=_CANONICAL_ROLE,
            suffix="canonical",
        )
        runtime = await database.connect_as_runtime_role(runtime_role)
        admin = await database.connect()
        try:
            await _assert_checker(runtime, expected=True)

            await admin.execute(f"ALTER ROLE {_CANONICAL_ROLE} CREATEROLE")
            try:
                await _assert_checker(runtime, expected=False)
            finally:
                await admin.execute(f"ALTER ROLE {_CANONICAL_ROLE} NOCREATEROLE")
            await _assert_checker(runtime, expected=True)

            await admin.execute(f'GRANT {_CANONICAL_ROLE} TO "{runtime_role}" WITH ADMIN OPTION')
            try:
                await _assert_checker(runtime, expected=False)
            finally:
                await admin.execute(
                    f'REVOKE ADMIN OPTION FOR {_CANONICAL_ROLE} FROM "{runtime_role}"'
                )
            await _assert_checker(runtime, expected=True)

            await admin.execute(
                f"GRANT SELECT ON TABLE public.memory_spaces TO {_CANONICAL_ROLE} WITH GRANT OPTION"
            )
            try:
                await _assert_checker(runtime, expected=False)
            finally:
                await admin.execute(
                    "REVOKE GRANT OPTION FOR SELECT ON TABLE public.memory_spaces "
                    f"FROM {_CANONICAL_ROLE}"
                )
            await _assert_checker(runtime, expected=True)

            checker = "FUNCTION public.memory_comparison_is_strict_v4_canonical_writer()"
            await admin.execute(
                f"GRANT EXECUTE ON {checker} TO {_CANONICAL_ROLE} WITH GRANT OPTION"
            )
            try:
                await _assert_checker(runtime, expected=False)
            finally:
                await admin.execute(f"REVOKE ALL ON {checker} FROM {_CANONICAL_ROLE}")
                await admin.execute(f"GRANT EXECUTE ON {checker} TO {_CANONICAL_ROLE}")
            await _assert_checker(runtime, expected=True)
        finally:
            await runtime.close()
            await admin.close()
    finally:
        if runtime_role:
            await database.drop_runtime_roles(runtime_role)
        await database.drop()


async def _assert_checker(connection, *, expected: bool) -> None:
    observed = await connection.fetchval(
        "SELECT public.memory_comparison_is_strict_v4_canonical_writer()"
    )
    assert observed is expected
