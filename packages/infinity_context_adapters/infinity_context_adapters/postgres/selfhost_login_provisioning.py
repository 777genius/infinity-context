"""Administrative provisioning for isolated self-host PostgreSQL identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

SELFHOST_MIGRATOR_ROLE = "infinity_context_migrator"
SELFHOST_RUNTIME_ROLE = "infinity_context_runtime"
SELFHOST_CANONICAL_WRITER_LOGIN_ROLE = "infinity_context_canonical_writer_login"
SELFHOST_REGISTRAR_LOGIN_ROLE = "infinity_context_strict_v4_registrar_login"
SELFHOST_SEALER_LOGIN_ROLE = "infinity_context_strict_v4_sealer_login"
SELFHOST_LOGIN_ROLES = (
    SELFHOST_MIGRATOR_ROLE,
    SELFHOST_RUNTIME_ROLE,
    SELFHOST_CANONICAL_WRITER_LOGIN_ROLE,
    SELFHOST_REGISTRAR_LOGIN_ROLE,
    SELFHOST_SEALER_LOGIN_ROLE,
)

_PROVISIONING_DIRECTORY = Path(__file__).with_name("provisioning")
_CAPABILITY_SQL_PATH = _PROVISIONING_DIRECTORY / "strict_v4_roles.sql"
_LOGIN_SQL_PATH = _PROVISIONING_DIRECTORY / "selfhost_login_identities.sql"
_RESTORED_OBJECT_OWNERSHIP_SQL_PATH = (
    _PROVISIONING_DIRECTORY / "restored_object_ownership.sql"
)
_PASSWORD_PLACEHOLDERS = (
    "__MIGRATOR_PASSWORD__",
    "__RUNTIME_PASSWORD__",
    "__CANONICAL_WRITER_PASSWORD__",
    "__REGISTRAR_PASSWORD__",
    "__SEALER_PASSWORD__",
)


@dataclass(frozen=True, slots=True)
class SelfHostLoginPasswords:
    migrator: str
    runtime: str
    canonical_writer: str
    registrar: str
    sealer: str

    def validate(self) -> None:
        values = self.values()
        if any(not value for value in values):
            raise ValueError("all self-host login passwords are required")
        if len(set(values)) != len(values):
            raise ValueError("self-host login passwords must be distinct")
        if any("\x00" in value for value in values):
            raise ValueError("self-host login passwords contain invalid characters")

    def values(self) -> tuple[str, ...]:
        return (
            self.migrator,
            self.runtime,
            self.canonical_writer,
            self.registrar,
            self.sealer,
        )


async def provision_selfhost_login_identities(
    engine: AsyncEngine,
    passwords: SelfHostLoginPasswords,
) -> None:
    """Create missing capability/login roles without rotating existing passwords."""

    await _apply_identity_provisioning(engine, passwords=passwords, rotate=False)


async def rotate_selfhost_login_passwords(
    engine: AsyncEngine,
    passwords: SelfHostLoginPasswords,
) -> None:
    """Explicitly rotate passwords after validating every existing identity."""

    await _apply_identity_provisioning(engine, passwords=passwords, rotate=True)


async def _apply_identity_provisioning(
    engine: AsyncEngine,
    *,
    passwords: SelfHostLoginPasswords,
    rotate: bool,
) -> None:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("self-host identity provisioning requires PostgreSQL")
    passwords.validate()
    capability_sql = _CAPABILITY_SQL_PATH.read_text(encoding="utf-8")
    login_sql = _render_login_sql(passwords=passwords, rotate=rotate)
    restored_object_ownership_sql = _RESTORED_OBJECT_OWNERSHIP_SQL_PATH.read_text(
        encoding="utf-8"
    )
    try:
        async with engine.begin() as connection:
            raw_connection = await connection.get_raw_connection()
            driver_connection = raw_connection.driver_connection
            await driver_connection.execute(capability_sql)
            await driver_connection.execute(login_sql)
            await driver_connection.execute(restored_object_ownership_sql)
    except Exception:
        raise RuntimeError("self-host identity provisioning failed") from None


def _render_login_sql(*, passwords: SelfHostLoginPasswords, rotate: bool) -> str:
    sql = _LOGIN_SQL_PATH.read_text(encoding="utf-8")
    replacements = dict(
        zip(_PASSWORD_PLACEHOLDERS, map(_quote_literal, passwords.values()), strict=True)
    )
    replacements["__ROTATE_PASSWORDS__"] = "TRUE" if rotate else "FALSE"
    for placeholder, value in replacements.items():
        if sql.count(placeholder) != 1:
            raise RuntimeError("invalid packaged self-host identity provisioning SQL")
        sql = sql.replace(placeholder, value)
    return sql


def _quote_literal(value: str) -> str:
    # Explicit escape strings parse consistently even when the session changes
    # standard_conforming_strings. Backslashes must be escaped before quotes.
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return "E'" + escaped + "'"


__all__ = (
    "SELFHOST_CANONICAL_WRITER_LOGIN_ROLE",
    "SELFHOST_LOGIN_ROLES",
    "SELFHOST_MIGRATOR_ROLE",
    "SELFHOST_REGISTRAR_LOGIN_ROLE",
    "SELFHOST_RUNTIME_ROLE",
    "SELFHOST_SEALER_LOGIN_ROLE",
    "SelfHostLoginPasswords",
    "provision_selfhost_login_identities",
    "rotate_selfhost_login_passwords",
)
