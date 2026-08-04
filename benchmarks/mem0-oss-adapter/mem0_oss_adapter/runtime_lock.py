"""Validation helpers for the compact, host-specific immutable wheel lock."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from mem0_oss_adapter.runtime_pin import RuntimePin

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,99}$")
_DIST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")


@dataclass(frozen=True, slots=True)
class LockedArtifact:
    distribution: str
    version: str
    filename: str
    sha256: str
    url: str


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    artifacts: tuple[LockedArtifact, ...]
    machine: str
    python_version: str
    schema_version: str
    sys_platform: str


def canonical_runtime_lock_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_runtime_lock(path: Path, *, pin: RuntimePin) -> RuntimeLock:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid runtime lock: {path.name}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "artifacts",
        "machine",
        "python_version",
        "schema_version",
        "sys_platform",
    }:
        raise RuntimeError("invalid runtime lock: fields are missing or extra")
    if (
        payload["schema_version"] != "mem0-oss-runtime-lock.v1"
        or payload["python_version"] != pin.python_version
        or payload["sys_platform"] != "linux"
        or payload["machine"] != "x86_64"
        or not isinstance(payload["artifacts"], list)
        or not 1 <= len(payload["artifacts"]) <= 1000
    ):
        raise RuntimeError("invalid runtime lock: incompatible target")
    if canonical_runtime_lock_sha256(payload) != pin.runtime_lock_sha256:
        raise RuntimeError("runtime lock digest does not match runtime pin")
    if len(payload["artifacts"]) != pin.runtime_lock_artifact_count:
        raise RuntimeError("runtime lock artifact count does not match runtime pin")

    artifacts = tuple(_load_artifact(item) for item in payload["artifacts"])
    _require_unique((item.distribution for item in artifacts), "distribution")
    _require_unique((item.filename for item in artifacts), "filename")
    expected = {
        "mem0ai": (pin.mem0ai_version, pin.mem0ai_wheel_filename, pin.mem0ai_wheel_sha256),
        "fastembed": (
            pin.fastembed_version,
            pin.fastembed_wheel_filename,
            pin.fastembed_wheel_sha256,
        ),
        "qdrant-client": (
            pin.qdrant_client_version,
            pin.qdrant_client_wheel_filename,
            pin.qdrant_client_wheel_sha256,
        ),
    }
    by_distribution = {item.distribution: item for item in artifacts}
    for name, (version, filename, digest) in expected.items():
        artifact = by_distribution.get(name)
        if artifact is None or (artifact.version, artifact.filename, artifact.sha256) != (
            version,
            filename,
            digest,
        ):
            raise RuntimeError(f"runtime lock does not preserve {name} pin")
    return RuntimeLock(
        artifacts=artifacts,
        machine=payload["machine"],
        python_version=payload["python_version"],
        schema_version=payload["schema_version"],
        sys_platform=payload["sys_platform"],
    )


def verify_downloaded_artifacts(runtime_lock: RuntimeLock, directory: Path) -> None:
    for artifact in runtime_lock.artifacts:
        candidate = directory / artifact.filename
        if not candidate.is_file():
            raise RuntimeError(f"locked wheel is missing: {artifact.filename}")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != artifact.sha256:
            raise RuntimeError(f"locked wheel digest mismatch: {artifact.filename}")


def verify_wheel_metadata_closure(runtime_lock: RuntimeLock, directory: Path) -> None:
    """Ensure installed wheel metadata cannot smuggle a second dependency graph."""

    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.version import Version

    installed = {
        artifact.distribution: (artifact.version, directory / artifact.filename)
        for artifact in runtime_lock.artifacts
    }
    environment = default_environment()
    environment.update(
        {
            "python_version": runtime_lock.python_version,
            "python_full_version": f"{runtime_lock.python_version}.0",
            "sys_platform": runtime_lock.sys_platform,
            "platform_machine": runtime_lock.machine,
            "platform_system": "Linux",
            "extra": "",
        }
    )
    for artifact in runtime_lock.artifacts:
        metadata = _read_wheel_metadata(directory / artifact.filename)
        name = _normalize_distribution(str(metadata.get("Name") or ""))
        version = str(metadata.get("Version") or "")
        if name != artifact.distribution or version != artifact.version:
            raise RuntimeError("wheel METADATA identity disagrees with lock")
        for raw_requirement in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            dependency = _normalize_distribution(requirement.name)
            locked = installed.get(dependency)
            if locked is None:
                raise RuntimeError(
                    "active dependency is absent from lock: "
                    f"{artifact.distribution} -> {dependency}"
                )
            if requirement.specifier and not requirement.specifier.contains(
                Version(locked[0]), prereleases=True
            ):
                raise RuntimeError("locked dependency version is incompatible")


def _read_wheel_metadata(path: Path):
    try:
        with zipfile.ZipFile(path) as wheel:
            candidates = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
            if len(candidates) != 1:
                raise RuntimeError("wheel contains ambiguous metadata")
            return BytesParser().parsebytes(wheel.read(candidates[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"cannot read wheel metadata: {path.name}") from exc


def _load_artifact(value: object) -> LockedArtifact:
    if not isinstance(value, dict) or set(value) != {
        "distribution",
        "filename",
        "sha256",
        "url",
        "version",
    }:
        raise RuntimeError("invalid runtime lock artifact")
    artifact = LockedArtifact(**value)
    parsed_url = urlparse(artifact.url)
    if (
        not _DIST.fullmatch(artifact.distribution)
        or not _VERSION.fullmatch(artifact.version)
        or not _FILENAME.fullmatch(artifact.filename)
        or not _SHA256.fullmatch(artifact.sha256)
        or parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.path.rsplit("/", 1)[-1] != artifact.filename
    ):
        raise RuntimeError("invalid runtime lock artifact value")
    return artifact


def _normalize_distribution(value: str) -> str:
    return value.replace("_", "-").casefold()


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise RuntimeError(f"runtime lock contains duplicate {label}")
