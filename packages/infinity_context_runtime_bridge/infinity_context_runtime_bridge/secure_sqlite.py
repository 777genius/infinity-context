"""Race-resistant private SQLite path helpers for the bridge journal."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import suppress
from pathlib import Path

from .contracts import BridgeJournalError


def create_private_sqlite(path: Path) -> tuple[sqlite3.Connection, int]:
    _validate_path_shape(path)
    try:
        path.parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_parent_create_failed") from exc
    _verify_parent(path.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_create_failed") from exc
    finally:
        os.umask(previous_umask)
    connection: sqlite3.Connection | None = None
    try:
        verify_private_sqlite(path, descriptor)
        connection = _connect_descriptor(descriptor)
        verify_private_sqlite(path, descriptor)
        return connection, descriptor
    except BaseException:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
        with suppress(BridgeJournalError, OSError):
            unlink_bound_private_sqlite(path, descriptor)
        os.close(descriptor)
        raise


def open_private_sqlite(path: Path) -> tuple[sqlite3.Connection, int]:
    _validate_path_shape(path)
    _verify_parent(path.parent)
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise BridgeJournalError("bridge_journal_file_unsafe")
        flags = os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        _verify_descriptor(descriptor)
        _verify_same_inode(before, descriptor)
        verify_private_sqlite(path, descriptor)
        connection = _connect_descriptor(descriptor)
        verify_private_sqlite(path, descriptor)
        return connection, descriptor
    except BaseException as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, OSError):
            raise BridgeJournalError("bridge_journal_open_failed") from exc
        raise


def close_private_sqlite(connection: sqlite3.Connection, descriptor: int) -> None:
    try:
        connection.close()
    finally:
        os.close(descriptor)


def verify_private_sqlite(path: Path, descriptor: int) -> None:
    """Require the stable private path to name the already-open exact inode."""

    try:
        _verify_parent(path.parent)
        _verify_descriptor(descriptor)
        current = path.lstat()
        if stat.S_ISLNK(current.st_mode):
            raise BridgeJournalError("bridge_journal_file_replaced")
        _verify_same_inode(current, descriptor)
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_file_replaced") from exc


def unlink_bound_private_sqlite(path: Path, descriptor: int) -> None:
    """Unlink only when the pathname still names the validated open inode."""

    verify_private_sqlite(path, descriptor)
    try:
        path.unlink()
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_unlink_failed") from exc


def fsync_private_sqlite(path: Path, descriptor: int) -> None:
    verify_private_sqlite(path, descriptor)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_fsync_failed") from exc
    verify_private_sqlite(path, descriptor)


def _connect_descriptor(descriptor: int) -> sqlite3.Connection:
    try:
        return sqlite3.connect(
            f"file:/proc/self/fd/{descriptor}?mode=rw",
            uri=True,
            isolation_level=None,
            timeout=10.0,
            check_same_thread=False,
        )
    except sqlite3.Error as exc:
        raise BridgeJournalError("bridge_journal_sqlite_connect_failed") from exc


def _validate_path_shape(path: object) -> None:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name in {"", ".", ".."}
        or path.parent == path
    ):
        raise BridgeJournalError("bridge_journal_path_invalid")


def _verify_parent(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise BridgeJournalError("bridge_journal_parent_unsafe") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise BridgeJournalError("bridge_journal_parent_unsafe")


def _verify_descriptor(descriptor: int) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise BridgeJournalError("bridge_journal_file_unsafe")


def _verify_same_inode(value: os.stat_result, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    if (value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino):
        raise BridgeJournalError("bridge_journal_file_replaced")


__all__ = (
    "close_private_sqlite",
    "create_private_sqlite",
    "fsync_private_sqlite",
    "open_private_sqlite",
    "unlink_bound_private_sqlite",
    "verify_private_sqlite",
)
