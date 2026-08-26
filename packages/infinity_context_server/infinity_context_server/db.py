"""Database management CLI for Core Lite local/server deployments."""

from __future__ import annotations

import argparse
import asyncio
import json

from infinity_context_adapters.postgres import (
    build_async_engine,
    build_locator_retrieval_indexes,
    create_schema,
    upgrade_schema,
)

from infinity_context_server.config import Settings


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


async def bootstrap_locator_indexes() -> dict[str, object]:
    """Build and attest the required Retrieval V2 indexes."""

    settings = Settings()
    settings.validate_for_startup()
    engine = build_async_engine(settings.database_url)
    try:
        indexes = await build_locator_retrieval_indexes(engine)
    finally:
        await engine.dispose()
    return {
        "status": "ok",
        "operation": "bootstrap-locator-indexes",
        "indexes": list(indexes),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "upgrade":
        return await upgrade()
    if args.command == "bootstrap-locator-indexes":
        return await bootstrap_locator_indexes()
    raise ValueError(f"Unknown command: {args.command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infinity Context database commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("upgrade")
    sub.add_parser("bootstrap-locator-indexes")
    return parser


def main() -> None:
    print(json.dumps(asyncio.run(_run(_parser().parse_args())), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
