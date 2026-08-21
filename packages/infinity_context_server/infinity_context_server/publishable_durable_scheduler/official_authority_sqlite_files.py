"""Descriptor-pinned private SQLite files for immutable official authorities."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from threading import RLock
from typing import final

from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)


@final
class SecureOfficialAuthoritySQLite:
    """An open SQLite connection bound to one owner-only inode and parent."""

    __slots__ = (
        "connection",
        "descriptor",
        "parent_descriptor",
        "path",
        "readonly",
        "_closed",
        "_lock",
        "_stable_identity",
    )

    def __init__(
        self,
        *,
        path: Path,
        parent_descriptor: int,
        descriptor: int,
        connection: sqlite3.Connection,
        readonly: bool,
    ) -> None:
        self.path = path
        self.parent_descriptor = parent_descriptor
        self.descriptor = descriptor
        self.connection = connection
        self.readonly = readonly
        self._closed = False
        self._lock = RLock()
        self._stable_identity: tuple[int, int, int] | None = None

    @contextmanager
    def serialized(self) -> Iterator[None]:
        """Serialize a complete connection/file operation on this handle."""

        with self._lock:
            yield

    def freeze_identity(self) -> None:
        with self.serialized():
            self.verify_bound()
            value = os.fstat(self.descriptor)
            self._stable_identity = (value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            self.verify_stable()

    def verify_bound(self) -> None:
        with self.serialized():
            if self._closed:
                _fail("scheduler_official_authority_file_closed")
            _verify_parent(self.path.parent, self.parent_descriptor)
            _verify_descriptor(self.descriptor)
            try:
                current = os.stat(
                    self.path.name,
                    dir_fd=self.parent_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise SchedulerOfficialAuthorityError(
                    "scheduler_official_authority_file_replaced"
                ) from error
            if stat.S_ISLNK(current.st_mode):
                _fail("scheduler_official_authority_file_replaced")
            opened = os.fstat(self.descriptor)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                _fail("scheduler_official_authority_file_replaced")
            _require_no_sidecars(self.path, self.parent_descriptor)

    def verify_stable(self) -> None:
        with self.serialized():
            self.verify_bound()
            if self._stable_identity is None:
                return
            value = os.fstat(self.descriptor)
            observed = (value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if observed != self._stable_identity:
                _fail("scheduler_official_authority_file_mutated")

    def close(self, *, validate: bool = True) -> None:
        with self.serialized():
            if self._closed:
                return
            error: BaseException | None = None
            if validate:
                try:
                    self.verify_stable() if self.readonly else self.verify_bound()
                except BaseException as caught:
                    error = caught
            self._closed = True
            try:
                self.connection.close()
            except BaseException as caught:
                error = error or caught
            finally:
                try:
                    fcntl.flock(self.descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(self.descriptor)
                    os.close(self.parent_descriptor)
            if error is not None:
                raise error


def create_secure_authority_sqlite(path: Path) -> SecureOfficialAuthoritySQLite:
    target = _target(path, create_parent=True)
    parent_descriptor = _open_parent(target.parent)
    descriptor: int | None = None
    connection: sqlite3.Connection | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(target.name, flags, 0o600, dir_fd=parent_descriptor)
        except FileExistsError as error:
            raise SchedulerOfficialAuthorityError(
                "scheduler_official_authority_file_exists"
            ) from error
        except OSError as error:
            raise SchedulerOfficialAuthorityError(
                "scheduler_official_authority_file_create_invalid"
            ) from error
        os.fchmod(descriptor, 0o600)
        _verify_descriptor(descriptor)
        _verify_parent(target.parent, parent_descriptor)
        _verify_named_inode(target, parent_descriptor, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = _connect(descriptor, readonly=False)
        handle = SecureOfficialAuthoritySQLite(
            path=target,
            parent_descriptor=parent_descriptor,
            descriptor=descriptor,
            connection=connection,
            readonly=False,
        )
        handle.verify_bound()
        return handle
    except BaseException:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
        if descriptor is not None:
            with suppress(OSError, SchedulerOfficialAuthorityError):
                _unlink_exact(target, parent_descriptor, descriptor)
            with suppress(OSError):
                os.close(descriptor)
        os.close(parent_descriptor)
        raise


def open_secure_authority_sqlite(path: Path, *, readonly: bool) -> SecureOfficialAuthoritySQLite:
    target = _target(path, create_parent=False)
    parent_descriptor = _open_parent(target.parent)
    descriptor: int | None = None
    connection: sqlite3.Connection | None = None
    try:
        try:
            before = os.stat(
                target.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(before.st_mode):
                _fail("scheduler_official_authority_file_unsafe")
            flags = os.O_RDONLY if readonly else os.O_RDWR
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
        except SchedulerOfficialAuthorityError:
            raise
        except OSError as error:
            raise SchedulerOfficialAuthorityError(
                "scheduler_official_authority_file_missing"
            ) from error
        _verify_descriptor(descriptor)
        _verify_same(before, descriptor)
        _verify_named_inode(target, parent_descriptor, descriptor)
        lock = fcntl.LOCK_SH if readonly else fcntl.LOCK_EX
        fcntl.flock(descriptor, lock | fcntl.LOCK_NB)
        connection = _connect(descriptor, readonly=readonly)
        handle = SecureOfficialAuthoritySQLite(
            path=target,
            parent_descriptor=parent_descriptor,
            descriptor=descriptor,
            connection=connection,
            readonly=readonly,
        )
        handle.verify_bound()
        return handle
    except BaseException:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        os.close(parent_descriptor)
        raise


def unlink_created_authority(handle: SecureOfficialAuthoritySQLite) -> None:
    if handle._closed:  # noqa: SLF001 - same-module lifecycle primitive
        return
    handle.verify_bound()
    os.unlink(handle.path.name, dir_fd=handle.parent_descriptor)
    handle.close(validate=False)


def _connect(descriptor: int, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro&immutable=1" if readonly else "rw"
    try:
        connection = sqlite3.connect(
            f"file:/proc/self/fd/{descriptor}?mode={mode}",
            uri=True,
            isolation_level=None,
            timeout=10.0,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        else:
            observed = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
            if observed is None or str(observed[0]).lower() != "delete":
                _fail("scheduler_official_authority_journal_mode_invalid")
            connection.execute("PRAGMA synchronous=FULL")
        return connection
    except sqlite3.Error as error:
        if "connection" in locals():
            connection.close()
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_database_open_invalid"
        ) from error


def _target(path: Path, *, create_parent: bool) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
        _fail("scheduler_official_authority_path_invalid")
    parent = path.parent
    if create_parent and not parent.exists():
        try:
            parent.mkdir(mode=0o700, parents=False)
        except OSError as error:
            raise SchedulerOfficialAuthorityError(
                "scheduler_official_authority_parent_unsafe"
            ) from error
    try:
        if parent.resolve(strict=True) != parent:
            _fail("scheduler_official_authority_parent_unsafe")
    except OSError as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_parent_unsafe"
        ) from error
    return path


def _open_parent(parent: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(parent, flags)
        _verify_parent(parent, descriptor)
        return descriptor
    except BaseException:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def _verify_parent(parent: Path, descriptor: int) -> None:
    try:
        named = parent.lstat()
        opened = os.fstat(descriptor)
    except OSError as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_parent_unsafe"
        ) from error
    if (
        stat.S_ISLNK(named.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(named.st_mode) != 0o700
        or stat.S_IMODE(opened.st_mode) != 0o700
        or named.st_uid != os.geteuid()
        or opened.st_uid != os.geteuid()
        or named.st_nlink < 2
        or opened.st_nlink < 2
        or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        _fail("scheduler_official_authority_parent_unsafe")


def _verify_descriptor(descriptor: int) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
    ):
        _fail("scheduler_official_authority_file_unsafe")


def _verify_named_inode(target: Path, parent_descriptor: int, descriptor: int) -> None:
    try:
        named = os.stat(target.name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_file_replaced"
        ) from error
    if stat.S_ISLNK(named.st_mode):
        _fail("scheduler_official_authority_file_replaced")
    _verify_same(named, descriptor)


def _verify_same(named: os.stat_result, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
        _fail("scheduler_official_authority_file_replaced")


def _require_no_sidecars(target: Path, parent_descriptor: int) -> None:
    for suffix in ("-journal", "-wal", "-shm"):
        try:
            os.stat(target.name + suffix, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise SchedulerOfficialAuthorityError(
                "scheduler_official_authority_sidecar_unsafe"
            ) from error
        _fail("scheduler_official_authority_sidecar_unsafe")


def _unlink_exact(target: Path, parent_descriptor: int, descriptor: int) -> None:
    _verify_named_inode(target, parent_descriptor, descriptor)
    os.unlink(target.name, dir_fd=parent_descriptor)


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "SecureOfficialAuthoritySQLite",
    "create_secure_authority_sqlite",
    "open_secure_authority_sqlite",
    "unlink_created_authority",
)
