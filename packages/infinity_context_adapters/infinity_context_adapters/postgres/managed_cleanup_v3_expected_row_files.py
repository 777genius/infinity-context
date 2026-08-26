"""Race-resistant local files for cleanup-v3 authority evidence."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
from contextlib import suppress
from pathlib import Path

from infinity_context_core.ports.managed_cleanup_v3_contracts import ManagedCleanupV3Error


def create_secure_sqlite(path: Path) -> tuple[sqlite3.Connection, int]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _verify_parent(path.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_create") from exc
    finally:
        os.umask(previous_umask)
    db: sqlite3.Connection | None = None
    try:
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
        db = _connect_descriptor(descriptor, readonly=False)
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
        _verify_parent(path.parent)
        return db, descriptor
    except BaseException:
        if db is not None:
            with suppress(sqlite3.Error):
                db.close()
        try:
            unlink_secure_file(path, descriptor)
        except (ManagedCleanupV3Error, OSError):
            pass
        finally:
            os.close(descriptor)
        raise


def open_secure_sqlite(path: Path, *, readonly: bool) -> tuple[sqlite3.Connection, int]:
    flags = os.O_RDONLY if readonly else os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        _verify_parent(path.parent)
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_unsafe")
        descriptor = os.open(path, flags)
        _verify_descriptor(descriptor)
        _verify_stat(before, descriptor)
        _verify_path(path, descriptor)
        db = _connect_descriptor(descriptor, readonly=readonly)
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
        _verify_parent(path.parent)
        return db, descriptor
    except BaseException as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, OSError):
            raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_open") from exc
        raise


def close_secure_sqlite(db: sqlite3.Connection, descriptor: int) -> None:
    try:
        db.close()
    finally:
        os.close(descriptor)


def open_secure_lock(path: Path) -> int:
    """Open and exclusively lock a private, stable per-index lock file."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _verify_parent(path.parent)
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_lock_open") from exc
    finally:
        os.umask(previous_umask)
    try:
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
        _verify_parent(path.parent)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def close_secure_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def unlink_secure_file(path: Path, descriptor: int) -> None:
    """Unlink only the private path still naming the exact open inode."""
    _verify_parent(path.parent)
    _verify_descriptor(descriptor)
    _verify_path(path, descriptor)
    path.unlink()


def secure_file_identity(descriptor: int) -> tuple[int, int, int]:
    """Return mutation-sensitive state for the already policy-validated inode."""
    _verify_descriptor(descriptor)
    value = os.fstat(descriptor)
    return value.st_size, value.st_mtime_ns, value.st_ctime_ns


def verify_secure_path(path: Path, descriptor: int) -> None:
    """Require the private path to still name the exact validated open inode."""
    try:
        _verify_parent(path.parent)
        _verify_descriptor(descriptor)
        _verify_path(path, descriptor)
    except OSError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_replaced") from exc


def _connect_descriptor(descriptor: int, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    return sqlite3.connect(f"file:/proc/self/fd/{descriptor}?mode={mode}", uri=True)


def _verify_descriptor(descriptor: int) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_unsafe")


def _verify_path(path: Path, descriptor: int) -> None:
    path_value = path.lstat()
    if stat.S_ISLNK(path_value.st_mode):
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_replaced")
    _verify_stat(path_value, descriptor)


def _verify_stat(path_value: os.stat_result, descriptor: int) -> None:
    descriptor_value = os.fstat(descriptor)
    if path_value.st_dev != descriptor_value.st_dev or path_value.st_ino != descriptor_value.st_ino:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_file_replaced")


def _verify_parent(path: Path) -> None:
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_parent_unsafe")


__all__ = (
    "close_secure_lock",
    "close_secure_sqlite",
    "create_secure_sqlite",
    "open_secure_lock",
    "open_secure_sqlite",
    "secure_file_identity",
    "unlink_secure_file",
    "verify_secure_path",
)
