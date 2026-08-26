#!/usr/bin/env python3
"""Canonical tracked-content manifest for Retrieval V2 lifecycle evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_SCHEMA = "infinity-context-reviewed-content-manifest.v2"
_REGULAR_MODES = frozenset({"100644", "100755"})
_SYMLINK_MODE = "120000"


@dataclass(frozen=True)
class _TrackedFile:
    mode: str
    relative: PurePosixPath


def _git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(root), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"cannot inspect retrieval lifecycle Git index{suffix}") from error
    return completed.stdout


def _is_private_environment_file(relative: PurePosixPath) -> bool:
    """Exclude private dotenv inputs without opening them; public examples are source."""
    name = relative.name
    return (name == ".env" or name.startswith(".env.")) and not name.endswith(".example")


def _tracked_files(root: Path) -> tuple[list[_TrackedFile], list[str]]:
    repository_root = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel")).strip()).resolve(
        strict=True
    )
    if repository_root != root:
        raise RuntimeError("retrieval lifecycle manifest root must be the Git repository root")

    records = _git(root, "ls-files", "--cached", "--stage", "-z").split(b"\0")
    tracked: list[_TrackedFile] = []
    excluded: list[str] = []
    for record in records:
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("retrieval lifecycle Git index record is invalid")
        mode, _object_id, stage = (os.fsdecode(field) for field in fields)
        relative = PurePosixPath(os.fsdecode(raw_path))
        if stage != "0" or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("retrieval lifecycle Git index is unresolved or unsafe")
        if _is_private_environment_file(relative):
            excluded.append(relative.as_posix())
            continue
        if mode not in _REGULAR_MODES and mode != _SYMLINK_MODE:
            raise RuntimeError(
                f"unsupported tracked entry {relative.as_posix()!r} with mode {mode}"
            )
        tracked.append(_TrackedFile(mode=mode, relative=relative))

    tracked.sort(key=lambda item: item.relative.as_posix())
    excluded.sort()
    if not tracked:
        raise RuntimeError("retrieval lifecycle manifest scope is empty")
    return tracked, excluded


def _content(root: Path, tracked: _TrackedFile) -> bytes:
    path = root.joinpath(*tracked.relative.parts)
    try:
        status = path.lstat()
    except OSError as error:
        raise RuntimeError(f"tracked manifest input is unavailable: {tracked.relative}") from error
    if tracked.mode == _SYMLINK_MODE:
        if not stat.S_ISLNK(status.st_mode):
            raise RuntimeError(f"tracked manifest symlink changed type: {tracked.relative}")
        return os.fsencode(os.readlink(path))
    if not stat.S_ISREG(status.st_mode):
        raise RuntimeError(f"tracked manifest input changed type: {tracked.relative}")
    return path.read_bytes()


def build_manifest(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    files, excluded = _tracked_files(root)
    entries = []
    canonical = hashlib.sha256()
    for tracked in files:
        relative = tracked.relative.as_posix()
        data = _content(root, tracked)
        entry = {
            "mode": tracked.mode,
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        entries.append(entry)
        canonical.update(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        canonical.update(b"\n")
    return {
        "schema": _SCHEMA,
        "file_count": len(entries),
        "excluded_private_environment_files": excluded,
        "manifest_sha256": canonical.hexdigest(),
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "file_count": manifest["file_count"],
                "manifest_sha256": manifest["manifest_sha256"],
                "schema": manifest["schema"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
