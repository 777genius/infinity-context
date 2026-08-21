"""Exact least-privilege ACL reconciliation for the general PostgreSQL runtime."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

_RUNTIME_ACL_PATH = Path(__file__).with_name("provisioning") / "runtime_acl.sql"
RUNTIME_ROLE = "infinity_context_runtime"


def load_runtime_acl_sql() -> str:
    """Load the packaged, fixed-identity reconciliation program."""

    return _RUNTIME_ACL_PATH.read_text(encoding="utf-8")


async def reconcile_runtime_acl(engine: AsyncEngine) -> None:
    """Install exact runtime ACLs through the migration object's owner connection."""

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Runtime ACL reconciliation requires PostgreSQL")
    async with engine.begin() as connection:
        raw_connection = await connection.get_raw_connection()
        await raw_connection.driver_connection.execute(load_runtime_acl_sql())


__all__ = ("RUNTIME_ROLE", "load_runtime_acl_sql", "reconcile_runtime_acl")
