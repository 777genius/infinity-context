"""POSIX descriptor-bound reads for private subscription bridge secrets."""

from __future__ import annotations

import hmac
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_READ_CHUNK_BYTES = 4_096
_UNAVAILABLE = "bridge_secure_secret_file_unavailable"

_DirectoryIdentity = tuple[int, int, int, int, int, int]
_FileSnapshot = tuple[int, int, int, int, int, int, int, int, int]


class SecureSecretFileError(RuntimeError):
    """Stable non-secret failure for the POSIX private-file boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str = _UNAVAILABLE) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class SecureSecretFileSnapshot:
    """Safe identity evidence captured around one exact descriptor read."""

    directory_chain: tuple[_DirectoryIdentity, ...]
    file: _FileSnapshot

    def __repr__(self) -> str:
        return "SecureSecretFileSnapshot(identity=<redacted>)"


@final
class SecureSecretFileContents:
    """Owned mutable bytes which are zeroed when the lease is closed."""

    __slots__ = ("_closed", "_value", "snapshot")

    def __init__(self, value: bytearray, snapshot: SecureSecretFileSnapshot) -> None:
        if type(value) is not bytearray or type(snapshot) is not SecureSecretFileSnapshot:
            raise SecureSecretFileError() from None
        self._value = value
        self.snapshot = snapshot
        self._closed = False

    @property
    def value(self) -> bytearray:
        if self._closed:
            raise SecureSecretFileError() from None
        return self._value

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _wipe(self._value)

    def __enter__(self) -> SecureSecretFileContents:
        if self._closed:
            raise SecureSecretFileError() from None
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __copy__(self) -> None:
        raise TypeError("secure secret file contents are noncopyable")

    def __deepcopy__(self, _memo: object) -> None:
        raise TypeError("secure secret file contents are noncopyable")

    def __reduce__(self) -> None:
        raise TypeError("secure secret file contents are nonserializable")

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def __repr__(self) -> str:
        return f"SecureSecretFileContents(closed={self._closed!r}, value=<redacted>)"


@final
class SecureSecretFileReader:
    """Read one canonical file beneath an explicit euid-private root.

    Every path component is opened relative to a held parent descriptor with
    ``O_NOFOLLOW``. Components at and below ``private_root`` must be euid-owned
    ``0700`` directories. Earlier absolute-path components must be root/euid owned
    and non-writable by other users (a root-owned sticky directory such as ``/tmp``
    is allowed).
    """

    __slots__ = ("_maximum_bytes", "_path", "_private_root")

    def __init__(
        self,
        *,
        private_root: Path,
        path: Path,
        maximum_bytes: int,
    ) -> None:
        if (
            not isinstance(private_root, Path)
            or not isinstance(path, Path)
            or type(maximum_bytes) is not int
            or not 1 <= maximum_bytes <= 64 * 1024 * 1024
        ):
            raise SecureSecretFileError() from None
        self._private_root = private_root
        self._path = path
        self._maximum_bytes = maximum_bytes

    def read(self) -> SecureSecretFileContents:
        """Return a mutable, caller-owned snapshot or one redacted failure."""

        result: SecureSecretFileContents | None = None
        failed = False
        try:
            result = self._read_bound()
        except Exception:
            failed = True
        if failed or result is None:
            raise SecureSecretFileError() from None
        return result

    def __repr__(self) -> str:
        return (
            f"SecureSecretFileReader(maximum_bytes={self._maximum_bytes!r}, "
            "path=<redacted>, private_root=<redacted>)"
        )

    def _read_bound(self) -> SecureSecretFileContents:
        private_root, path = _canonical_layout(self._private_root, self._path)
        directory_flags, file_flags = _open_flags()
        root_fd: int | None = None
        secret_fd: int | None = None
        directory_fds: list[int] = []
        bindings: list[_DirectoryBinding] = []
        value = bytearray()
        verification = bytearray()
        completed = False
        try:
            root_before = os.stat("/", follow_symlinks=False)
            root_fd = os.open("/", directory_flags)
            root_opened = os.fstat(root_fd)
            root_after = os.stat("/", follow_symlinks=False)
            root_identity = _directory_identity(root_opened)
            if (
                _directory_identity(root_before) != root_identity
                or _directory_identity(root_after) != root_identity
                or not _protected_ancestor(root_opened)
            ):
                raise _InvalidSecretFile
            bindings.append(_DirectoryBinding(None, root_fd, "", root_identity, False))

            current_fd = root_fd
            root_component_count = len(private_root.parts) - 1
            for offset, component in enumerate(path.parent.parts[1:]):
                before = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                child_fd = os.open(component, directory_flags, dir_fd=current_fd)
                directory_fds.append(child_fd)
                opened = os.fstat(child_fd)
                after = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                identity = _directory_identity(opened)
                is_private = offset >= root_component_count - 1
                if (
                    _directory_identity(before) != identity
                    or _directory_identity(after) != identity
                    or not _valid_directory(opened, private=is_private)
                ):
                    raise _InvalidSecretFile
                bindings.append(
                    _DirectoryBinding(current_fd, child_fd, component, identity, is_private)
                )
                current_fd = child_fd

            before = os.stat(path.name, dir_fd=current_fd, follow_symlinks=False)
            secret_fd = os.open(path.name, file_flags, dir_fd=current_fd)
            opened = os.fstat(secret_fd)
            after_open = os.stat(path.name, dir_fd=current_fd, follow_symlinks=False)
            opened_snapshot = _file_snapshot(opened)
            if (
                _file_snapshot(before) != opened_snapshot
                or _file_snapshot(after_open) != opened_snapshot
                or not _private_file(opened)
                or not 1 <= opened.st_size <= self._maximum_bytes
            ):
                raise _InvalidSecretFile

            _read_bounded(secret_fd, value, maximum_bytes=self._maximum_bytes)
            first_final = os.fstat(secret_fd)
            if len(value) != opened.st_size or len(value) > self._maximum_bytes:
                raise _InvalidSecretFile
            os.lseek(secret_fd, 0, os.SEEK_SET)
            _read_bounded(secret_fd, verification, maximum_bytes=self._maximum_bytes)
            final = os.fstat(secret_fd)
            after = os.stat(path.name, dir_fd=current_fd, follow_symlinks=False)
            if (
                _file_snapshot(first_final) != opened_snapshot
                or _file_snapshot(final) != opened_snapshot
                or _file_snapshot(after) != opened_snapshot
                or not _private_file(final)
                or not _private_file(after)
                or len(value) != opened.st_size
                or not hmac.compare_digest(value, verification)
                or not 1 <= len(value) <= self._maximum_bytes
            ):
                raise _InvalidSecretFile
            _revalidate_directories(bindings)
            snapshot = SecureSecretFileSnapshot(
                directory_chain=tuple(item.identity for item in bindings),
                file=opened_snapshot,
            )
            result = SecureSecretFileContents(value, snapshot)
            completed = True
            return result
        finally:
            _wipe(verification)
            if not completed:
                _wipe(value)
            if secret_fd is not None:
                with suppress(OSError):
                    os.close(secret_fd)
            for descriptor in reversed(directory_fds):
                with suppress(OSError):
                    os.close(descriptor)
            if root_fd is not None:
                with suppress(OSError):
                    os.close(root_fd)


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int | None
    fd: int
    name: str
    identity: _DirectoryIdentity
    private: bool


class _InvalidSecretFile(Exception):
    pass


def _read_bounded(descriptor: int, target: bytearray, *, maximum_bytes: int) -> None:
    while len(target) <= maximum_bytes:
        requested = min(_READ_CHUNK_BYTES, maximum_bytes + 1 - len(target))
        chunk = os.read(descriptor, requested)
        if type(chunk) is not bytes or len(chunk) > requested:
            raise _InvalidSecretFile
        if not chunk:
            break
        target.extend(chunk)


def _canonical_layout(private_root: Path, path: Path) -> tuple[Path, Path]:
    if (
        os.name != "posix"
        or not private_root.is_absolute()
        or not path.is_absolute()
        or private_root == Path("/")
        or path.name in {"", ".", ".."}
    ):
        raise _InvalidSecretFile
    resolved_root = private_root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    if resolved_root != private_root or resolved_path != path:
        raise _InvalidSecretFile
    try:
        relative = path.relative_to(private_root)
    except ValueError:
        raise _InvalidSecretFile from None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise _InvalidSecretFile
    return resolved_root, resolved_path


def _open_flags() -> tuple[int, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    if nofollow is None or directory is None or cloexec is None:
        raise _InvalidSecretFile
    return (
        os.O_RDONLY | directory | cloexec | nofollow,
        os.O_RDONLY | cloexec | nofollow,
    )


def _revalidate_directories(bindings: list[_DirectoryBinding]) -> None:
    for binding in bindings:
        opened = os.fstat(binding.fd)
        if binding.parent_fd is None:
            current = os.stat("/", follow_symlinks=False)
        else:
            current = os.stat(
                binding.name,
                dir_fd=binding.parent_fd,
                follow_symlinks=False,
            )
        if (
            _directory_identity(opened) != binding.identity
            or _directory_identity(current) != binding.identity
            or not _valid_directory(opened, private=binding.private)
            or not _valid_directory(current, private=binding.private)
        ):
            raise _InvalidSecretFile


def _valid_directory(value: os.stat_result, *, private: bool) -> bool:
    return _private_directory(value) if private else _protected_ancestor(value)


def _private_directory(value: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and value.st_uid == os.geteuid()
        and stat.S_IMODE(value.st_mode) == _PRIVATE_DIRECTORY_MODE
    )


def _protected_ancestor(value: os.stat_result) -> bool:
    mode = stat.S_IMODE(value.st_mode)
    owned = value.st_uid in {0, os.geteuid()}
    writable_by_others = bool(mode & 0o022)
    root_sticky = value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
    return stat.S_ISDIR(value.st_mode) and owned and (not writable_by_others or root_sticky)


def _private_file(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == _PRIVATE_FILE_MODE
    )


def _directory_identity(value: os.stat_result) -> _DirectoryIdentity:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
    )


def _file_snapshot(value: os.stat_result) -> _FileSnapshot:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _wipe(value: bytearray) -> None:
    value[:] = b"\0" * len(value)
    value.clear()


__all__ = (
    "SecureSecretFileContents",
    "SecureSecretFileError",
    "SecureSecretFileReader",
    "SecureSecretFileSnapshot",
)
