"""Race-resistant file operations for the subscription bridge process launcher."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from .json_boundary import BridgeJsonError, canonical_json_bytes, strict_canonical_json_object
from .process_contracts import BridgeProcessError


@dataclass(slots=True)
class StateLock:
    lifecycle_root: Path
    descriptor: int

    @classmethod
    def acquire(cls, state_root: Path, lifecycle_name: str, *, create: bool) -> StateLock:
        lifecycle = state_root / lifecycle_name
        if create:
            try:
                lifecycle.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise BridgeProcessError("bridge_process_state_already_initialized") from exc
            except OSError as exc:
                raise BridgeProcessError("bridge_process_lifecycle_create_failed") from exc
        verify_private_directory(lifecycle, "lifecycle_root")
        lock_path = lifecycle / "launcher.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        previous_umask = os.umask(0o077)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise BridgeProcessError("bridge_process_lock_open_failed") from exc
        finally:
            os.umask(previous_umask)
        try:
            _verify_private_descriptor(descriptor, label="lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise BridgeProcessError("bridge_process_launcher_already_active") from exc
        except BaseException:
            os.close(descriptor)
            raise
        return cls(lifecycle_root=lifecycle, descriptor=descriptor)

    def close(self) -> None:
        if self.descriptor < 0:
            return
        descriptor, self.descriptor = self.descriptor, -1
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def private_directory_identity(path: Path, label: str) -> str:
    value = verify_private_directory(path, label)
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "device": value.st_dev,
                "inode": value.st_ino,
                "mode": stat.S_IMODE(value.st_mode),
                "owner": value.st_uid,
                "path": str(path),
            }
        )
    ).hexdigest()


def verify_private_directory(path: Path, label: str) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as exc:
        raise BridgeProcessError(f"bridge_process_{label}_unsafe") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail(f"bridge_process_{label}_unsafe")
    return value


def verify_private_file(path: Path, label: str) -> None:
    descriptor = _open_private_file(path, label)
    os.close(descriptor)


def read_private_file(path: Path, label: str, *, maximum_bytes: int) -> bytes:
    descriptor = _open_private_file(path, label)
    try:
        return _read_descriptor(descriptor, maximum_bytes=maximum_bytes, label=label)
    finally:
        os.close(descriptor)


def sha256_private_file(path: Path, label: str, *, maximum_bytes: int) -> str:
    descriptor = _open_private_file(path, label)
    try:
        return _sha256_descriptor(descriptor, maximum_bytes=maximum_bytes, label=label)
    finally:
        os.close(descriptor)


def verify_public_file(
    path: Path,
    expected_sha256: str,
    *,
    executable: bool,
    maximum_bytes: int,
    label: str,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BridgeProcessError(f"bridge_process_{label}_unsafe") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_mode & 0o022) != 0
            or (executable and (opened.st_mode & 0o111) == 0)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            _fail(f"bridge_process_{label}_unsafe")
        actual = _sha256_descriptor(descriptor, maximum_bytes=maximum_bytes, label=label)
        if not hmac.compare_digest(actual, expected_sha256):
            _fail(f"bridge_process_{label}_sha256_mismatch")
    finally:
        os.close(descriptor)


def read_private_json(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    raw = read_private_file(path, "metadata", maximum_bytes=maximum_bytes)
    try:
        return strict_canonical_json_object(raw, maximum_bytes=maximum_bytes)
    except BridgeJsonError as exc:
        raise BridgeProcessError("bridge_process_metadata_invalid") from exc


def write_private_json_once(path: Path, payload: object, *, maximum_bytes: int) -> None:
    _write_private_bytes(
        path, canonical_json_bytes(payload), replace=False, maximum_bytes=maximum_bytes
    )


def write_private_json_replace(path: Path, payload: object, *, maximum_bytes: int) -> None:
    _write_private_bytes(
        path, canonical_json_bytes(payload), replace=True, maximum_bytes=maximum_bytes
    )


def bounded_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read(maximum_bytes + 1)
    except OSError as exc:
        raise BridgeProcessError("bridge_process_proc_read_failed") from exc
    if not raw or len(raw) > maximum_bytes:
        _fail("bridge_process_proc_read_invalid")
    return raw


def _open_private_file(path: Path, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BridgeProcessError(f"bridge_process_{label}_unsafe") from exc
    try:
        _verify_private_descriptor(descriptor, label=label)
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            _fail(f"bridge_process_{label}_replaced")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_private_descriptor(descriptor: int, *, label: str) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        _fail(f"bridge_process_{label}_unsafe")


def _write_private_bytes(path: Path, raw: bytes, *, replace: bool, maximum_bytes: int) -> None:
    if not raw or len(raw) > maximum_bytes:
        _fail("bridge_process_metadata_size_invalid")
    verify_private_directory(path.parent, "metadata_parent")
    destination = path
    if replace:
        destination = path.parent / f".{path.name}.{token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError as exc:
        raise BridgeProcessError("bridge_process_metadata_create_failed") from exc
    finally:
        os.umask(previous_umask)
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
        _verify_private_descriptor(descriptor, label="metadata")
    except BaseException:
        with suppress(OSError):
            destination.unlink()
        raise
    finally:
        os.close(descriptor)
    if replace:
        try:
            os.replace(destination, path)
        except OSError as exc:
            with suppress(OSError):
                destination.unlink()
            raise BridgeProcessError("bridge_process_metadata_replace_failed") from exc
    _fsync_directory(path.parent)


def _sha256_descriptor(descriptor: int, *, maximum_bytes: int, label: str) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total))
        if not chunk:
            return digest.hexdigest()
        total += len(chunk)
        if total > maximum_bytes:
            _fail(f"bridge_process_{label}_size_invalid")
        digest.update(chunk)


def _read_descriptor(descriptor: int, *, maximum_bytes: int, label: str) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - total))
        if not chunk:
            raw = b"".join(chunks)
            if not raw:
                _fail(f"bridge_process_{label}_empty")
            return raw
        total += len(chunk)
        if total > maximum_bytes:
            _fail(f"bridge_process_{label}_size_invalid")
        chunks.append(chunk)


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        try:
            written = os.write(descriptor, raw[offset:])
        except OSError as exc:
            raise BridgeProcessError("bridge_process_metadata_write_failed") from exc
        if written <= 0:
            _fail("bridge_process_metadata_write_failed")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BridgeProcessError("bridge_process_metadata_fsync_failed") from exc


def _fail(code: str) -> None:
    raise BridgeProcessError(code)


__all__ = (
    "StateLock",
    "bounded_read",
    "private_directory_identity",
    "read_private_file",
    "read_private_json",
    "sha256_private_file",
    "verify_private_directory",
    "verify_private_file",
    "verify_public_file",
    "write_private_json_once",
    "write_private_json_replace",
)
