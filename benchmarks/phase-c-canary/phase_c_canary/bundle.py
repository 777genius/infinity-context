from __future__ import annotations

import json
import stat
from pathlib import Path

from .hashing import sha256_file


class BundleError(RuntimeError):
    pass


REQUIRED_REPRODUCTION_FILES = frozenset(
    {
        "authority.json",
        "infinity-release-files.sha256",
        "runner-source.tar",
        "runner-source.tar.sha256",
        "scan.py",
        "scan.py.sha256",
        "attestation.json",
        "live-entrypoint.sh",
        "runtime-release.json",
        "runtime-artifact-manifest.json",
        "python-closure.json",
        "container-identities.json",
        "provider-usage-v3.sqlite3",
    }
)


def verify_reproduction_bundle(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise BundleError("bundle root must be a regular directory")
    root = root.resolve(strict=True)
    manifest_path = root / "manifest.json"
    try:
        manifest_mode = manifest_path.lstat().st_mode
    except OSError as exc:
        raise BundleError("bundle manifest cannot be read") from exc
    if not stat.S_ISREG(manifest_mode) or manifest_path.is_symlink():
        raise BundleError("bundle manifest must be a regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("bundle manifest cannot be read") from exc
    if set(manifest) != {"schema_version", "files"} or manifest["schema_version"] != 1:
        raise BundleError("unsupported bundle manifest")
    entries = manifest["files"]
    if not isinstance(entries, list):
        raise BundleError("bundle file inventory is invalid")
    indexed: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise BundleError("bundle file entry is invalid")
        relative = entry["path"]
        if not isinstance(relative, str) or relative in indexed:
            raise BundleError("bundle paths are invalid or duplicated")
        relative_path = Path(relative)
        candidate = root / relative_path
        if (
            not relative
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or candidate.is_symlink()
            or _has_symlink_parent(root, candidate)
        ):
            raise BundleError(f"bundle file is absent or escapes root: {relative}")
        path = candidate.resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise BundleError(f"bundle file is absent or escapes root: {relative}")
        if path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            raise BundleError(f"bundle file identity mismatch: {relative}")
        indexed[relative] = entry
    missing = REQUIRED_REPRODUCTION_FILES - set(indexed)
    if missing:
        raise BundleError(f"bundle is not reproducible; missing {sorted(missing)}")
    actual_files: set[str] = set()
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode) and not path.is_symlink():
            continue
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise BundleError(f"bundle contains symlink or special node: {path.relative_to(root)}")
        actual_files.add(str(path.relative_to(root)))
    if actual_files != set(indexed) | {"manifest.json"}:
        raise BundleError("bundle contains unmanifested or missing regular files")
    return manifest


def _has_symlink_parent(root: Path, candidate: Path) -> bool:
    parent = candidate.parent
    while parent != root:
        if parent.is_symlink():
            return True
        if parent == parent.parent:
            return True
        parent = parent.parent
    return root.is_symlink()
