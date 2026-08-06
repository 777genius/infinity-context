"""Private SQLite schema authority for the Mem0 v5 evidence store."""

from __future__ import annotations

import hmac
import os
import sqlite3
import stat
from collections.abc import Callable
from functools import cache
from pathlib import Path

SCHEMA = (
    "CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE evidence (
        sequence INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        subject_sha256 TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        predecessor_sha256 TEXT NOT NULL,
        row_sha256 TEXT NOT NULL UNIQUE,
        row_mac_sha256 TEXT NOT NULL,
        UNIQUE(kind, subject_sha256)
    )""",
)


def prepare_private_database_path(path: Path, *, existed: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = os.lstat(path.parent)
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise OSError("unsafe SQLite parent")
    if existed:
        verify_private_database_files(path, require_database=True)
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        _verify_private_stat(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def open_private_owner_lock(path: Path):
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        prior = os.lstat(path)
    except FileNotFoundError:
        prior = None
    if prior is not None:
        _verify_private_stat(prior)
    flags = os.O_RDWR | nofollow
    if prior is None:
        flags |= os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        if prior is None:
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
        elif (opened.st_dev, opened.st_ino) != (prior.st_dev, prior.st_ino):
            raise OSError("SQLite owner lock changed")
        _verify_private_stat(opened)
        return os.fdopen(descriptor, "a+b")
    except BaseException:
        os.close(descriptor)
        raise


def verify_private_database_files(path: Path, *, require_database: bool = False) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            value = os.lstat(candidate)
        except FileNotFoundError:
            if require_database and candidate == path:
                raise
            continue
        _verify_private_stat(value)


def _verify_private_stat(value: os.stat_result) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise OSError("unsafe SQLite file")


def schema_fingerprint(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )


def incremental_head_matches(
    connection: sqlite3.Connection,
    *,
    row_count: int,
    head_sha256: str,
    empty_root_sha256: str,
    expected_row_mac: Callable[[str], str],
) -> bool:
    last = connection.execute(
        "SELECT sequence, row_sha256, row_mac_sha256 FROM evidence ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    actual_count = connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    if actual_count != row_count:
        return False
    if row_count == 0:
        return last is None and head_sha256 == empty_root_sha256
    return (
        last is not None
        and last["sequence"] == row_count
        and last["row_sha256"] == head_sha256
        and type(last["row_mac_sha256"]) is str
        and hmac.compare_digest(last["row_mac_sha256"], expected_row_mac(head_sha256))
    )


@cache
def expected_schema_fingerprint() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in SCHEMA:
            connection.execute(statement)
        return schema_fingerprint(connection)
    finally:
        connection.close()
