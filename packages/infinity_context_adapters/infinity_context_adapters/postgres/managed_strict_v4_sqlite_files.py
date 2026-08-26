"""Hardened local SQLite handles for provider-free preparation evidence."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path


class StrictV4SQLiteFileError(RuntimeError):
    """A preparation database failed a local-file security invariant."""


def create_strict_sqlite(path: Path) -> tuple[sqlite3.Connection, int]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _verify_parent(path.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    old_umask = os.umask(0o077)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise StrictV4SQLiteFileError("strict_v4_sqlite_create_failed") from exc
    finally:
        os.umask(old_umask)
    db: sqlite3.Connection | None = None
    try:
        _verify_stable(path, fd)
        db = _connect(fd, readonly=False)
        _verify_stable(path, fd)
        return db, fd
    except BaseException:
        try:
            if db is not None:
                db.close()
            with suppress(FileNotFoundError, StrictV4SQLiteFileError):
                unlink_strict_sqlite_binding(path, fd)
        finally:
            os.close(fd)
        raise


def open_strict_sqlite(path: Path, *, readonly: bool) -> tuple[sqlite3.Connection, int]:
    flags = os.O_RDONLY if readonly else os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        _verify_parent(path.parent)
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise StrictV4SQLiteFileError("strict_v4_sqlite_file_unsafe")
        fd = os.open(path, flags)
        _verify_descriptor(fd)
        _verify_same(before, fd)
        _verify_stable(path, fd)
        db = _connect(fd, readonly=readonly)
        _verify_stable(path, fd)
        if readonly:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA query_only").fetchone() != (1,):
                raise StrictV4SQLiteFileError("strict_v4_sqlite_readonly_failed")
        return db, fd
    except BaseException as exc:
        if fd is not None:
            os.close(fd)
        if isinstance(exc, OSError):
            raise StrictV4SQLiteFileError("strict_v4_sqlite_open_failed") from exc
        raise


def close_strict_sqlite(db: sqlite3.Connection, fd: int) -> None:
    try:
        db.close()
    finally:
        os.close(fd)


def wipe(secret: bytearray) -> None:
    for index in range(len(secret)):
        secret[index] = 0


def verify_exact_schema(db: sqlite3.Connection, table_sql: Mapping[str, str]) -> None:
    """Reject catalog drift, lookalike tables, triggers, views, and indexes."""
    expected = [
        ("index", "sqlite_autoindex_claims_1", "claims", None),
        ("index", "sqlite_autoindex_claims_2", "claims", None),
        ("index", "sqlite_autoindex_pages_1", "pages", None),
        ("index", "sqlite_autoindex_sessions_1", "sessions", None),
    ]
    expected.extend(("table", name, name, _normalized_sql(sql)) for name, sql in table_sql.items())
    actual = [
        (str(kind), str(name), str(owner), None if sql is None else _normalized_sql(str(sql)))
        for kind, name, owner, sql in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        )
    ]
    if (
        actual != sorted(expected)
        or db.execute("PRAGMA foreign_keys").fetchone() != (1,)
        or db.execute("PRAGMA trusted_schema").fetchone() != (0,)
    ):
        raise StrictV4SQLiteFileError("strict_v4_sqlite_schema_unsafe")


def verify_strict_sqlite_binding(path: Path, fd: int) -> None:
    """Prove the named path still resolves to the held secure descriptor."""
    _verify_stable(path, fd)


def unlink_strict_sqlite_binding(path: Path, fd: int) -> None:
    """Unlink only the exact still-bound inode while bootstrap repair is locked."""
    _verify_stable(path, fd)
    path.unlink()


@contextmanager
def exclusive_parent_lock(path: Path) -> Iterator[None]:
    """Serialize repair through the stable private parent directory inode."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        _verify_parent(path)
        current = path.lstat()
        actual = os.fstat(fd)
        if current.st_dev != actual.st_dev or current.st_ino != actual.st_ino:
            raise StrictV4SQLiteFileError("strict_v4_sqlite_parent_replaced")
        fcntl.flock(fd, fcntl.LOCK_EX)
        _verify_parent(path)
        yield
        _verify_parent(path)
    finally:
        os.close(fd)


def _normalized_sql(value: str) -> str:
    return " ".join(value.split())


def _connect(fd: int, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    db = sqlite3.connect(f"file:/proc/self/fd/{fd}?mode={mode}", uri=True, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def _verify_descriptor(fd: int) -> None:
    value = os.fstat(fd)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise StrictV4SQLiteFileError("strict_v4_sqlite_file_unsafe")


def _verify_stable(path: Path, fd: int) -> None:
    _verify_parent(path.parent)
    current = path.lstat()
    if stat.S_ISLNK(current.st_mode):
        raise StrictV4SQLiteFileError("strict_v4_sqlite_file_replaced")
    _verify_descriptor(fd)
    _verify_same(current, fd)


def _verify_same(value: os.stat_result, fd: int) -> None:
    actual = os.fstat(fd)
    if value.st_dev != actual.st_dev or value.st_ino != actual.st_ino:
        raise StrictV4SQLiteFileError("strict_v4_sqlite_file_replaced")


def _verify_parent(path: Path) -> None:
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise StrictV4SQLiteFileError("strict_v4_sqlite_parent_unsafe")


__all__ = (
    "StrictV4SQLiteFileError",
    "close_strict_sqlite",
    "create_strict_sqlite",
    "exclusive_parent_lock",
    "open_strict_sqlite",
    "unlink_strict_sqlite_binding",
    "verify_exact_schema",
    "verify_strict_sqlite_binding",
    "wipe",
)
