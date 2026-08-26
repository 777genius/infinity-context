"""Deployment-pinned public authority for Retrieval V2 runtime supervisors."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from infinity_context_core.features.context_building.public import InstalledReleaseIdentity


@dataclass(frozen=True, slots=True)
class SupervisorTrustRegistry:
    registry_id: str
    generation: int
    valid_from: datetime
    valid_until: datetime
    keys: tuple[tuple[str, str], ...]
    installed_release: InstalledReleaseIdentity
    root_sha256: str

    def public_key(self, key_id: str, *, now: datetime) -> str:
        if now.tzinfo is None:
            raise ValueError("Supervisor trust verification time must be timezone-aware")
        if not self.valid_from <= now < self.valid_until:
            raise RuntimeError("retrieval_profile_supervisor_trust_stale")
        matches = tuple(value for candidate, value in self.keys if candidate == key_id)
        if len(matches) != 1:
            raise RuntimeError("retrieval_profile_supervisor_key_untrusted")
        return matches[0]

    def verify_launch(self, owner, *, now: datetime) -> None:
        if owner.installed_release != self.installed_release:
            raise RuntimeError("retrieval_profile_supervisor_release_mismatch")
        if (
            owner.trust_root_sha256 != self.root_sha256
            or owner.trust_registry_generation != self.generation
        ):
            raise RuntimeError("retrieval_profile_supervisor_trust_mismatch")
        trusted_key = self.public_key(owner.supervisor_key_id, now=now)
        if owner.supervisor_public_key != trusted_key:
            raise RuntimeError("retrieval_profile_supervisor_key_untrusted")
        _verify(
            trusted_key, owner.launch_signature, owner.launch_payload(),
            error="retrieval_profile_runtime_launch_invalid"
        )

    def verify_death_proof(self, proof, *, now: datetime) -> None:
        if proof.installed_release != self.installed_release:
            raise RuntimeError("retrieval_profile_supervisor_release_mismatch")
        if (
            proof.trust_root_sha256 != self.root_sha256
            or proof.trust_registry_generation != self.generation
        ):
            raise RuntimeError("retrieval_profile_supervisor_trust_mismatch")
        trusted_key = self.public_key(proof.supervisor_key_id, now=now)
        _verify(
            trusted_key, proof.signature, proof.payload(),
            error="retrieval_profile_dead_proof_invalid"
        )

    def provenance(self) -> dict[str, object]:
        return {
            "supervisor_key_ids": [key_id for key_id, _ in self.keys],
            "supervisor_trust_registry_generation": self.generation,
            "supervisor_trust_root_sha256": self.root_sha256,
            "installed_release_identity": self.installed_release.payload(),
            "installed_release_identity_sha256": self.installed_release.digest(),
        }


def load_pinned_supervisor_trust(
    *,
    path: str,
    expected_root_sha256: str,
    expected_key_id: str,
    expected_generation: int,
    expected_release: InstalledReleaseIdentity,
    now: datetime | None = None,
) -> SupervisorTrustRegistry:
    """Load one non-substitutable public registry and match deployment pins exactly."""

    if not path or not os.path.isabs(path):
        raise RuntimeError("retrieval_profile_supervisor_trust_path_invalid")
    if len(expected_root_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in expected_root_sha256
    ):
        raise RuntimeError("retrieval_profile_supervisor_trust_digest_invalid")
    if (
        not expected_key_id
        or expected_key_id != expected_key_id.strip()
        or len(expected_key_id) > 120
    ):
        raise RuntimeError("retrieval_profile_supervisor_key_id_invalid")
    if (
        not isinstance(expected_generation, int)
        or isinstance(expected_generation, bool)
        or expected_generation < 1
    ):
        raise RuntimeError("retrieval_profile_supervisor_trust_generation_invalid")
    _assert_runtime_cannot_substitute(Path(path))
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024:
                raise RuntimeError("retrieval_profile_supervisor_trust_file_invalid")
            raw = os.read(descriptor, 64 * 1024 + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RuntimeError("retrieval_profile_supervisor_trust_unavailable") from exc
    registry = _parse_registry(raw)
    if registry.root_sha256 != expected_root_sha256:
        raise RuntimeError("retrieval_profile_supervisor_trust_digest_mismatch")
    if registry.generation != expected_generation:
        raise RuntimeError("retrieval_profile_supervisor_trust_generation_mismatch")
    if registry.installed_release != expected_release:
        raise RuntimeError("retrieval_profile_supervisor_release_mismatch")
    registry.public_key(expected_key_id, now=now or datetime.now(UTC))
    return registry


def registry_document(
    *, registry_id: str, generation: int, valid_from: datetime, valid_until: datetime,
    keys: tuple[tuple[str, str], ...], installed_release: InstalledReleaseIdentity
) -> tuple[bytes, str]:
    """Canonical public fixture/launcher representation; contains no private material."""

    payload = {
        "generation": generation,
        "keys": [{"key_id": key_id, "public_key": public_key} for key_id, public_key in keys],
        "registry_id": registry_id,
        "release_identity": installed_release.payload(),
        "schema": "retrieval-supervisor-trust-registry.v2",
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def _parse_registry(raw: bytes) -> SupervisorTrustRegistry:
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or set(decoded) != {
            "schema", "registry_id", "generation", "valid_from", "valid_until", "keys",
            "release_identity",
        } or decoded["schema"] != "retrieval-supervisor-trust-registry.v2":
            raise ValueError
        registry_id = decoded["registry_id"]
        generation = decoded["generation"]
        valid_from = datetime.fromisoformat(decoded["valid_from"])
        valid_until = datetime.fromisoformat(decoded["valid_until"])
        key_rows = decoded["keys"]
        release = InstalledReleaseIdentity(**decoded["release_identity"])
        if (
            not isinstance(registry_id, str)
            or not registry_id
            or registry_id != registry_id.strip()
            or len(registry_id) > 120
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1 or valid_from.tzinfo is None or valid_until.tzinfo is None
            or valid_from >= valid_until or not isinstance(key_rows, list) or not key_rows
        ):
            raise ValueError
        keys = []
        for row in key_rows:
            if not isinstance(row, dict) or set(row) != {"key_id", "public_key"}:
                raise ValueError
            key_id, public_key = row["key_id"], row["public_key"]
            if (
                not isinstance(key_id, str) or not key_id or key_id != key_id.strip()
                or len(key_id) > 120 or not isinstance(public_key, str) or len(public_key) != 64
                or any(c not in "0123456789abcdef" for c in public_key)
            ):
                raise ValueError
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
            keys.append((key_id, public_key))
        if len({key_id for key_id, _ in keys}) != len(keys):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("retrieval_profile_supervisor_trust_malformed") from exc
    canonical, digest = registry_document(
        registry_id=registry_id, generation=generation, valid_from=valid_from,
        valid_until=valid_until, keys=tuple(keys), installed_release=release
    )
    if canonical != raw:
        raise RuntimeError("retrieval_profile_supervisor_trust_noncanonical")
    return SupervisorTrustRegistry(
        registry_id, generation, valid_from, valid_until, tuple(keys), release, digest
    )


def _assert_runtime_cannot_substitute(path: Path) -> None:
    uid, groups = os.geteuid(), set(os.getgroups()) | {os.getegid()}
    if uid == 0:
        raise RuntimeError("retrieval_profile_supervisor_trust_runtime_writable")
    try:
        file_stat = path.lstat()
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or file_stat.st_uid == uid
            or _mode_writable(file_stat, uid, groups)
        ):
            raise RuntimeError("retrieval_profile_supervisor_trust_runtime_writable")
        child_stat = file_stat
        parent = path.parent
        while True:
            parent_stat = parent.lstat()
            if stat.S_ISLNK(parent_stat.st_mode):
                raise RuntimeError("retrieval_profile_supervisor_trust_runtime_writable")
            if parent_stat.st_uid == uid:
                raise RuntimeError("retrieval_profile_supervisor_trust_runtime_writable")
            if _mode_writable(parent_stat, uid, groups):
                sticky_protects = (
                    bool(parent_stat.st_mode & stat.S_ISVTX)
                    and parent_stat.st_uid != uid
                    and child_stat.st_uid != uid
                )
                if not sticky_protects:
                    raise RuntimeError("retrieval_profile_supervisor_trust_runtime_writable")
            if parent == parent.parent:
                break
            child_stat, parent = parent_stat, parent.parent
    except OSError as exc:
        raise RuntimeError("retrieval_profile_supervisor_trust_unavailable") from exc


def _mode_writable(metadata: os.stat_result, uid: int, groups: set[int]) -> bool:
    if metadata.st_uid == uid:
        return bool(metadata.st_mode & stat.S_IWUSR)
    if metadata.st_gid in groups:
        return bool(metadata.st_mode & stat.S_IWGRP)
    return bool(metadata.st_mode & stat.S_IWOTH)


def _verify(public_key: str, signature: str, payload: bytes, *, error: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(
            base64.b64decode(signature, validate=True), payload
        )
    except (ValueError, InvalidSignature) as exc:
        raise RuntimeError(error) from exc


__all__ = ("SupervisorTrustRegistry", "load_pinned_supervisor_trust", "registry_document")
