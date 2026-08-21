"""Stable provider-free verification for the reviewed Node executable."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

REVIEWED_NODE_EXECUTABLE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
REVIEWED_NODE_EXECUTABLE_SIZE_BYTES = 123_438_592
_IMMUTABLE_EXECUTABLE_MODES = frozenset({0o500, 0o550, 0o555})


def require_reviewed_node_executable(path: Path, expected_sha256: str) -> Path:
    """Return one canonical immutable Node path after stable-fd verification."""

    descriptor: int | None = None
    try:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.is_symlink()
            or expected_sha256 != REVIEWED_NODE_EXECUTABLE_SHA256
        ):
            raise ValueError
        canonical = path.resolve(strict=True)
        if canonical != path:
            raise ValueError
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        opened = os.fstat(descriptor)
        identity = _identity(opened)
        if (
            identity != _identity(before)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(opened.st_mode) not in _IMMUTABLE_EXECUTABLE_MODES
            or opened.st_nlink != 1
            or opened.st_size != REVIEWED_NODE_EXECUTABLE_SIZE_BYTES
            or not os.access(path, os.X_OK)
        ):
            raise ValueError
        digest = hashlib.sha256()
        consumed = 0
        while consumed < REVIEWED_NODE_EXECUTABLE_SIZE_BYTES:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, REVIEWED_NODE_EXECUTABLE_SIZE_BYTES - consumed),
            )
            if not chunk:
                raise ValueError
            digest.update(chunk)
            consumed += len(chunk)
        if os.read(descriptor, 1) or digest.hexdigest() != expected_sha256:
            raise ValueError
        if identity != _identity(os.fstat(descriptor)) or identity != _identity(path.lstat()):
            raise ValueError
        return canonical
    except (OSError, ValueError):
        raise ValueError("reviewed_node_executable_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = (
    "REVIEWED_NODE_EXECUTABLE_SHA256",
    "REVIEWED_NODE_EXECUTABLE_SIZE_BYTES",
    "require_reviewed_node_executable",
)
