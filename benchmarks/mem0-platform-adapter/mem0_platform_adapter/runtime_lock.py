"""Fail-closed validation for the compact platform-specific wheel lock."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from collections import deque
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile

from mem0_platform_adapter.runtime_pin import RuntimePin

_SCHEMA_VERSION = "mem0-platform-runtime-lock.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DISTRIBUTION = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,99}$")
_WHEEL_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")


@dataclass(frozen=True, slots=True)
class LockedArtifact:
    distribution: str
    version: str
    filename: str
    url: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    python_version: str
    sys_platform: str
    machine: str
    artifacts: tuple[LockedArtifact, ...]


@dataclass(frozen=True, slots=True)
class _WheelMetadata:
    name: str
    version: str
    requirements: tuple[Any, ...]


def canonical_runtime_lock_sha256(payload: object) -> str:
    """Hash the semantic JSON document independently of whitespace and key order."""
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def load_runtime_lock(path: Path, *, pin: RuntimePin) -> RuntimeLock:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid runtime lock: {path.name}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "python_version",
        "sys_platform",
        "machine",
        "artifacts",
    }:
        raise RuntimeError("invalid runtime lock: top-level fields")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise RuntimeError("invalid runtime lock: schema version")
    expected_environment = (
        f"{sys.version_info.major}.{sys.version_info.minor}",
        sys.platform,
        platform.machine().casefold(),
    )
    observed_environment = (
        payload["python_version"],
        payload["sys_platform"],
        payload["machine"],
    )
    if observed_environment != expected_environment:
        raise RuntimeError("runtime lock does not match this Python platform")
    raw_artifacts = payload["artifacts"]
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise RuntimeError("invalid runtime lock: artifacts")
    if len(raw_artifacts) != pin.runtime_lock_artifact_count:
        raise RuntimeError("runtime lock artifact count does not match runtime pin")
    if canonical_runtime_lock_sha256(payload) != pin.runtime_lock_sha256:
        raise RuntimeError("runtime lock digest does not match runtime pin")

    artifacts = tuple(_load_artifact(item) for item in raw_artifacts)
    normalized_distributions = [_normalize_distribution(item.distribution) for item in artifacts]
    if normalized_distributions != sorted(normalized_distributions):
        raise RuntimeError("runtime lock artifacts must be sorted by normalized distribution")
    _require_unique(normalized_distributions, "normalized distribution")
    _require_unique([item.filename for item in artifacts], "wheel filename")
    _require_unique([_normalize_url(item.url) for item in artifacts], "artifact URL")
    _require_unique([item.sha256 for item in artifacts], "artifact SHA-256")

    by_distribution = {artifact.distribution: artifact for artifact in artifacts}
    pinned_sdk = by_distribution.get(_normalize_distribution(pin.distribution))
    if pinned_sdk is None or (
        pinned_sdk.version != pin.version
        or pinned_sdk.filename != pin.wheel_filename
        or pinned_sdk.sha256 != pin.wheel_sha256
    ):
        raise RuntimeError("runtime lock Mem0 artifact does not match runtime pin")
    return RuntimeLock(
        python_version=payload["python_version"],
        sys_platform=payload["sys_platform"],
        machine=payload["machine"],
        artifacts=artifacts,
    )


def verify_downloaded_artifacts(runtime_lock: RuntimeLock, directory: Path) -> None:
    expected_filenames = {artifact.filename for artifact in runtime_lock.artifacts}
    observed_filenames = {path.name for path in directory.glob("*.whl")}
    if observed_filenames != expected_filenames:
        raise RuntimeError("downloaded wheel set does not match runtime lock")
    for artifact in runtime_lock.artifacts:
        observed = hashlib.sha256((directory / artifact.filename).read_bytes()).hexdigest()
        if observed != artifact.sha256:
            raise RuntimeError(f"downloaded wheel failed SHA-256: {artifact.distribution}")


def verify_wheel_metadata_closure(runtime_lock: RuntimeLock, directory: Path) -> None:
    """Prove the active dependency closure from hash-verified wheel metadata."""
    verify_downloaded_artifacts(runtime_lock, directory)
    try:
        from packaging.markers import default_environment
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.utils import canonicalize_name
        from packaging.version import InvalidVersion, Version
    except ImportError as exc:
        raise RuntimeError("verified packaging wheel is required for metadata validation") from exc

    metadata_by_name: dict[str, _WheelMetadata] = {}
    for artifact in runtime_lock.artifacts:
        message = _read_wheel_metadata(directory / artifact.filename)
        names = message.get_all("Name", [])
        versions = message.get_all("Version", [])
        if len(names) != 1 or len(versions) != 1:
            raise RuntimeError(f"wheel METADATA identity is invalid: {artifact.filename}")
        metadata_name = canonicalize_name(names[0])
        metadata_version = versions[0]
        if metadata_name != artifact.distribution or metadata_version != artifact.version:
            raise RuntimeError(f"wheel METADATA identity disagrees with lock: {artifact.filename}")
        try:
            requirements = tuple(
                Requirement(value) for value in message.get_all("Requires-Dist", [])
            )
            Version(metadata_version)
        except (InvalidRequirement, InvalidVersion) as exc:
            raise RuntimeError(f"wheel METADATA is invalid: {artifact.filename}") from exc
        metadata_by_name[artifact.distribution] = _WheelMetadata(
            name=metadata_name,
            version=metadata_version,
            requirements=requirements,
        )

    environment = default_environment()
    contexts = {name: {""} for name in metadata_by_name}
    pending = deque((name, "") for name in metadata_by_name)
    while pending:
        name, active_extra = pending.popleft()
        for requirement in metadata_by_name[name].requirements:
            marker_environment = dict(environment)
            marker_environment["extra"] = active_extra
            if requirement.marker is not None and not requirement.marker.evaluate(
                marker_environment
            ):
                continue
            dependency = canonicalize_name(requirement.name)
            locked = metadata_by_name.get(dependency)
            if requirement.url is not None:
                raise RuntimeError(
                    f"active direct-URL dependency is forbidden: {name} -> {dependency}"
                )
            if locked is None:
                raise RuntimeError(f"active dependency is absent from lock: {name} -> {dependency}")
            if requirement.specifier and not requirement.specifier.contains(
                Version(locked.version), prereleases=True
            ):
                raise RuntimeError(
                    f"locked dependency version is incompatible: {name} -> {dependency}"
                )
            for requested_extra in sorted(requirement.extras):
                if requested_extra not in contexts[dependency]:
                    contexts[dependency].add(requested_extra)
                    pending.append((dependency, requested_extra))


def _read_wheel_metadata(path: Path):
    try:
        with ZipFile(path) as archive:
            members = [
                name
                for name in archive.namelist()
                if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
            ]
            if len(members) != 1:
                raise RuntimeError(f"wheel must contain exactly one METADATA file: {path.name}")
            raw_metadata = archive.read(members[0])
    except (BadZipFile, KeyError, OSError) as exc:
        raise RuntimeError(f"wheel archive is invalid: {path.name}") from exc
    return BytesParser(policy=default).parsebytes(raw_metadata)


def _load_artifact(value: object) -> LockedArtifact:
    if not isinstance(value, dict) or set(value) != {
        "distribution",
        "version",
        "filename",
        "url",
        "sha256",
    }:
        raise RuntimeError("invalid runtime lock artifact fields")
    if any(not isinstance(item, str) or not item for item in value.values()):
        raise RuntimeError("invalid runtime lock artifact values")
    artifact = LockedArtifact(**value)
    parsed_url = urlparse(artifact.url)
    wheel_distribution, wheel_version = _parse_wheel_filename(artifact.filename)
    if (
        not _DISTRIBUTION.fullmatch(artifact.distribution)
        or artifact.distribution != _normalize_distribution(artifact.distribution)
        or not _VERSION.fullmatch(artifact.version)
        or not _WHEEL_FILENAME.fullmatch(artifact.filename)
        or wheel_distribution != artifact.distribution
        or wheel_version != artifact.version
        or not _SHA256.fullmatch(artifact.sha256)
        or parsed_url.scheme != "https"
        or parsed_url.netloc != "files.pythonhosted.org"
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or unquote(parsed_url.path) != parsed_url.path
        or PurePosixPath(parsed_url.path).name != artifact.filename
    ):
        raise RuntimeError(f"invalid runtime lock artifact: {artifact.distribution}")
    return artifact


def _parse_wheel_filename(filename: str) -> tuple[str, str]:
    if not _WHEEL_FILENAME.fullmatch(filename):
        raise RuntimeError(f"invalid wheel filename: {filename}")
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) not in {5, 6} or any(not part for part in parts):
        raise RuntimeError(f"invalid wheel filename: {filename}")
    return _normalize_distribution(parts[0]), parts[1]


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _normalize_url(value: str) -> str:
    parsed = urlparse(value)
    return parsed._replace(
        scheme=parsed.scheme.casefold(), netloc=parsed.netloc.casefold()
    ).geturl()


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise RuntimeError(f"runtime lock contains a duplicate {label}")
