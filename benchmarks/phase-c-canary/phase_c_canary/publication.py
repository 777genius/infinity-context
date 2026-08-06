from __future__ import annotations

import ctypes
import errno
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from .hashing import sha256_bytes


class PublicationError(RuntimeError):
    pass


FaultHook = Callable[[str], None]


class RenameNoReplacePort:
    def rename(self, source: Path, destination: Path) -> None:
        raise NotImplementedError


class LinuxRenameNoReplace(RenameNoReplacePort):
    """Narrow Linux renameat2(RENAME_NOREPLACE) adapter."""

    _AT_FDCWD = -100
    _RENAME_NOREPLACE = 1

    def rename(self, source: Path, destination: Path) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise PublicationError("renameat2 is unavailable; publication fails closed")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            self._AT_FDCWD,
            os.fsencode(source),
            self._AT_FDCWD,
            os.fsencode(destination),
            self._RENAME_NOREPLACE,
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise PublicationError("publication destination already exists")
        if error in (errno.ENOSYS, errno.EINVAL):
            raise PublicationError("atomic no-replace publication is unsupported")
        raise PublicationError(f"atomic publication failed with errno {error}")


class AtomicArtifactPublisher:
    """Publish only a complete, self-hashing directory.

    Staging and destination must share a filesystem. Existing destinations are
    never replaced. This intentionally avoids pretending that cross-device
    rename is atomic.
    """

    def __init__(self, rename: RenameNoReplacePort | None = None) -> None:
        self._rename = rename or LinuxRenameNoReplace()

    def publish(
        self,
        *,
        staging: Path,
        destination: Path,
        files: Mapping[str, bytes],
        fault: FaultHook | None = None,
    ) -> Path:
        if staging.parent.stat().st_dev != destination.parent.stat().st_dev:
            raise PublicationError("staging and destination are on different filesystems")
        if staging.exists() or destination.exists():
            raise PublicationError("staging or destination already exists")
        staging.mkdir(mode=0o700)
        try:
            manifest_files: list[dict[str, object]] = []
            for relative, content in sorted(files.items()):
                target = _contained(staging, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                _durable_write(target, content)
                manifest_files.append(
                    {"path": relative, "size": len(content), "sha256": sha256_bytes(content)}
                )
            if fault:
                fault("before_manifest")
            manifest = json.dumps(
                {"schema_version": 1, "files": manifest_files},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            _durable_write(staging / "manifest.json", manifest)
            _fsync_tree_directories(staging)
            if fault:
                fault("after_manifest")
            self._rename.rename(staging, destination)
            _fsync_directory(destination.parent)
            if fault:
                fault("after_publication")
            return destination
        except Exception:
            # A post-rename fault leaves a complete published artifact. All
            # earlier faults leave only non-authoritative staging residue.
            raise


def _contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or relative == "manifest.json":
        raise PublicationError(f"unsafe artifact path: {relative}")
    return candidate


def _durable_write(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = [path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]
    directories.append(root)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        _fsync_directory(directory)
