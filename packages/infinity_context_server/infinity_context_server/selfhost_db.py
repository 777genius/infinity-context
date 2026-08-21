"""Explicit administrative database commands for self-host deployments."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from os import environ

from infinity_context_adapters.postgres.runtime_acl import reconcile_runtime_acl
from infinity_context_adapters.postgres.unit_of_work import build_async_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from infinity_context_server.selfhost_identity_config import (
    apply_selfhost_identity_provisioning,
)

MIGRATOR_DATABASE_URL_ENV = "MEMORY_DATABASE_URL"


def _load_migrator_database_url(environment: Mapping[str, str] | None = None) -> str:
    source = environ if environment is None else environment
    database_url = source.get(MIGRATOR_DATABASE_URL_ENV, "")
    if not database_url:
        raise RuntimeError(f"required database setting is missing: {MIGRATOR_DATABASE_URL_ENV}")
    try:
        parsed = make_url(database_url)
    except ArgumentError:
        raise RuntimeError("migrator database URL is invalid") from None
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("migrator database URL must use PostgreSQL")
    if not parsed.username or not parsed.password:
        raise RuntimeError("migrator database URL must include credentials")
    return database_url


async def _reconcile_runtime_acl() -> None:
    engine = build_async_engine(_load_migrator_database_url())
    try:
        await reconcile_runtime_acl(engine)
    finally:
        await engine.dispose()


async def _run(args: argparse.Namespace) -> dict[str, str]:
    if args.command == "provision-identities":
        await apply_selfhost_identity_provisioning(rotate_passwords=False)
    elif args.command == "rotate-passwords":
        await apply_selfhost_identity_provisioning(rotate_passwords=True)
    elif args.command == "reconcile-runtime-acl":
        await _reconcile_runtime_acl()
    else:  # pragma: no cover - argparse constrains the public command surface.
        raise ValueError(f"Unknown command: {args.command}")
    return {"operation": args.command, "status": "ok"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Infinity Context self-host database administration"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provision-identities")
    commands.add_parser("rotate-passwords")
    commands.add_parser("reconcile-runtime-acl")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    result = asyncio.run(_run(_parser().parse_args(argv)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
