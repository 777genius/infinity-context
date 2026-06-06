"""Database management CLI for Core Lite local/server deployments."""

from __future__ import annotations

import argparse
import asyncio
import json

from memo_stack_adapters.postgres import build_async_engine, create_schema

from memo_stack_server.config import Settings


async def upgrade() -> dict[str, object]:
    settings = Settings()
    settings.validate_for_startup()
    engine = build_async_engine(settings.database_url)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
    return {"status": "ok", "operation": "upgrade"}


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "upgrade":
        return await upgrade()
    raise ValueError(f"Unknown command: {args.command}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Memo Stack database commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("upgrade")
    print(json.dumps(asyncio.run(_run(parser.parse_args())), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
