"""Database management CLI for Core Lite local/server deployments."""

from __future__ import annotations

import argparse
import asyncio
import json
from importlib.resources import files

from infinity_context_adapters.postgres import build_async_engine, create_schema, upgrade_schema

from infinity_context_server.config import Settings


def _strict_v4_roles_sql() -> str:
    return (
        files("infinity_context_adapters.postgres")
        .joinpath("provisioning")
        .joinpath("strict_v4_roles.sql")
        .read_text(encoding="utf-8")
    )


async def provision_strict_v4_roles() -> dict[str, object]:
    """Provision strict-v4 NOLOGIN roles with an administrative connection."""

    settings = Settings()
    settings.validate_for_startup()
    engine = build_async_engine(settings.database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Strict-v4 role provisioning requires PostgreSQL")
        async with engine.begin() as connection:
            raw_connection = await connection.get_raw_connection()
            await raw_connection.driver_connection.execute(_strict_v4_roles_sql())
    finally:
        await engine.dispose()
    return {
        "status": "ok",
        "operation": "provision-strict-v4-roles",
    }


async def upgrade() -> dict[str, object]:
    settings = Settings()
    settings.validate_for_startup()
    engine = build_async_engine(settings.database_url)
    try:
        if engine.dialect.name == "postgresql":
            result = await upgrade_schema(engine)
        else:
            await create_schema(engine)
            return {
                "status": "ok",
                "operation": "upgrade",
                "current_migration": "metadata-test-compatibility",
                "applied_migrations": [],
                "legacy_baseline": False,
            }
    finally:
        await engine.dispose()
    return {
        "status": "ok",
        "operation": "upgrade",
        "current_migration": result.current,
        "applied_migrations": list(result.applied),
        "legacy_baseline": result.legacy_baseline,
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "provision-strict-v4-roles":
        return await provision_strict_v4_roles()
    if args.command == "upgrade":
        return await upgrade()
    raise ValueError(f"Unknown command: {args.command}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Infinity Context database commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("provision-strict-v4-roles")
    sub.add_parser("upgrade")
    print(json.dumps(asyncio.run(_run(parser.parse_args())), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
