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
    payload: dict[str, object]


def write_immutable_json(
    *,
    directory: Path,
    prefix: str,
    payload: dict[str, object],
) -> ImmutableJsonEvidence:
    """Durably create one commitment-named canonical JSON document."""

    if not directory.is_absolute() or not _safe_prefix(prefix) or type(payload) is not dict:
        _fail("publishable_immutable_evidence_write_input_invalid")
    _require_private_directory(directory)
    try:
        raw_payload = _canonical_json(payload)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_invalid") from exc
    commitment = hashlib.sha256(raw_payload).hexdigest()
    destination = directory / f"{prefix}{commitment}.json"
    raw = raw_payload + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    descriptor: int | None = None
    try:
        descriptor = os.open(destination, flags, 0o600)
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_write_failed") from exc
    finally:
        os.umask(previous_umask)
        if descriptor is not None:
            os.close(descriptor)
    _fsync_directory(directory)
    evidence = read_immutable_json(
        path=destination,
        directory=directory,
        prefix=prefix,
    )
    if evidence.payload != payload:
        _fail("publishable_immutable_evidence_existing_mismatch")
    return evidence


def read_immutable_json(
    *,
    path: Path,
    directory: Path,
    prefix: str,
) -> ImmutableJsonEvidence:
    """Read through a no-follow descriptor and bind bytes, name, inode, and stat."""

    if (
        not path.is_absolute()
        or not directory.is_absolute()
        or path.parent != directory
        or not _safe_prefix(prefix)
    ):
        _fail("publishable_immutable_evidence_read_input_invalid")
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or not 1 <= opened.st_size <= _MAX_EVIDENCE_BYTES
        ):
            _fail("publishable_immutable_evidence_unsafe")
        raw = _read_exact(descriptor, opened.st_size)
        final = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(final):
            _fail("publishable_immutable_evidence_changed")
    except ImmutableEvidenceError:
        raise
    except OSError as exc:
        raise ImmutableEvidenceError("publishable_immutable_evidence_unavailable") from exc
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
        payload=payload,
    )


def require_immutable_json_unchanged(
    evidence: ImmutableJsonEvidence,
    *,
    directory: Path,
    prefix: str,
) -> ImmutableJsonEvidence:
    """Re-read and require byte, commitment, inode, and metadata identity."""

    if type(evidence) is not ImmutableJsonEvidence:
        _fail("publishable_immutable_evidence_read_input_invalid")
    observed = read_immutable_json(path=evidence.path, directory=directory, prefix=prefix)
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


def _require_private_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise ImmutableEvidenceError(
            "publishable_immutable_evidence_directory_unavailable"
        ) from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail("publishable_immutable_evidence_directory_unsafe")


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            _fail("publishable_immutable_evidence_short_write")
        offset += written


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
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


def _fail(code: str) -> None:
    raise ImmutableEvidenceError(code)


__all__ = (
    "ImmutableEvidenceError",
    "ImmutableJsonEvidence",
    "read_immutable_json",
    "require_immutable_json_unchanged",
    "write_immutable_json",
)
