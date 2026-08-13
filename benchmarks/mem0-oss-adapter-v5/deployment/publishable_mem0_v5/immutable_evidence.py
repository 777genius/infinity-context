"""Small write-once canonical JSON boundary for lifecycle evidence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_MAX_EVIDENCE_BYTES: Final = 4 * 1024 * 1024


class ImmutableEvidenceError(RuntimeError):
    """Stable failure for unsafe, changed, or noncanonical evidence."""


@dataclass(frozen=True, slots=True)
class ImmutableJsonEvidence:
    path: Path
    commitment_sha256: str
    file_sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    uid: int
    gid: int
    payload: dict[str, object]


def write_immutable_json(
    *,
    directory: Path,
    prefix: str,
    payload: dict[str, object],
    expected_uid: int,
    expected_gid: int,
) -> ImmutableJsonEvidence:
    """Durably create one commitment-named canonical JSON document."""

    if (
        not directory.is_absolute()
        or not _safe_prefix(prefix)
        or type(payload) is not dict
        or not _safe_owner(expected_uid, expected_gid)
    ):
        _fail("publishable_immutable_evidence_write_input_invalid")
    try:
        raw_payload = _canonical_json(payload)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_invalid") from exc
    commitment = hashlib.sha256(raw_payload).hexdigest()
    basename = f"{prefix}{commitment}.json"
    destination = directory / basename
    raw = raw_payload + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    descriptor: int | None = None
    directory_descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    try:
        directory_descriptor = _open_private_directory(directory, expected_uid, expected_gid)
        try:
            descriptor = os.open(basename, flags, 0o600, dir_fd=directory_descriptor)
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            created = os.fstat(descriptor)
            created_identity = (created.st_dev, created.st_ino)
            os.fchown(descriptor, expected_uid, expected_gid)
            os.fchmod(descriptor, 0o600)
            _require_evidence_descriptor(descriptor, expected_uid, expected_gid)
            _write_all(descriptor, raw)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
        _require_private_directory_descriptor(directory_descriptor, expected_uid, expected_gid)
        os.fsync(directory_descriptor)
        evidence = _read_immutable_json_from_dirfd(
            path=destination,
            directory_descriptor=directory_descriptor,
            prefix=prefix,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if evidence.payload != payload:
            _fail("publishable_immutable_evidence_existing_mismatch")
        _require_directory_path_bound(directory, directory_descriptor)
        return evidence
    except BaseException as exc:
        if directory_descriptor is not None and created_identity is not None:
            _unlink_created_entry_best_effort(
                directory_descriptor, basename, created_identity
            )
        if isinstance(exc, ImmutableEvidenceError):
            raise
        raise ImmutableEvidenceError("publishable_immutable_evidence_write_failed") from exc
    finally:
        os.umask(previous_umask)
        if descriptor is not None:
            os.close(descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def read_immutable_json(
    *,
    path: Path,
    directory: Path,
    prefix: str,
    expected_uid: int,
    expected_gid: int,
) -> ImmutableJsonEvidence:
    """Read through a no-follow descriptor and bind bytes, name, inode, and stat."""

    if (
        not path.is_absolute()
        or not directory.is_absolute()
        or path.parent != directory
        or not _safe_prefix(prefix)
        or not _safe_owner(expected_uid, expected_gid)
    ):
        _fail("publishable_immutable_evidence_read_input_invalid")
    directory_descriptor: int | None = None
    try:
        directory_descriptor = _open_private_directory(directory, expected_uid, expected_gid)
        evidence = _read_immutable_json_from_dirfd(
            path=path,
            directory_descriptor=directory_descriptor,
            prefix=prefix,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _require_directory_path_bound(directory, directory_descriptor)
        return evidence
    except ImmutableEvidenceError:
        raise
    except OSError as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_unavailable") from exc
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _read_immutable_json_from_dirfd(
    *,
    path: Path,
    directory_descriptor: int,
    prefix: str,
    expected_uid: int,
    expected_gid: int,
) -> ImmutableJsonEvidence:
    descriptor: int | None = None
    try:
        before = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptor,
        )
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_uid, opened.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or not 1 <= opened.st_size <= _MAX_EVIDENCE_BYTES
        ):
            _fail("publishable_immutable_evidence_unsafe")
        raw = _read_exact(descriptor, opened.st_size)
        final = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            _stat_identity(opened) != _stat_identity(final)
            or _stat_identity(named) != _stat_identity(final)
        ):
            _fail("publishable_immutable_evidence_changed")
        _require_private_directory_descriptor(directory_descriptor, expected_uid, expected_gid)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        _fail("publishable_immutable_evidence_noncanonical")
    encoded = raw[:-1]
    try:
        payload = json.loads(encoded, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ImmutableEvidenceError) as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_invalid") from exc
    try:
        canonical = _canonical_json(payload)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_invalid") from exc
    if type(payload) is not dict or canonical != encoded:
        _fail("publishable_immutable_evidence_noncanonical")
    commitment = hashlib.sha256(encoded).hexdigest()
    if path.name != f"{prefix}{commitment}.json":
        _fail("publishable_immutable_evidence_commitment_mismatch")
    return ImmutableJsonEvidence(
        path=path,
        commitment_sha256=commitment,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        device=opened.st_dev,
        inode=opened.st_ino,
        size=opened.st_size,
        mtime_ns=opened.st_mtime_ns,
        ctime_ns=opened.st_ctime_ns,
        uid=opened.st_uid,
        gid=opened.st_gid,
        payload=payload,
    )


def require_immutable_json_unchanged(
    evidence: ImmutableJsonEvidence,
    *,
    directory: Path,
    prefix: str,
    expected_uid: int,
    expected_gid: int,
) -> ImmutableJsonEvidence:
    """Re-read and require byte, commitment, inode, and metadata identity."""

    if type(evidence) is not ImmutableJsonEvidence:
        _fail("publishable_immutable_evidence_read_input_invalid")
    observed = read_immutable_json(
        path=evidence.path,
        directory=directory,
        prefix=prefix,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if observed != evidence:
        _fail("publishable_immutable_evidence_changed")
    return observed


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            _fail("publishable_immutable_evidence_short_read")
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        _fail("publishable_immutable_evidence_changed")
    return b"".join(chunks)


def _open_private_directory(path: Path, expected_uid: int, expected_gid: int) -> int:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ImmutableEvidenceError(
            "publishable_immutable_evidence_directory_unavailable"
        ) from exc
    try:
        _require_private_directory_descriptor(descriptor, expected_uid, expected_gid)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _require_private_directory_descriptor(
    descriptor: int, expected_uid: int, expected_gid: int
) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(value.st_mode)
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail("publishable_immutable_evidence_directory_unsafe")


def _require_directory_path_bound(path: Path, descriptor: int) -> None:
    value = os.stat(path, follow_symlinks=False)
    opened = os.fstat(descriptor)
    if (
        stat.S_ISLNK(value.st_mode)
        or (value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        _fail("publishable_immutable_evidence_directory_changed")


def _require_evidence_descriptor(descriptor: int, expected_uid: int, expected_gid: int) -> None:
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        _fail("publishable_immutable_evidence_unsafe")


def _unlink_created_entry_best_effort(
    directory_descriptor: int, basename: str, created_identity: tuple[int, int]
) -> None:
    try:
        current = os.stat(basename, dir_fd=directory_descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == created_identity:
            os.unlink(basename, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
    except OSError:
        pass


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            _fail("publishable_immutable_evidence_short_write")
        offset += written


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_uid,
        value.st_gid,
    )


def _unique_object(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            _fail("publishable_immutable_evidence_duplicate_key")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _safe_prefix(value: object) -> bool:
    return (
        type(value) is str
        and value.endswith("-")
        and 2 <= len(value) <= 64
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in value)
    )


def _safe_owner(uid: object, gid: object) -> bool:
    return type(uid) is int and uid >= 0 and type(gid) is int and gid >= 0


def _fail(code: str) -> None:
    raise ImmutableEvidenceError(code)


__all__ = (
    "ImmutableEvidenceError",
    "ImmutableJsonEvidence",
    "read_immutable_json",
    "require_immutable_json_unchanged",
    "write_immutable_json",
)
