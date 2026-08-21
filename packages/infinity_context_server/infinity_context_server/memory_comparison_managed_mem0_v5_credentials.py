"""Private, read-once filesystem credentials for the managed Mem0 v5 lane."""

from __future__ import annotations

import hmac
import os
import stat
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_secret_validation import (
    is_bounded_text_secret,
)

_MIN_BYTES = 32
_MAX_BYTES = 4_096
_UNAVAILABLE = "managed_mem0_v5_credential_unavailable"
_REPLAYED = "managed_mem0_v5_credential_replayed"
_NOT_DISTINCT = "managed_mem0_v5_credential_roles_not_distinct"


class ManagedMem0V5CredentialError(RuntimeError):
    """Stable fail-closed error for local credential loading and consumption."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5CredentialPaths:
    bearer_token: Path
    evidence_key: Path
    receipt_secret: Path
    checkpoint_signing_key: Path
    checkpoint_head_key: Path

    def __post_init__(self) -> None:
        paths = self.values()
        if any(not isinstance(path, Path) or not path.is_absolute() for path in paths):
            _fail(_UNAVAILABLE)
        if len(set(paths)) != len(paths):
            _fail(_NOT_DISTINCT)

    def values(self) -> tuple[Path, ...]:
        return (
            self.bearer_token,
            self.evidence_key,
            self.receipt_secret,
            self.checkpoint_signing_key,
            self.checkpoint_head_key,
        )


class _NonExportable:
    __slots__ = ()

    def __copy__(self) -> None:
        raise TypeError("managed Mem0 v5 credentials are noncopyable")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("managed Mem0 v5 credentials are noncopyable")

    def __reduce__(self) -> None:
        raise TypeError("managed Mem0 v5 credentials are nonserializable")

    def __reduce_ex__(self, protocol: int) -> None:
        del protocol
        raise TypeError("managed Mem0 v5 credentials are nonserializable")


class _ReadOnceBytes(_NonExportable):
    __slots__ = ("_consumed", "_lock", "_value")

    def __init__(self, value: bytearray) -> None:
        self._lock = threading.Lock()
        self._value: bytearray | None = bytearray(value)
        self._consumed = False

    def consume(self) -> bytes:
        with self._lock:
            value = self._take()
            try:
                return bytes(value)
            finally:
                _wipe(value)

    def validate(self) -> None:
        """Validate availability and production byte bounds without consuming."""

        with self._lock:
            value = self._value
            if self._consumed or value is None or not _MIN_BYTES <= len(value) <= _MAX_BYTES:
                _fail(_UNAVAILABLE)

    def _take(self) -> bytearray:
        if self._consumed or self._value is None:
            _fail(_REPLAYED)
        self._consumed = True
        value = self._value
        self._value = None
        return value

    def close(self) -> None:
        with self._lock:
            value = self._value
            self._value = None
            self._consumed = True
            if value is not None:
                _wipe(value)

    def __enter__(self):
        with self._lock:
            if self._consumed or self._value is None:
                _fail(_REPLAYED)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(consumed={self._consumed!r})"


class _ReadOnceText(_ReadOnceBytes):
    __slots__ = ()

    def consume(self) -> str:
        with self._lock:
            value = self._take()
            try:
                text = bytes(value).decode("utf-8")
            except UnicodeDecodeError:
                _fail(_UNAVAILABLE)
            finally:
                _wipe(value)
        if not is_bounded_text_secret(text, minimum=_MIN_BYTES, maximum=_MAX_BYTES):
            _fail(_UNAVAILABLE)
        return text

    def validate(self) -> None:
        """Validate UTF-8/token syntax without taking the one-shot value."""

        with self._lock:
            value = self._value
            if self._consumed or value is None or not _MIN_BYTES <= len(value) <= _MAX_BYTES:
                _fail(_UNAVAILABLE)
            try:
                text = bytes(value).decode("utf-8")
            except UnicodeDecodeError:
                _fail(_UNAVAILABLE)
            if not is_bounded_text_secret(text, minimum=_MIN_BYTES, maximum=_MAX_BYTES):
                _fail(_UNAVAILABLE)


@final
class ReadOnceManagedMem0V5BearerToken(_ReadOnceText):
    """Bearer capability compatible with ManagedMem0V5BearerCapability."""


@final
class ReadOnceManagedMem0V5EvidenceKey(_ReadOnceBytes):
    """Evidence capability compatible with ManagedMem0V5EvidenceKeyCapability."""


@final
class ReadOnceManagedMem0V5ReceiptSecret(_ReadOnceText):
    """Text secret consumed by Mem0V5RuntimeReceiptVerifier composition."""


@final
class ReadOnceManagedMem0V5CheckpointSigningKey(_ReadOnceBytes):
    """HMAC key consumed by checkpoint signer composition."""


@final
class ReadOnceManagedMem0V5CheckpointHeadKey(_ReadOnceBytes):
    """HMAC key consumed by SQLite checkpoint-head composition."""


@final
class ManagedMem0V5CredentialCapabilities(_NonExportable):
    """Role-separated capabilities loaded atomically once per process."""

    __slots__ = (
        "_closed",
        "_lock",
        "bearer_token",
        "checkpoint_head_key",
        "checkpoint_signing_key",
        "evidence_key",
        "receipt_secret",
    )

    def __init__(self, values: tuple[bytearray, ...]) -> None:
        self._lock = threading.Lock()
        self._closed = False
        created: list[_ReadOnceBytes] = []
        try:
            self.bearer_token = ReadOnceManagedMem0V5BearerToken(values[0])
            created.append(self.bearer_token)
            self.evidence_key = ReadOnceManagedMem0V5EvidenceKey(values[1])
            created.append(self.evidence_key)
            self.receipt_secret = ReadOnceManagedMem0V5ReceiptSecret(values[2])
            created.append(self.receipt_secret)
            self.checkpoint_signing_key = ReadOnceManagedMem0V5CheckpointSigningKey(values[3])
            created.append(self.checkpoint_signing_key)
            self.checkpoint_head_key = ReadOnceManagedMem0V5CheckpointHeadKey(values[4])
        except Exception:
            for capability in created:
                capability.close()
            self._closed = True
            raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for name in (
                "bearer_token",
                "evidence_key",
                "receipt_secret",
                "checkpoint_signing_key",
                "checkpoint_head_key",
            ):
                capability = getattr(self, name, None)
                if capability is not None:
                    capability.close()

    def __enter__(self):
        with self._lock:
            if self._closed:
                _fail(_REPLAYED)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(roles=5, closed={self._closed!r})"


@final
@dataclass(slots=True, repr=False)
class ManagedMem0V5PrivateSecretSnapshot:
    value: bytearray
    identity: tuple[int, int]


_LoadedSecret = ManagedMem0V5PrivateSecretSnapshot


def load_managed_mem0_v5_credentials(
    paths: ManagedMem0V5CredentialPaths,
) -> ManagedMem0V5CredentialCapabilities:
    """Load five private files and return role-specific one-shot capabilities."""

    if type(paths) is not ManagedMem0V5CredentialPaths:
        _fail(_UNAVAILABLE)
    loaded: list[ManagedMem0V5PrivateSecretSnapshot] = []
    try:
        for path in paths.values():
            loaded.append(_read_private_secret(path))
        if len({item.identity for item in loaded}) != len(loaded):
            _fail(_NOT_DISTINCT)
        for index, left in enumerate(loaded):
            for right in loaded[index + 1 :]:
                if hmac.compare_digest(left.value, right.value):
                    _fail(_NOT_DISTINCT)
        _validate_text_secret(loaded[0].value)
        _validate_text_secret(loaded[2].value)
        return ManagedMem0V5CredentialCapabilities(tuple(item.value for item in loaded))
    finally:
        for item in loaded:
            _wipe(item.value)


def _read_private_secret(path: Path) -> ManagedMem0V5PrivateSecretSnapshot:
    directory_fd: int | None = None
    secret_fd: int | None = None
    value = bytearray()
    completed = False
    try:
        parent_before = os.lstat(path.parent)
        if not _private_directory(parent_before):
            _fail(_UNAVAILABLE)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            _fail(_UNAVAILABLE)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | nofollow)
        parent_opened = os.fstat(directory_fd)
        if _identity(parent_before) != _identity(parent_opened):
            _fail(_UNAVAILABLE)
        before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        secret_fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | nofollow, dir_fd=directory_fd)
        opened = os.fstat(secret_fd)
        if _identity(before) != _identity(opened) or not _private_file(opened):
            _fail(_UNAVAILABLE)
        while len(value) <= _MAX_BYTES:
            chunk = os.read(secret_fd, min(1_024, _MAX_BYTES + 1 - len(value)))
            if not chunk:
                break
            value.extend(chunk)
        after = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        parent_after = os.lstat(path.parent)
        opened_after = os.fstat(secret_fd)
        if (
            _snapshot(opened) != _snapshot(after)
            or _snapshot(opened) != _snapshot(opened_after)
            or _identity(parent_opened) != _identity(parent_after)
            or not _private_directory(parent_after)
            or not _private_file(after)
            or not _private_file(opened_after)
            or len(value) != opened.st_size
            or not _MIN_BYTES <= len(value) <= _MAX_BYTES
        ):
            _fail(_UNAVAILABLE)
        result = ManagedMem0V5PrivateSecretSnapshot(value, _identity(opened))
        completed = True
        return result
    except ManagedMem0V5CredentialError:
        raise
    except (OSError, ValueError):
        raise ManagedMem0V5CredentialError(_UNAVAILABLE) from None
    finally:
        if not completed:
            _wipe(value)
        if secret_fd is not None:
            with suppress(OSError):
                os.close(secret_fd)
        if directory_fd is not None:
            with suppress(OSError):
                os.close(directory_fd)


def read_managed_mem0_v5_private_secret(path: Path) -> ManagedMem0V5PrivateSecretSnapshot:
    """Read one immutable private secret with inode and metadata race checks."""

    return _read_private_secret(path)


def _validate_text_secret(value: bytearray) -> None:
    try:
        text = bytes(value).decode("utf-8")
    except UnicodeDecodeError:
        _fail(_UNAVAILABLE)
    if not is_bounded_text_secret(text, minimum=_MIN_BYTES, maximum=_MAX_BYTES):
        _fail(_UNAVAILABLE)


def _private_directory(value: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(value.st_mode)
        and value.st_uid == os.geteuid()
        and stat.S_IMODE(value.st_mode) == 0o700
    )


def _private_file(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and value.st_uid == os.geteuid()
        and value.st_nlink == 1
        and stat.S_IMODE(value.st_mode) == 0o600
    )


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _snapshot(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _wipe(value: bytearray) -> None:
    value[:] = b"\x00" * len(value)
    value.clear()


def wipe_managed_mem0_v5_private_secret(value: bytearray) -> None:
    """Zero and release mutable secret material owned by the caller."""

    if type(value) is not bytearray:
        _fail(_UNAVAILABLE)
    _wipe(value)


def _fail(code: str) -> None:
    raise ManagedMem0V5CredentialError(code)


__all__ = [
    "ManagedMem0V5CredentialCapabilities",
    "ManagedMem0V5CredentialError",
    "ManagedMem0V5CredentialPaths",
    "ManagedMem0V5PrivateSecretSnapshot",
    "ReadOnceManagedMem0V5BearerToken",
    "ReadOnceManagedMem0V5CheckpointHeadKey",
    "ReadOnceManagedMem0V5CheckpointSigningKey",
    "ReadOnceManagedMem0V5EvidenceKey",
    "ReadOnceManagedMem0V5ReceiptSecret",
    "load_managed_mem0_v5_credentials",
    "read_managed_mem0_v5_private_secret",
    "wipe_managed_mem0_v5_private_secret",
]
