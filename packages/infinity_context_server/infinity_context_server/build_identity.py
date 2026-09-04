"""Verification of trusted source and installed service build identities."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_SCHEMA = "infinity-context.source-build.v1"
_INSTALLED_SCHEMA = "infinity-context.installed-build.v2"
_LEGACY_INSTALLED_SCHEMA = "infinity-context.installed-build.v1"
_MAX_BYTES = 16_384
_RUNTIME_PACKAGES = (
    "infinity_context_adapters",
    "infinity_context_contracts",
    "infinity_context_core",
    "infinity_context_server",
)


class Distribution(Protocol):
    files: Any

    def locate_file(self, path: Any) -> Path: ...


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    service_revision: str
    source_tree_digest_sha256: str
    installed_distribution_digest_sha256: str
    runtime_modules_digest_sha256: str

    def installed_release(self):
        from infinity_context_core.features.context_building.public import (
            InstalledReleaseIdentity,
        )

        return InstalledReleaseIdentity(
            self.service_revision,
            self.source_tree_digest_sha256,
            self.installed_distribution_digest_sha256,
            self.runtime_modules_digest_sha256,
        )


def installed_distribution_digest(distribution: Distribution | None = None) -> str:
    """Hash every installed RECORD file and reject shadow imports or aliases."""

    return installed_artifact_digests(distribution)[0]


def installed_artifact_digests(
    distribution: Distribution | None = None,
) -> tuple[str, str]:
    """Measure the complete distribution and repository-owned runtime modules."""

    try:
        installed = distribution or importlib.metadata.distribution("infinity-context")
        root = Path(installed.locate_file("")).resolve(strict=True)
        installation_root = Path(sys.prefix).resolve(strict=True)
        imported = tuple(
            Path(importlib.import_module(name).__file__ or "").resolve(strict=True)
            for name in _RUNTIME_PACKAGES
        )
    except (importlib.metadata.PackageNotFoundError, FileNotFoundError) as exc:
        raise RuntimeError("installed infinity-context distribution is unavailable") from exc
    if (
        not root.is_dir()
        or not root.is_relative_to(installation_root)
        or any(not path.is_relative_to(root) for path in imported)
    ):
        raise RuntimeError("infinity-context server import is outside installed distribution")
    recorded = installed.files
    if recorded is None:
        raise RuntimeError("installed infinity-context distribution has no RECORD files")
    files: list[tuple[str, Path]] = []
    names: set[str] = set()
    paths: set[Path] = set()
    imported_recorded: set[Path] = set()
    for item in recorded:
        raw = str(item).replace("\\", "/")
        relative = PurePosixPath(raw)
        if relative.is_absolute():
            raise RuntimeError("installed RECORD contains an absolute path")
        try:
            path = Path(installed.locate_file(item)).resolve(strict=True)
        except FileNotFoundError as exc:
            raise RuntimeError("installed RECORD file is unavailable") from exc
        if not path.is_file() or not path.is_relative_to(installation_root):
            raise RuntimeError("installed RECORD file resolves outside installation prefix")
        name = path.relative_to(installation_root).as_posix()
        if not name or name in names or path in paths:
            raise RuntimeError("installed RECORD contains duplicate or aliased files")
        names.add(name)
        paths.add(path)
        files.append((name, path))
        imported_recorded.update(candidate for candidate in imported if path == candidate)
    if not files or imported_recorded != set(imported):
        raise RuntimeError("imported runtime module is absent from installed RECORD")
    digest = hashlib.sha256()
    runtime_digest = hashlib.sha256()
    runtime_roots = tuple(path.parent for path in imported)
    runtime_file_count = 0
    for name, path in sorted(files):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        if any(path.is_relative_to(root) for root in runtime_roots):
            runtime_digest.update(name.encode())
            runtime_digest.update(b"\0")
            runtime_digest.update(path.read_bytes())
            runtime_digest.update(b"\0")
            runtime_file_count += 1
    if runtime_file_count < len(_RUNTIME_PACKAGES):
        raise RuntimeError("installed runtime module set is incomplete")
    return f"sha256:{digest.hexdigest()}", f"sha256:{runtime_digest.hexdigest()}"


def repository_source_release_identity(root: Path, *, service_revision: str | None = None):
    """Measure a repository-owned source runtime used only by isolated acceptance."""

    from infinity_context_core.features.context_building.public import (
        InstalledReleaseIdentity,
    )

    root = root.resolve(strict=True)
    revision = service_revision
    if revision is None:
        try:
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("repository source revision is unavailable") from exc
    if not _GIT_SHA.fullmatch(revision):
        raise RuntimeError("repository source revision is invalid")
    runtime_files: list[Path] = []
    for package in _RUNTIME_PACKAGES:
        package_root = root / "packages" / package
        runtime_files.extend(
            path
            for path in package_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in {".py", ".json", ".sql"}
        )
    runtime_digest = _paths_digest(root, runtime_files)
    distribution_files = [*runtime_files, root / "pyproject.toml", root / "uv.lock"]
    distribution_digest = _paths_digest(root, distribution_files)
    source_files = [
        path
        for directory in ("packages", "tests", "scripts", "docs", ".github")
        for path in (root / directory).rglob("*")
        if path.is_file()
        and not any(
            part
            in {
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                "build",
                "dist",
                "node_modules",
            }
            for part in path.parts
        )
        and path.suffix in {".py", ".pyi", ".ts", ".mjs", ".json", ".sql", ".md", ".yml", ".yaml"}
    ]
    source_files.extend(
        path for path in (root / "pyproject.toml", root / "uv.lock") if path.is_file()
    )
    return InstalledReleaseIdentity(
        revision,
        _paths_digest(root, source_files),
        distribution_digest,
        runtime_digest,
    )


def _paths_digest(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    unique = sorted({path.resolve(strict=True) for path in paths})
    if not unique or any(not path.is_relative_to(root) for path in unique):
        raise RuntimeError("repository source artifact is invalid")
    for path in unique:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def write_installed_build_identity(*, source_manifest: Path, output_path: Path) -> None:
    source = _read_json(source_manifest)
    revision, source_digest = _validate_source(source)
    distribution_digest, runtime_digest = installed_artifact_digests()
    payload = {
        "schema_version": _INSTALLED_SCHEMA,
        "service_revision": revision,
        "source_tree_digest_sha256": source_digest,
        "installed_distribution_digest_sha256": distribution_digest,
        "runtime_modules_digest_sha256": runtime_digest,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    temporary.replace(output_path)


def verify_installed_build_identity(path_text: str | None) -> BuildIdentity | None:
    if path_text is None:
        return None
    if not path_text:
        raise RuntimeError("service build identity path cannot be empty")
    path = Path(path_text)
    try:
        payload = _read_json(path)
    except FileNotFoundError:
        return None
    required = {
        "schema_version",
        "service_revision",
        "source_tree_digest_sha256",
        "installed_distribution_digest_sha256",
    }
    schema = payload.get("schema_version")
    if schema == _INSTALLED_SCHEMA:
        required.add("runtime_modules_digest_sha256")
    if set(payload) != required or schema not in {_INSTALLED_SCHEMA, _LEGACY_INSTALLED_SCHEMA}:
        raise RuntimeError("service build identity has an unsupported contract")
    revision = payload["service_revision"]
    source_digest = payload["source_tree_digest_sha256"]
    installed_digest = payload["installed_distribution_digest_sha256"]
    pinned_runtime_digest = payload.get("runtime_modules_digest_sha256")
    if not isinstance(revision, str) or not _GIT_SHA.fullmatch(revision):
        raise RuntimeError("service build revision is invalid")
    if (
        not _valid_digest(source_digest)
        or not _valid_digest(installed_digest)
        or (pinned_runtime_digest is not None and not _valid_digest(pinned_runtime_digest))
    ):
        raise RuntimeError("service build digest is invalid")
    observed, runtime_digest = installed_artifact_digests()
    if not hmac.compare_digest(installed_digest, observed):
        raise RuntimeError("service build does not match executing distribution")
    if pinned_runtime_digest is not None and not hmac.compare_digest(
        pinned_runtime_digest, runtime_digest
    ):
        raise RuntimeError("service build does not match executing runtime modules")
    return BuildIdentity(revision, source_digest, installed_digest, runtime_digest)


def _read_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > _MAX_BYTES:
        raise RuntimeError("service build identity exceeds its size limit")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("service build identity is malformed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("service build identity must be an object")
    return payload


def _validate_source(payload: dict[str, Any]) -> tuple[str, str]:
    if set(payload) != {"schema_version", "service_revision", "source_tree_digest_sha256"}:
        raise RuntimeError("source build manifest has an unsupported contract")
    revision, digest = payload["service_revision"], payload["source_tree_digest_sha256"]
    if payload["schema_version"] != _SOURCE_SCHEMA or not isinstance(revision, str):
        raise RuntimeError("source build manifest is invalid")
    if not _GIT_SHA.fullmatch(revision) or not _valid_digest(digest):
        raise RuntimeError("source build manifest is invalid")
    return revision, digest


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None
