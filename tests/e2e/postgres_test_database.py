"""Isolated real-PostgreSQL database lifecycle for E2E tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from sqlalchemy.engine import make_url

STRICT_V4_CAPABILITY_ROLES = (
    "infinity_context_canonical_writer",
    "infinity_context_strict_v4_registrar",
    "infinity_context_strict_v4_sealer",
)
STRICT_V4_TEST_ROLE_PASSWORD = "strict-v4-role-boundary-test-only"


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
        unique_suffix = uuid.uuid4().hex
        maximum_prefix_bytes = 63 - len(unique_suffix.encode("ascii")) - 1
        bounded_prefix = prefix.encode("utf-8")[:maximum_prefix_bytes].decode(
            "utf-8",
            errors="ignore",
        )
        database_name = f"{bounded_prefix}_{unique_suffix}"
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
            await self._provision_strict_v4_capability_roles(admin)
            await self._terminate_connections(admin)
            await admin.execute(f'DROP DATABASE IF EXISTS "{self.database_name}"')
            await admin.execute(f'CREATE DATABASE "{self.database_name}"')
        finally:
            await admin.close()
        target_admin = await self.asyncpg.connect(self.raw_dsn)
        try:
            await self._provision_strict_v4_capability_roles(target_admin)
        finally:
            await target_admin.close()

    async def drop(self) -> None:
        admin = await self.asyncpg.connect(self.admin_dsn)
        try:
            await self._terminate_connections(admin)
            await admin.execute(f'DROP DATABASE IF EXISTS "{self.database_name}"')
        finally:
            await admin.close()

    async def create_runtime_role(self, *, capability_role: str, suffix: str) -> str:
        if capability_role not in STRICT_V4_CAPABILITY_ROLES:
            raise ValueError("unknown strict-v4 capability role")
        role = f"{self.database_name}_{suffix}"
        admin = await self.asyncpg.connect(self.raw_dsn)
        try:
            await admin.execute(
                f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{STRICT_V4_TEST_ROLE_PASSWORD}'"
            )
            await admin.execute(
                f'GRANT {capability_role} TO "{role}" '
                "WITH INHERIT TRUE, SET FALSE, ADMIN FALSE"
            )
        finally:
            await admin.close()
        return role

    async def drop_runtime_roles(self, *roles: str) -> None:
        admin = await self.asyncpg.connect(self.admin_dsn)
        try:
            for role in roles:
                if not role.startswith(f"{self.database_name}_"):
                    raise ValueError("runtime test role is outside this database namespace")
                await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await admin.close()

    async def connect_as_runtime_role(self, role: str):
        if not role.startswith(f"{self.database_name}_"):
            raise ValueError("runtime test role is outside this database namespace")
        return await self.asyncpg.connect(
            self.raw_dsn,
            user=role,
            password=STRICT_V4_TEST_ROLE_PASSWORD,
        )

    async def connect(self):
        return await self.asyncpg.connect(self.raw_dsn)

    async def _terminate_connections(self, admin) -> None:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            self.database_name,
        )

    async def _provision_strict_v4_capability_roles(self, admin) -> None:
        provisioning_sql = (
            files("infinity_context_adapters.postgres")
            .joinpath("provisioning", "strict_v4_roles.sql")
            .read_text(encoding="utf-8")
        )
        await admin.execute(provisioning_sql)


__all__ = ("PostgresTestDatabase",)
