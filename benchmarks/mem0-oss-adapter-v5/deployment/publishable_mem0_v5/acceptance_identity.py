"""Path-independent identity for the installed Docker acceptance driver."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .config import PublishableLaneConfig

_CLOSURE_SCHEMA: Final = "publishable-mem0-v5-acceptance-driver-closure.v1"
ACCEPTANCE_DRIVER_IDENTITY_KIND: Final = "authenticated-package-closure-v1"
_GIT_STATUS: Final = "NOT_EMBEDDED_IN_INSTALLED_ARTIFACT"
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_FILES = 128
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_REQUIRED_FILES = {
    "acceptance.py",
    "acceptance_attestation.py",
    "acceptance_identity.py",
    "cli.py",
    "config.py",
    "deployment.py",
    "docker_cli.py",
    "immutable_evidence.py",
    "provider_attestation.py",
    "runtime_attestation.py",
}


class AcceptanceDriverIdentityError(RuntimeError):
    """Stable failure for an unbound or changed installed driver."""


@dataclass(frozen=True, slots=True)
class AcceptanceDriverIdentity:
    package_closure_sha256: str
    deployment_closure_sha256: str
    deployment_closure_hmac_sha256: str
    file_count: int
    total_bytes: int

    def payload(self) -> dict[str, object]:
        return {
            "git_commit": {"status": _GIT_STATUS},
            "identity_kind": ACCEPTANCE_DRIVER_IDENTITY_KIND,
            "file_count": self.file_count,
            "package_closure_sha256": self.package_closure_sha256,
            "schema_version": _CLOSURE_SCHEMA,
            "total_bytes": self.total_bytes,
        }

    def deployment_authority_payload(self, *, deployment_inputs_sha256: str) -> dict[str, str]:
        return {
            "deployment_closure_hmac_sha256": self.deployment_closure_hmac_sha256,
            "deployment_closure_sha256": self.deployment_closure_sha256,
            "deployment_inputs_sha256": deployment_inputs_sha256,
        }


@dataclass(frozen=True, slots=True)
class _SourceClosure:
    sha256: str
    files: tuple[tuple[str, int, str], ...]
    total_bytes: int


def attest_acceptance_driver(config: PublishableLaneConfig) -> AcceptanceDriverIdentity:
    """Require installed package files to equal the configured deployment copy."""

    if type(config) is not PublishableLaneConfig:
        _fail("publishable_acceptance_driver_input_invalid")
    installed = _measure_package_closure(Path(__file__).parent)
    _require_single_package_origin(Path(__file__).parent)
    deployed = _measure_package_closure(config.paths.deployment_dir / "publishable_mem0_v5")
    if installed != deployed:
        _fail("publishable_acceptance_driver_deployment_mismatch")
    return AcceptanceDriverIdentity(
        package_closure_sha256=installed.sha256,
        deployment_closure_sha256=config.bind_mount_authority.deployment_closure_sha256,
        deployment_closure_hmac_sha256=(config.bind_mount_authority.deployment_closure_hmac_sha256),
        file_count=len(installed.files),
        total_bytes=installed.total_bytes,
    )


def require_acceptance_driver_unchanged(
    expected: AcceptanceDriverIdentity,
    config: PublishableLaneConfig,
) -> AcceptanceDriverIdentity:
    if type(expected) is not AcceptanceDriverIdentity:
        _fail("publishable_acceptance_driver_input_invalid")
    observed = attest_acceptance_driver(config)
    if observed != expected:
        _fail("publishable_acceptance_driver_changed")
    return observed


def _measure_package_closure(root: Path) -> _SourceClosure:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise AcceptanceDriverIdentityError("publishable_acceptance_driver_unavailable") from exc
    if (
        not root.is_absolute()
        or stat.S_ISLNK(root_stat.st_mode)
        or not stat.S_ISDIR(root_stat.st_mode)
    ):
        _fail("publishable_acceptance_driver_unsafe")
    paths: list[Path] = []
    try:
        for current, directories, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            current_stat = current_path.lstat()
            if (
                stat.S_ISLNK(current_stat.st_mode)
                or not stat.S_ISDIR(current_stat.st_mode)
                or current_stat.st_mode & 0o022
            ):
                _fail("publishable_acceptance_driver_unsafe")
            for name in directories:
                child = (current_path / name).lstat()
                if stat.S_ISLNK(child.st_mode) or not stat.S_ISDIR(child.st_mode):
                    _fail("publishable_acceptance_driver_unsafe")
            paths.extend(
                current_path / name
                for name in names
                if "__pycache__" not in (current_path / name).relative_to(root).parts
            )
    except OSError as exc:
        raise AcceptanceDriverIdentityError("publishable_acceptance_driver_unavailable") from exc
    relative_names = {
        path.relative_to(root).as_posix() for path in paths if path.name.endswith(".py")
    }
    if not relative_names >= _REQUIRED_FILES or not 1 <= len(paths) <= _MAX_FILES:
        _fail("publishable_acceptance_driver_inventory_invalid")
    files: list[tuple[str, int, str]] = []
    total = 0
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        raw = _read_source(path)
        total += len(raw)
        if total > _MAX_TOTAL_BYTES:
            _fail("publishable_acceptance_driver_inventory_invalid")
        files.append((relative, len(raw), hashlib.sha256(raw).hexdigest()))
    payload = {
        "files": [{"path": name, "sha256": digest, "size": size} for name, size, digest in files],
        "schema_version": _CLOSURE_SCHEMA,
    }
    return _SourceClosure(
        sha256=hashlib.sha256(_canonical_json(payload)).hexdigest(),
        files=tuple(files),
        total_bytes=total,
    )


def _read_source(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            _fail("publishable_acceptance_driver_unsafe")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
            or not 1 <= opened.st_size <= _MAX_FILE_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            _fail("publishable_acceptance_driver_unsafe")
        raw = _read_exact(descriptor, opened.st_size)
        final = os.fstat(descriptor)
        if (
            opened.st_mode,
            opened.st_uid,
            opened.st_gid,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (
            final.st_mode,
            final.st_uid,
            final.st_gid,
            final.st_size,
            final.st_mtime_ns,
        ):
            _fail("publishable_acceptance_driver_changed")
        return raw
    except AcceptanceDriverIdentityError:
        raise
    except OSError as exc:
        raise AcceptanceDriverIdentityError("publishable_acceptance_driver_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        value = os.read(descriptor, min(64 * 1024, remaining))
        if not value:
            _fail("publishable_acceptance_driver_changed")
        chunks.append(value)
        remaining -= len(value)
    if os.read(descriptor, 1):
        _fail("publishable_acceptance_driver_changed")
    return b"".join(chunks)


def _require_single_package_origin(root: Path) -> None:
    try:
        expected = root.resolve(strict=True)
        for name, module in tuple(sys.modules.items()):
            if name != "publishable_mem0_v5" and not name.startswith("publishable_mem0_v5."):
                continue
            origin = getattr(module, "__file__", None)
            if origin is None:
                continue
            if not Path(origin).resolve(strict=True).is_relative_to(expected):
                _fail("publishable_acceptance_driver_mixed_origin")
    except AcceptanceDriverIdentityError:
        raise
    except OSError as exc:
        raise AcceptanceDriverIdentityError("publishable_acceptance_driver_unavailable") from exc


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _fail(code: str) -> None:
    raise AcceptanceDriverIdentityError(code)


__all__ = (
    "ACCEPTANCE_DRIVER_IDENTITY_KIND",
    "AcceptanceDriverIdentity",
    "AcceptanceDriverIdentityError",
    "attest_acceptance_driver",
    "require_acceptance_driver_unchanged",
)
