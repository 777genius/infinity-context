"""Metadata-only inventory for project-local bridge lifecycle state."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path

_GENERATION = re.compile(r"generation-([0-9]{7})\Z")
_LIFECYCLE_FILES = frozenset({"active.json", "launcher.lock", "runtime-authority.json"})
_GENERATION_FILES = frozenset({"pending.json", "readiness.json"})


class ProjectLifecycleInventoryError(RuntimeError):
    """Stable failure while observing lifecycle metadata without opening receipts."""


def inspect_project_lifecycle(
    lifecycle: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> str:
    """Commit stable lifecycle structure and metadata without reading receipt bodies."""

    first = _snapshot(
        lifecycle,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    second = _snapshot(
        lifecycle,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if second != first:
        _fail("publishable_attestation_fleet_lifecycle_changed")
    generations = tuple(item[0] for item in first[1])
    if not generations or generations != tuple(range(1, generations[-1] + 1)):
        _fail("publishable_attestation_fleet_generation_invalid")
    commitment = hashlib.sha256(
        _canonical_json({"lifecycle": first[0], "generations": first[1]})
    ).hexdigest()
    return commitment


def _snapshot(
    lifecycle: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> tuple[
    tuple[tuple[object, ...], ...],
    tuple[tuple[int, tuple[tuple[object, ...], ...]], ...],
]:
    _require_private_directory(lifecycle, expected_uid, expected_gid)
    try:
        entries = tuple(sorted(lifecycle.iterdir(), key=lambda item: item.name))
    except OSError as exc:
        raise ProjectLifecycleInventoryError(
            "publishable_attestation_fleet_directory_unavailable"
        ) from exc
    names = {path.name for path in entries}
    generation_paths: dict[int, Path] = {}
    for path in entries:
        matched = _GENERATION.fullmatch(path.name)
        if matched is not None:
            generation = int(matched.group(1))
            if generation < 1 or generation in generation_paths:
                _fail("publishable_attestation_fleet_generation_invalid")
            generation_paths[generation] = path
    if names != _LIFECYCLE_FILES | {path.name for path in generation_paths.values()}:
        _fail("publishable_attestation_fleet_lifecycle_inventory_invalid")
    lifecycle_files = tuple(
        _file_identity(
            lifecycle / name,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        for name in sorted(_LIFECYCLE_FILES)
    )
    generations: list[tuple[int, tuple[tuple[object, ...], ...]]] = []
    for generation, path in sorted(generation_paths.items()):
        _require_private_directory(path, expected_uid, expected_gid)
        try:
            children = tuple(sorted(path.iterdir(), key=lambda item: item.name))
        except OSError as exc:
            raise ProjectLifecycleInventoryError(
                "publishable_attestation_fleet_directory_unavailable"
            ) from exc
        child_names = {child.name for child in children}
        if not _GENERATION_FILES.issubset(child_names) or child_names - (
            _GENERATION_FILES | {"stop.json"}
        ):
            _fail("publishable_attestation_fleet_generation_inventory_invalid")
        generations.append(
            (
                generation,
                tuple(
                    _file_identity(
                        child,
                        expected_uid=expected_uid,
                        expected_gid=expected_gid,
                    )
                    for child in children
                ),
            )
        )
    return lifecycle_files, tuple(generations)


def _file_identity(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> tuple[object, ...]:
    try:
        value = path.lstat()
    except OSError as exc:
        raise ProjectLifecycleInventoryError(
            "publishable_attestation_fleet_file_unavailable"
        ) from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o600
    ):
        _fail("publishable_attestation_fleet_file_unsafe")
    return (
        path.name,
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IMODE(value.st_mode),
    )


def _require_private_directory(path: Path, expected_uid: int, expected_gid: int) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise ProjectLifecycleInventoryError(
            "publishable_attestation_fleet_directory_unavailable"
        ) from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail("publishable_attestation_fleet_directory_unsafe")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fail(code: str) -> None:
    raise ProjectLifecycleInventoryError(code)


__all__ = (
    "ProjectLifecycleInventoryError",
    "inspect_project_lifecycle",
)
