from __future__ import annotations

import tarfile
import zipfile
import zlib
from collections.abc import Set
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4_096
MAX_ARCHIVE_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_TEXT_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_NAME_BYTES = 1_024


class ArchiveSourceGuardError(ValueError):
    """A supported source archive could not be inspected safely and completely."""


@dataclass(frozen=True)
class ArchiveSourceInventory:
    member_names: tuple[str, ...]
    text_members: tuple[tuple[Path, str], ...]


def inspect_source_archive(
    path: Path, *, text_suffixes: Set[str]
) -> ArchiveSourceInventory:
    try:
        if path.name.endswith((".whl", ".zip")):
            _bounded_archive(path)
            return _inspect_zip(path, text_suffixes)
        if path.name.endswith((".tar", ".tar.gz", ".tgz")):
            _bounded_archive(path)
            return _inspect_tar(path, text_suffixes)
    except (
        OSError,
        EOFError,
        UnicodeError,
        NotImplementedError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zlib.error,
    ) as error:
        raise ArchiveSourceGuardError(f"archive is unreadable or malformed: {path.name}") from error
    raise ArchiveSourceGuardError(f"unsupported archive suffix: {path.name}")


def _inspect_zip(path: Path, text_suffixes: Set[str]) -> ArchiveSourceInventory:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        _bounded_entries(infos)
        names = tuple(info.filename for info in infos)
        _safe_unique_names(names)
        text_members: list[tuple[Path, str]] = []
        total = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ArchiveSourceGuardError(f"encrypted archive member: {info.filename}")
            if info.is_dir() or Path(info.filename).suffix not in text_suffixes:
                continue
            _bounded_member(info.filename, info.file_size)
            total = _bounded_total(total, info.file_size)
            with archive.open(info) as extracted:
                raw = extracted.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
            _bounded_member(info.filename, len(raw))
            if len(raw) != info.file_size:
                raise ArchiveSourceGuardError(f"archive member size mismatch: {info.filename}")
            text_members.append((Path(info.filename), raw.decode("utf-8")))
        return ArchiveSourceInventory(names, tuple(text_members))


def _inspect_tar(path: Path, text_suffixes: Set[str]) -> ArchiveSourceInventory:
    with tarfile.open(path, mode="r:*") as archive:
        names: list[str] = []
        seen_names: set[str] = set()
        text_members: list[tuple[Path, str]] = []
        total = 0
        for member in archive:
            if len(names) >= MAX_ARCHIVE_ENTRIES:
                raise ArchiveSourceGuardError("archive entry limit exceeded")
            _safe_unique_name(member.name, seen_names)
            names.append(member.name)
            if member.issym() or member.islnk():
                raise ArchiveSourceGuardError(f"linked archive member: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise ArchiveSourceGuardError(f"unsupported archive member: {member.name}")
            if Path(member.name).suffix not in text_suffixes:
                continue
            _bounded_member(member.name, member.size)
            total = _bounded_total(total, member.size)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ArchiveSourceGuardError(f"archive member is unreadable: {member.name}")
            with extracted:
                raw = extracted.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
            _bounded_member(member.name, len(raw))
            if len(raw) != member.size:
                raise ArchiveSourceGuardError(f"archive member size mismatch: {member.name}")
            text_members.append((Path(member.name), raw.decode("utf-8")))
        return ArchiveSourceInventory(tuple(names), tuple(text_members))


def _bounded_archive(path: Path) -> None:
    size = path.stat().st_size
    if size < 0 or size > MAX_ARCHIVE_BYTES:
        raise ArchiveSourceGuardError("archive byte limit exceeded")


def _bounded_entries(entries: list[zipfile.ZipInfo]) -> None:
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ArchiveSourceGuardError("archive entry limit exceeded")


def _safe_unique_names(names: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for name in names:
        _safe_unique_name(name, seen)


def _safe_unique_name(name: str, seen: set[str]) -> None:
    if name in seen:
        raise ArchiveSourceGuardError("archive contains duplicate member names")
    seen.add(name)
    pure = PurePosixPath(name)
    if (
        not name
        or len(name.encode("utf-8")) > MAX_ARCHIVE_NAME_BYTES
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in name
    ):
        raise ArchiveSourceGuardError(f"unsafe archive member name: {name}")


def _bounded_member(name: str, size: int) -> None:
    if size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES:
        raise ArchiveSourceGuardError(f"archive member byte limit exceeded: {name}")


def _bounded_total(total: int, size: int) -> int:
    bounded = total + size
    if bounded > MAX_ARCHIVE_TEXT_BYTES:
        raise ArchiveSourceGuardError("archive text byte limit exceeded")
    return bounded
