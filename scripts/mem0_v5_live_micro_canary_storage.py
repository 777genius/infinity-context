"""Private locked atomic-file primitives for the live Mem0 v5 micro-canary."""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import final


@final
class LockedPrivateRoot:
    """Serialize one lifecycle and expose bounded atomic files under its private root."""

    __slots__ = ("_dirfd", "_root", "_root_code")

    def __init__(self, root: Path, *, root_code: str) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or not root_code:
            raise ValueError(root_code)
        self._root = root
        self._root_code = root_code
        self._dirfd: int | None = None

    def __enter__(self) -> LockedPrivateRoot:
        if self._dirfd is not None:
            raise ValueError("mem0_v5_live_private_root_session_replayed")
        self._dirfd = _open_private_root(self._root, self._root_code)
        try:
            fcntl.flock(self._dirfd, fcntl.LOCK_EX)
        except OSError:
            os.close(self._dirfd)
            self._dirfd = None
            raise ValueError("mem0_v5_live_private_root_lock_failed") from None
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        descriptor = self._dirfd
        self._dirfd = None
        if descriptor is not None:
            with suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def read_optional(self, name: str, *, maximum_bytes: int, code: str) -> bytes | None:
        return _read_optional_private_file(
            self._required_dirfd(),
            name,
            maximum_bytes=maximum_bytes,
            code=code,
        )

    def atomic_replace(
        self,
        name: str,
        rendered: bytes,
        *,
        boundary: Callable[[str], None] | None,
        prefix: str,
    ) -> None:
        _atomic_replace(
            self._required_dirfd(),
            name,
            rendered,
            boundary=boundary,
            prefix=prefix,
        )

    def _required_dirfd(self) -> int:
        if self._dirfd is None:
            raise ValueError("mem0_v5_live_private_root_session_inactive")
        return self._dirfd


def _open_private_root(path: Path, code: str) -> int:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if (
            path.resolve(strict=True) != path
            or path.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o700
        ):
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError
        return descriptor
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise ValueError(code) from None


def _read_optional_private_file(
    dirfd: int,
    name: str,
    *,
    maximum_bytes: int,
    code: str,
) -> bytes | None:
    descriptor: int | None = None
    try:
        try:
            before = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=dirfd,
        )
        opened = os.fstat(descriptor)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= maximum_bytes
            or identity != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            raise OSError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise OSError
        final = os.fstat(descriptor)
        if identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise OSError
        return b"".join(chunks)
    except OSError:
        raise ValueError(code) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_replace(
    dirfd: int,
    name: str,
    rendered: bytes,
    *,
    boundary: Callable[[str], None] | None,
    prefix: str,
) -> None:
    temporary = f".{name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
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
        _boundary(boundary, f"{prefix}_temp_fsynced")
        os.replace(temporary, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        _boundary(boundary, f"{prefix}_published")
        os.fsync(dirfd)
        _boundary(boundary, f"{prefix}_directory_fsynced")
    except OSError:
        raise ValueError(f"mem0_v5_live_{prefix}_write_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dirfd)


def _boundary(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)


__all__ = ("LockedPrivateRoot",)
