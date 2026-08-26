"""Fail-closed local storage primitives for managed-v5 recovery."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    canonical_json,
)

MAX_JOURNAL_BYTES = 128 * 1024 * 1024
ROOT_MODE = 0o700
FILE_MODE = 0o600


class ManagedV5RecoveryStorageError(RuntimeError):
    pass


def require_private_root(path: Path) -> None:
    try:
        metadata = path.lstat()
        valid = (
            path.is_absolute()
            and path.resolve(strict=True) == path
            and not path.is_symlink()
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and stat.S_IMODE(metadata.st_mode) == ROOT_MODE
        )
    except OSError:
        valid = False
    if not valid:
        _fail("managed_v5_live_recovery_root_invalid")


def acquire_session_lock(root: Path, journal_name: str) -> int:
    name = f".{journal_name}.lock"
    if len(name.encode("utf-8")) > 240:
        _fail("managed_v5_live_recovery_journal_lock_invalid")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    descriptor = None
    try:
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            FILE_MODE,
            dir_fd=dirfd,
        )
        if not safe_private_file(os.fstat(descriptor)):
            raise OSError
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        _fail("managed_v5_live_recovery_journal_locked")
    finally:
        os.close(dirfd)


def read_private_file(path: Path) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        if (
            not safe_private_file(opened)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            or not 1 <= opened.st_size <= MAX_JOURNAL_BYTES
        ):
            raise OSError
        raw = bytearray()
        while len(raw) <= MAX_JOURNAL_BYTES:
            chunk = os.read(descriptor, min(65_536, MAX_JOURNAL_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) != opened.st_size or len(raw) > MAX_JOURNAL_BYTES:
            raise OSError
        return bytes(raw)
    except OSError:
        _fail("managed_v5_live_recovery_journal_read_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def atomic_write_private_json(root: Path, path: Path, payload: dict[str, object]) -> None:
    rendered = canonical_json(payload)
    if not 1 <= len(rendered) <= MAX_JOURNAL_BYTES:
        _fail("managed_v5_live_recovery_journal_too_large")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor = None
    try:
        existing = optional_lstat(path)
        if existing is not None and not safe_private_file(existing):
            raise OSError
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            FILE_MODE,
            dir_fd=dirfd,
        )
        view = memoryview(rendered)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path.name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)
    except OSError:
        _fail("managed_v5_live_recovery_journal_write_failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dirfd)
        os.close(dirfd)


def safe_private_file(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == FILE_MODE
    )


def optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _fail(code: str) -> None:
    raise ManagedV5RecoveryStorageError(code)


__all__ = (
    "ManagedV5RecoveryStorageError",
    "acquire_session_lock",
    "atomic_write_private_json",
    "read_private_file",
    "require_private_root",
)
