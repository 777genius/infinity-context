from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .authority import AuthorityContract
from .hashing import sha256_file
from .python_closure import verify_python_import_closure


class AuthorityError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def verify_immutable_authority(authority: AuthorityContract) -> None:
    for immutable in (
        authority.infinity_release_manifest,
        authority.runtime_artifact_manifest,
        authority.runtime_release,
    ):
        if not immutable.path.is_file():
            raise AuthorityError(f"authority file is absent: {immutable.path}")
        actual = sha256_file(immutable.path)
        if actual != immutable.sha256:
            raise AuthorityError(f"authority digest mismatch: {immutable.path}")

    release = _strict_object(authority.runtime_release.path)
    if release.get("commitSha") != authority.runtime_commit:
        raise AuthorityError("runtime release commit does not match authority")
    if release.get("activation") != "not-activated":
        raise AuthorityError("immutable canary runtime unexpectedly reports activation")
    source_commit = (
        (authority.infinity_source_root / "attestation" / "commit.txt")
        .read_text(encoding="utf-8")
        .strip()
    )
    if source_commit != authority.infinity_commit:
        raise AuthorityError("Infinity source commit does not match authority")
    _verify_sha256_manifest(
        authority.infinity_release_manifest.path,
        authority.infinity_source_root,
    )
    _verify_sha256_manifest(
        authority.infinity_source_root / "attestation" / "source-files.sha256",
        authority.infinity_source_root,
    )
    _verify_runtime_artifacts(
        authority.runtime_artifact_manifest.path,
        authority.runtime_root / "repo",
    )
    verify_python_import_closure(authority)


def require_import_from(module_name: str, root: Path) -> ModuleType:
    module = importlib.import_module(module_name)
    module_path = Path(getattr(module, "__file__", "")).resolve(strict=True)
    expected_root = root.resolve(strict=True)
    if not module_path.is_relative_to(expected_root):
        raise AuthorityError(
            f"import shadowing detected for {module_name}: {module_path} is outside {expected_root}"
        )
    return module


def _strict_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"invalid authority JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuthorityError(f"authority JSON is not an object: {path}")
    return value


def _verify_sha256_manifest(manifest: Path, root: Path) -> None:
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AuthorityError(f"cannot read closure manifest: {manifest}") from exc
    if not lines:
        raise AuthorityError(f"closure manifest is empty: {manifest}")
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise AuthorityError(f"invalid closure manifest line: {manifest}")
        expected, relative = parts
        path = _contained(root, relative)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise AuthorityError(f"closure file identity mismatch: {relative}")


def _verify_runtime_artifacts(manifest: Path, repo: Path) -> None:
    value = _strict_object(manifest)
    entries = value.get("artifactFiles")
    if not isinstance(entries, list) or not entries:
        raise AuthorityError("runtime artifact inventory is absent")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise AuthorityError("runtime artifact entry is invalid")
        relative = entry["path"]
        if not isinstance(relative, str) or relative in seen:
            raise AuthorityError("runtime artifact path is invalid or duplicated")
        seen.add(relative)
        path = _contained(repo, relative)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != entry["size"]
            or sha256_file(path) != entry["sha256"]
        ):
            raise AuthorityError(f"runtime artifact identity mismatch: {relative}")


def _contained(root: Path, relative: str, *, resolve: bool = True) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise AuthorityError(f"unsafe closure path: {relative}")
    candidate = root / relative
    if resolve and not candidate.resolve().is_relative_to(root.resolve()):
        raise AuthorityError(f"closure path escapes root: {relative}")
    return candidate
