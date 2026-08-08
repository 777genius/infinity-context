"""Isolated real-PostgreSQL database lifecycle for E2E tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import make_url


@dataclass(frozen=True, slots=True)
class PostgresTestDatabase:
    asyncpg: Any
    admin_dsn: str
    app_url: str
    raw_dsn: str
    database_name: str

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        prefix: str,
        asyncpg: Any,
    ) -> PostgresTestDatabase:
        parsed = make_url(database_url)
        if not parsed.drivername.startswith("postgresql"):
            raise ValueError("PostgreSQL E2E requires a PostgreSQL database URL")
        database_name = f"{prefix}_{uuid.uuid4().hex}"
        return cls(
            asyncpg=asyncpg,
            admin_dsn=parsed.set(drivername="postgresql").render_as_string(hide_password=False),
            app_url=parsed.set(
                drivername="postgresql+asyncpg",
                database=database_name,
            ).render_as_string(hide_password=False),
            raw_dsn=parsed.set(
                drivername="postgresql",
                database=database_name,
            ).render_as_string(hide_password=False),
            database_name=database_name,
        )

    async def recreate(self) -> None:
        admin = await self.asyncpg.connect(self.admin_dsn)
        try:
            await self._terminate_connections(admin)
            await admin.execute(f'DROP DATABASE IF EXISTS "{self.database_name}"')
            await admin.execute(f'CREATE DATABASE "{self.database_name}"')
        finally:
            await admin.close()

    async def drop(self) -> None:
        admin = await self.asyncpg.connect(self.admin_dsn)
        try:
            await self._terminate_connections(admin)
            await admin.execute(f'DROP DATABASE IF EXISTS "{self.database_name}"')
        finally:
            await admin.close()

    async def connect(self):
        return await self.asyncpg.connect(self.raw_dsn)

    async def _terminate_connections(self, admin) -> None:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            self.database_name,
        )


__all__ = ("PostgresTestDatabase",)
