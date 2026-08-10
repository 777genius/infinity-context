"""Race-resistant local SQLite files for original-pair authority."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path


class OriginalPairIdentityAuthorityError(RuntimeError):
    pass


def create_secure_sqlite(target: Path) -> tuple[sqlite3.Connection, int]:
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _verify_parent(target.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_exists") from exc
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_create_invalid") from exc
    finally:
        os.umask(previous_umask)
    try:
        verify_bound(target, descriptor)
        db = _connect_descriptor(descriptor, readonly=False)
        verify_bound(target, descriptor)
        return db, descriptor
    except BaseException:
        unlink_bound(target, descriptor)
        os.close(descriptor)
        raise


def open_secure_sqlite(target: Path) -> tuple[sqlite3.Connection, int]:
    _verify_parent(target.parent)
    try:
        before = target.lstat()
        if stat.S_ISLNK(before.st_mode):
            _fail("store_unsafe")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
    except OriginalPairIdentityAuthorityError:
        raise
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_missing") from exc
    try:
        _verify_descriptor(descriptor)
        _verify_same_stat(before, descriptor)
        verify_bound(target, descriptor)
        db = _connect_descriptor(descriptor, readonly=True)
        verify_bound(target, descriptor)
        return db, descriptor
    except BaseException:
        os.close(descriptor)
        raise


def verify_bound(target: Path, descriptor: int) -> None:
    _verify_descriptor(descriptor)
    try:
        value = target.lstat()
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_replaced") from exc
    if stat.S_ISLNK(value.st_mode):
        _fail("store_replaced")
    _verify_same_stat(value, descriptor)


def unlink_bound(target: Path, descriptor: int) -> None:
    try:
        verify_bound(target, descriptor)
        target.unlink()
    except (OSError, OriginalPairIdentityAuthorityError):
        pass


def discard_secure_file(target: Path) -> None:
    """Remove one private regular staging file without following links."""

    _verify_parent(target.parent)
    try:
        before = target.lstat()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_partial_unsafe") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) & 0o077
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            _fail("partial_unsafe")
        target.unlink()
        if os.fstat(descriptor).st_nlink != 0:
            _fail("partial_replaced")
        _sync_parent(target.parent)
    finally:
        os.close(descriptor)


def publish_secure_sqlite(staging: Path, target: Path) -> None:
    """Atomically publish a completed private SQLite file without overwrite."""

    if staging.parent != target.parent:
        _fail("publish_invalid")
    _verify_parent(target.parent)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = staging.lstat()
        descriptor = os.open(staging, flags)
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_publish_invalid") from exc
    try:
        _verify_descriptor(descriptor)
        _verify_same_stat(before, descriptor)
        os.link(staging, target, follow_symlinks=False)
        published = target.lstat()
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(published.st_mode)
            or (published.st_dev, published.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_nlink != 2
        ):
            _fail("publish_replaced")
        staging.unlink()
        verify_bound(target, descriptor)
        _sync_parent(target.parent)
    finally:
        os.close(descriptor)


def recover_secure_sqlite_publish(staging: Path, target: Path) -> bool:
    """Finish the sole recoverable crash point between link and staging unlink."""

    if staging.parent != target.parent:
        _fail("publish_invalid")
    _verify_parent(target.parent)
    try:
        staged = staging.lstat()
        published = target.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_publish_invalid") from exc
    if (staged.st_dev, staged.st_ino) != (published.st_dev, published.st_ino):
        return False
    if (
        stat.S_ISLNK(staged.st_mode)
        or not stat.S_ISREG(staged.st_mode)
        or staged.st_uid != os.getuid()
        or stat.S_IMODE(staged.st_mode) != 0o600
        or staged.st_nlink != 2
    ):
        _fail("publish_recovery_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (staged.st_dev, staged.st_ino):
            _fail("publish_replaced")
        staging.unlink()
        verify_bound(target, descriptor)
        _sync_parent(target.parent)
    finally:
        os.close(descriptor)
    return True


def _connect_descriptor(descriptor: int, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    return sqlite3.connect(f"file:/proc/self/fd/{descriptor}?mode={mode}", uri=True)


def _verify_parent(target: Path) -> None:
    try:
        value = target.lstat()
    except OSError as exc:
        raise OriginalPairIdentityAuthorityError("original_pair_store_parent_unsafe") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) & 0o077
    ):
        _fail("store_parent_unsafe")


def _sync_parent(target: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    try:
        value = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.getuid()
            or stat.S_IMODE(value.st_mode) & 0o077
        ):
            _fail("store_parent_unsafe")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_descriptor(descriptor: int) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        _fail("store_unsafe")


def _verify_same_stat(value: os.stat_result, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    if (value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino):
        _fail("store_replaced")


def _fail(suffix: str) -> None:
    raise OriginalPairIdentityAuthorityError(f"original_pair_{suffix}")


__all__ = (
    "OriginalPairIdentityAuthorityError",
    "create_secure_sqlite",
    "discard_secure_file",
    "open_secure_sqlite",
    "publish_secure_sqlite",
    "recover_secure_sqlite_publish",
    "unlink_bound",
    "verify_bound",
)
