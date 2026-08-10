"""Offline CLI for authenticated strict-v4 cleanup journal transitions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.managed_cleanup_v4_sqlite_journal import (
    JOURNAL_KEY_PURPOSE,
    SQLiteManagedCleanupV4Journal,
)
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.strict_v4_cleanup_authority import (
    AsyncPostgresStrictV4CleanupAuthorityReader,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
)

from infinity_context_server.memory_comparison_managed_v5_strict_v4_cleanup import (
    initiate_strict_v4_cleanup,
    recover_strict_v4_cleanup,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)


class _OneKey:
    def __init__(self, key_id: str, secret: bytes) -> None:
        self._key_id, self._secret = key_id, secret

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        if purpose != JOURNAL_KEY_PURPOSE or key_id != self._key_id:
            raise ValueError("strict-v4 cleanup key identity rejected")
        return self._secret


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-managed-strict-v4-cleanup",
        description=(
            "Operate a provider-free strict-v4 cleanup journal; no paid execution is enabled."
        ),
    )
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--key-file", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--receipt", required=True, type=Path)
    create.add_argument(
        "--registrar-postgres-dsn-file",
        required=True,
        type=Path,
        help="0600 file containing the registrar-only PostgreSQL DSN",
    )
    create.add_argument(
        "--sealer-postgres-dsn-file",
        required=True,
        type=Path,
        help="0600 file containing the sealed-authority readback PostgreSQL DSN",
    )
    create.add_argument("--receipt-key-file", required=True, type=Path)
    create.add_argument("--keyring", required=True, type=Path)
    commands.add_parser("initiate")
    commands.add_parser("recover")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    journal_path = args.journal.resolve(strict=False)
    journal_path.parent.resolve(strict=True)
    keys = _OneKey(args.key_id, _secret(args.key_file.resolve(strict=True)))
    if args.command == "create":
        receipt_store = SQLiteStrictV4PreparationReceiptStore.open(
            args.receipt.resolve(strict=True)
        )
        preparation_authenticator = ProjectionReceiptAuthenticator(
            _secret(args.receipt_key_file.resolve(strict=True))
        )
        readback_authenticator = ProjectionReceiptAuthenticator(
            keys.resolve(purpose=JOURNAL_KEY_PURPOSE, key_id=args.key_id)
        )
        registrar_dsn = _postgres_dsn(args.registrar_postgres_dsn_file.resolve(strict=True))
        sealer_dsn = _postgres_dsn(args.sealer_postgres_dsn_file.resolve(strict=True))

        async def connect_registrar() -> Any:
            import asyncpg

            return await asyncpg.connect(registrar_dsn)

        async def connect_sealer() -> Any:
            import asyncpg

            return await asyncpg.connect(sealer_dsn)

        artifact_keys = _FileKeyIdentityAuthority(args.keyring.resolve(strict=True))
        registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
            connect=connect_registrar,
            authenticator=preparation_authenticator,
        )

        async def recover_preparation():
            return await recover_strict_v4_full_run(
                receipt_store=receipt_store,
                registration_port=registry,
                authenticator=preparation_authenticator,
                key_identity_authority=artifact_keys,
            )

        try:
            receipt = receipt_store.read()
            readback = await AsyncPostgresStrictV4CleanupAuthorityReader(
                connect=connect_sealer,
                recover_preparation=recover_preparation,
                preparation_authenticator=preparation_authenticator,
                readback_authenticator=readback_authenticator,
                authentication_key_id=args.key_id,
            ).read_registered_strict_v4(receipt.run_id_sha256)
            if readback is None:
                raise ValueError("strict-v4 cleanup authority is not sealed")
        finally:
            receipt_store.close()
        journal = SQLiteManagedCleanupV4Journal.create(
            journal_path,
            readback=readback,
            authentication_key_id=args.key_id,
            key_identity_authority=keys,
        )
    else:
        journal = SQLiteManagedCleanupV4Journal.open(journal_path, key_identity_authority=keys)
    try:
        if args.command == "create":
            return {"state": "journal_created", "run_id_sha256": journal.run_id_sha256}
        if args.command == "initiate":
            result = await initiate_strict_v4_cleanup(journal=journal, key_identity_authority=keys)
            return {"replayed": result.replayed, "receipt": result.receipt.payload()}
        recovered = await recover_strict_v4_cleanup(journal=journal, key_identity_authority=keys)
        return {
            "state": "cleanup_complete"
            if recovered.terminal
            else ("cleanup_pending" if recovered.initiation else "cleanup_not_started"),
            "initiation": None if recovered.initiation is None else recovered.initiation.payload(),
            "terminal": None if recovered.terminal is None else recovered.terminal.payload(),
        }
    finally:
        journal.close()


class _FileKeyIdentityAuthority(StrictV4PreparationKeyIdentityPort):
    def __init__(self, path: Path) -> None:
        self._bindings = _object_bytes(_secret(path, min_bytes=2, max_bytes=1 << 20))

    def resolve(self, *, purpose: str, key_id: str) -> bytes:
        binding = self._bindings.get(key_id)
        if type(binding) is not dict or binding.get("purpose") != purpose:
            raise ValueError("strict-v4 cleanup artifact key identity rejected")
        key_file = binding.get("key_file")
        if type(key_file) is not str:
            raise ValueError("strict-v4 cleanup artifact key file is missing")
        path = Path(key_file)
        if not path.is_absolute() or path != path.resolve(strict=False):
            raise ValueError("strict-v4 cleanup artifact key path is invalid")
        return _secret(path.resolve(strict=True))


def _object_bytes(source: bytes) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("strict-v4 cleanup input contains a duplicate key")
            result[key] = value
        return result

    def reject_constant(token: str) -> object:
        raise ValueError(f"strict-v4 cleanup JSON constant {token} is invalid")

    value = json.loads(
        source,
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )
    if type(value) is not dict:
        raise ValueError("strict-v4 cleanup input must be one JSON object")
    return value


def _secret(path: Path, *, min_bytes: int = 32, max_bytes: int = 4096) -> bytes:
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise ValueError("strict-v4 cleanup key parent is unsafe")
    before = path.lstat()
    fd = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    value = bytearray()
    try:
        actual = os.fstat(fd)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(actual.st_mode)
            or actual.st_uid != os.getuid()
            or actual.st_nlink != 1
            or stat.S_IMODE(actual.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)
        ):
            raise ValueError("strict-v4 cleanup key file is unsafe")
        while chunk := os.read(fd, 4096):
            value.extend(chunk)
            if len(value) > max_bytes:
                raise ValueError("strict-v4 cleanup key is too large")
        final = os.fstat(fd)
        after = path.lstat()
        if (
            len(value) != actual.st_size
            or (after.st_dev, after.st_ino) != (actual.st_dev, actual.st_ino)
            or (final.st_size, final.st_mtime_ns, final.st_ctime_ns)
            != (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns)
        ):
            raise ValueError("strict-v4 cleanup key file was replaced")
        while value.endswith((b"\r", b"\n")):
            value.pop()
        if len(value) < min_bytes:
            raise ValueError("strict-v4 cleanup key is invalid")
        return bytes(value)
    finally:
        for index in range(len(value)):
            value[index] = 0
        os.close(fd)


def _postgres_dsn(path: Path) -> str:
    try:
        value = _secret(path, min_bytes=1, max_bytes=8192).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("strict-v4 cleanup PostgreSQL capability is invalid") from exc
    if not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("strict-v4 cleanup PostgreSQL capability is invalid")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    try:
        value = asyncio.run(_run(_parser().parse_args(argv)))
    except Exception:
        print("strict-v4 cleanup journal failed", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


__all__ = ("main",)
