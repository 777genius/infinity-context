"""Private filesystem primitives shared by durable adapter orchestration."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path


def private_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("adapter_configuration_invalid")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def read_private_json(path: Path, *, maximum_bytes: int, require_read_only: bool = False):
    raw = read_private_bytes(
        path,
        maximum_bytes=maximum_bytes,
        require_read_only=require_read_only,
    )
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("private_json_invalid") from None


def read_private_bytes(path: Path, *, maximum_bytes: int, require_read_only: bool = False) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("adapter_configuration_invalid")
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO) or (require_read_only and mode & stat.S_IWUSR):
        raise ValueError("adapter_configuration_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= maximum_bytes:
        raise ValueError("adapter_configuration_invalid")
    return raw


def atomic_private_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".result-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


__all__ = ("atomic_private_write", "private_directory", "read_private_bytes", "read_private_json")
