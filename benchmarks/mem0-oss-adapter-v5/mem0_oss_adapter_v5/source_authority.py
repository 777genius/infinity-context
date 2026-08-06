"""External source-closure authority verified independently of dependency locks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import InitVar, dataclass
from pathlib import Path, PurePosixPath

from .domain import canonical_sha256

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SCHEMA = "mem0-oss-adapter-v5.source-authority.v1"
_ALGORITHM = "sha256(sorted(path + NUL + size + NUL + sha256 + LF))"
_MAX_FILES = 10_000
_MAX_FILE_BYTES = 64 * 1024 * 1024
_ISSUANCE_TOKEN = object()


class SourceAuthorityError(RuntimeError):
    """External authority or installed closure cannot be trusted."""


@dataclass(frozen=True, slots=True)
class VerifiedSourceAuthority:
    """Capability issued only after exact manifest and installed-tree verification."""

    source_commit_sha1: str
    source_tree_sha1: str
    manifest_sha256: str
    closure_sha256: str
    phase_c_infinity_commit_sha1: str
    phase_c_infinity_tree_sha1: str
    phase_c_release_manifest_sha256: str
    _issuance: InitVar[object]

    def __post_init__(self, issuance: object) -> None:
        if issuance is not _ISSUANCE_TOKEN:
            raise TypeError("verified source authority requires verified issuance")

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("verified source authority cannot be subclassed")

    def binding_commitment(
        self,
        *,
        route_sha256: str,
        runtime_binding_commitment_sha256: str,
        runtime_source_sha256: str,
        runtime_route_binding_sha256: str,
        runtime_transport_origin_sha256: str,
    ) -> str:
        return canonical_sha256(
            {
                "route_sha256": route_sha256,
                "manifest_sha256": self.manifest_sha256,
                "source_closure_sha256": self.closure_sha256,
                "source_commit_sha1": self.source_commit_sha1,
                "source_tree_sha1": self.source_tree_sha1,
                "phase_c_infinity_commit_sha1": self.phase_c_infinity_commit_sha1,
                "phase_c_infinity_tree_sha1": self.phase_c_infinity_tree_sha1,
                "phase_c_release_manifest_sha256": self.phase_c_release_manifest_sha256,
                "runtime_binding_commitment_sha256": runtime_binding_commitment_sha256,
                "runtime_source_sha256": runtime_source_sha256,
                "runtime_route_binding_sha256": runtime_route_binding_sha256,
                "runtime_transport_origin_sha256": runtime_transport_origin_sha256,
            }
        )


def verify_source_authority(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    installed_root: Path,
    phase_c_authority_root: Path,
) -> VerifiedSourceAuthority:
    try:
        manifest_path.resolve(strict=True).relative_to(installed_root.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise SourceAuthorityError("source_authority_self_trust_invalid")
    expected_manifest = _sha256(expected_manifest_sha256)
    manifest_bytes = _read_bytes(manifest_path, maximum=8 * 1024 * 1024)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if not hmac.compare_digest(manifest_sha, expected_manifest):
        raise SourceAuthorityError("source_authority_pin_invalid")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourceAuthorityError("source_authority_manifest_invalid") from None
    root = _exact(
        manifest,
        {
            "schema_version",
            "source_commit_sha1",
            "source_tree_sha1",
            "closure_algorithm",
            "closure_sha256",
            "files",
            "phase_c_authority",
        },
    )
    if root["schema_version"] != _SCHEMA or root["closure_algorithm"] != _ALGORITHM:
        raise SourceAuthorityError("source_authority_schema_invalid")
    commit = _sha1(root["source_commit_sha1"])
    tree = _sha1(root["source_tree_sha1"])
    expected_closure = _sha256(root["closure_sha256"])
    phase = _exact(
        root["phase_c_authority"],
        {"infinity_commit_sha1", "infinity_tree_sha1", "release_manifest_sha256"},
    )
    phase_commit = _sha1(phase["infinity_commit_sha1"])
    phase_tree = _sha1(phase["infinity_tree_sha1"])
    release_sha = _sha256(phase["release_manifest_sha256"])
    files = _files(root["files"])
    actual = _installed_files(installed_root)
    if set(actual) != set(files):
        raise SourceAuthorityError("source_authority_inventory_invalid")
    rows = []
    for relative in sorted(files):
        expected_size, expected_sha = files[relative]
        size, digest = actual[relative]
        if (size, digest) != (expected_size, expected_sha):
            raise SourceAuthorityError("source_authority_file_invalid")
        rows.append(f"{relative}\0{size}\0{digest}\n")
    calculated = hashlib.sha256("".join(rows).encode()).hexdigest()
    if calculated != expected_closure:
        raise SourceAuthorityError("source_authority_closure_invalid")
    _verify_phase_c_authority(
        phase_c_authority_root,
        commit=phase_commit,
        tree=phase_tree,
        release_manifest_sha256=release_sha,
    )
    return _issue_verified_source_authority(
        source_commit_sha1=commit,
        source_tree_sha1=tree,
        manifest_sha256=manifest_sha,
        closure_sha256=calculated,
        phase_c_infinity_commit_sha1=phase_commit,
        phase_c_infinity_tree_sha1=phase_tree,
        phase_c_release_manifest_sha256=release_sha,
    )


def _issue_verified_source_authority(**values: object) -> VerifiedSourceAuthority:
    return VerifiedSourceAuthority(**values, _issuance=_ISSUANCE_TOKEN)  # type: ignore[arg-type]


def _files(value: object) -> dict[str, tuple[int, str]]:
    if type(value) is not list or not 1 <= len(value) <= _MAX_FILES:
        raise SourceAuthorityError("source_authority_inventory_invalid")
    result = {}
    for value_item in value:
        item = _exact(value_item, {"path", "size", "sha256"})
        relative = _relative(item["path"])
        size = item["size"]
        if type(size) is not int or not 0 <= size <= _MAX_FILE_BYTES or relative in result:
            raise SourceAuthorityError("source_authority_inventory_invalid")
        result[relative] = (size, _sha256(item["sha256"]))
    return result


def _installed_files(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise SourceAuthorityError("source_authority_root_invalid")
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SourceAuthorityError("source_authority_symlink_invalid")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SourceAuthorityError("source_authority_file_invalid")
        relative = path.relative_to(root).as_posix()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_FILE_BYTES:
                raise SourceAuthorityError("source_authority_file_invalid")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 64 * 1024):
                digest.update(chunk)
            current = path.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise SourceAuthorityError("source_authority_file_changed")
            result[relative] = (opened.st_size, digest.hexdigest())
        finally:
            os.close(descriptor)
    return result


def _verify_phase_c_authority(
    root: Path,
    *,
    commit: str,
    tree: str,
    release_manifest_sha256: str,
) -> None:
    if not root.is_absolute():
        raise SourceAuthorityError("phase_c_authority_invalid")
    _require_real_directory_chain(root)
    attestation = root / "attestation"
    _require_real_directory_chain(attestation)
    values = {
        "commit.txt": commit,
        "tree.txt": tree,
    }
    for name, expected in values.items():
        raw = _read_bytes(attestation / name, maximum=128)
        if raw.decode().strip() != expected:
            raise SourceAuthorityError("phase_c_authority_invalid")
    release = _read_bytes(attestation / "release-files.sha256", maximum=8 * 1024 * 1024)
    if hashlib.sha256(release).hexdigest() != release_manifest_sha256:
        raise SourceAuthorityError("phase_c_authority_invalid")


def _require_real_directory_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError:
            raise SourceAuthorityError("phase_c_authority_invalid") from None
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SourceAuthorityError("phase_c_authority_invalid")


def _read_bytes(path: Path, *, maximum: int) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SourceAuthorityError("source_authority_manifest_invalid")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= maximum:
        raise SourceAuthorityError("source_authority_manifest_invalid")
    return raw


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise SourceAuthorityError("source_authority_manifest_invalid")
    return value


def _relative(value: object) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise SourceAuthorityError("source_authority_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceAuthorityError("source_authority_path_invalid")
    return path.as_posix()


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise SourceAuthorityError("source_authority_digest_invalid")
    return value


def _sha1(value: object) -> str:
    if type(value) is not str or _SHA1.fullmatch(value) is None:
        raise SourceAuthorityError("source_authority_revision_invalid")
    return value


__all__ = ("SourceAuthorityError", "VerifiedSourceAuthority", "verify_source_authority")
