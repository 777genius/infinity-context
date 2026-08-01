"""Artifact file helpers for public memory benchmarks."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

ArtifactValidationErrorFactory = Callable[[str], Exception]


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    """Write a JSON artifact as an all-or-nothing file replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
        _fsync_parent_dir(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def _fsync_parent_dir(path: Path) -> None:
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def validate_distinct_artifact_paths(
    *,
    error_factory: ArtifactValidationErrorFactory,
    **paths: Path | None,
) -> None:
    seen: dict[Path, str] = {}
    for label, path in paths.items():
        if path is None:
            continue
        normalized = path.expanduser().resolve(strict=False)
        existing = seen.get(normalized)
        if existing is not None:
            raise error_factory(
                f"Benchmark artifact paths must be distinct: {existing} and {label}"
            )
        seen[normalized] = label


def validate_artifact_paths_do_not_overwrite_dataset(
    *,
    dataset_path: Path,
    error_factory: ArtifactValidationErrorFactory,
    **artifact_paths: Path | None,
) -> None:
    normalized_dataset = dataset_path.expanduser().resolve(strict=False)
    for label, path in artifact_paths.items():
        if path is None:
            continue
        if path.expanduser().resolve(strict=False) == normalized_dataset:
            raise error_factory(f"Benchmark artifact path must not overwrite dataset_path: {label}")
