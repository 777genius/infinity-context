"""Verification of trusted source and installed service build identities."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.metadata
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_SCHEMA = "infinity-context.source-build.v1"
_INSTALLED_SCHEMA = "infinity-context.installed-build.v1"
_MAX_BYTES = 16_384


class Distribution(Protocol):
    files: Any

    def locate_file(self, path: Any) -> Path: ...


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    service_revision: str
    source_tree_digest_sha256: str
    installed_distribution_digest_sha256: str


def installed_distribution_digest(distribution: Distribution | None = None) -> str:
    """Hash every installed RECORD file and reject shadow imports or aliases."""

    try:
        installed = distribution or importlib.metadata.distribution("infinity-context")
        root = Path(installed.locate_file("")).resolve(strict=True)
        imported = Path(importlib.import_module("infinity_context_server").__file__ or "").resolve(
            strict=True
        )
    except (importlib.metadata.PackageNotFoundError, FileNotFoundError) as exc:
        raise RuntimeError("installed infinity-context distribution is unavailable") from exc
    if not root.is_dir() or not imported.is_relative_to(root):
        raise RuntimeError("infinity-context server import is outside installed distribution")
    recorded = installed.files
    if recorded is None:
        raise RuntimeError("installed infinity-context distribution has no RECORD files")
    files: list[tuple[str, Path]] = []
    names: set[str] = set()
    paths: set[Path] = set()
    imported_recorded = False
    for item in recorded:
        raw = str(item).replace("\\", "/")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("installed RECORD contains an out-of-root path")
        name = relative.as_posix()
        try:
            path = Path(installed.locate_file(item)).resolve(strict=True)
        except FileNotFoundError as exc:
            raise RuntimeError("installed RECORD file is unavailable") from exc
        if not path.is_file() or not path.is_relative_to(root):
            raise RuntimeError("installed RECORD file resolves outside distribution")
        if not name or name in names or path in paths:
            raise RuntimeError("installed RECORD contains duplicate or aliased files")
        names.add(name)
        paths.add(path)
        files.append((name, path))
        imported_recorded |= path == imported
    if not files or not imported_recorded:
        raise RuntimeError("imported server module is absent from installed RECORD")
    digest = hashlib.sha256()
    for name, path in sorted(files):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def write_installed_build_identity(*, source_manifest: Path, output_path: Path) -> None:
    source = _read_json(source_manifest)
    revision, source_digest = _validate_source(source)
    payload = {
        "schema_version": _INSTALLED_SCHEMA,
        "service_revision": revision,
        "source_tree_digest_sha256": source_digest,
        "installed_distribution_digest_sha256": installed_distribution_digest(),
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
        "schema_version", "service_revision", "source_tree_digest_sha256",
        "installed_distribution_digest_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != _INSTALLED_SCHEMA:
        raise RuntimeError("service build identity has an unsupported contract")
    revision = payload["service_revision"]
    source_digest = payload["source_tree_digest_sha256"]
    installed_digest = payload["installed_distribution_digest_sha256"]
    if not isinstance(revision, str) or not _GIT_SHA.fullmatch(revision):
        raise RuntimeError("service build revision is invalid")
    if not _valid_digest(source_digest) or not _valid_digest(installed_digest):
        raise RuntimeError("service build digest is invalid")
    observed = installed_distribution_digest()
    if not hmac.compare_digest(installed_digest, observed):
        raise RuntimeError("service build does not match executing distribution")
    return BuildIdentity(revision, source_digest, installed_digest)


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
