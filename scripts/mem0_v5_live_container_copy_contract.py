"""Public authority for UID-isolated Mem0 v5 container copies."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

CONTAINER_COPY_SCHEMA = "managed-mem0-v5-container-copy.v1"
CONTAINER_UID = 65_532
ADAPTER_SECRET_NAMES = (
    "account-binding-hmac-sha256",
    "base-instructions-sha256",
    "ingress-bearer",
    "result-hmac",
    "runtime-attestation-secret",
    "runtime-bearer",
    "runtime-receipt-secret",
    "runtime-transport-origin",
    "state-hmac",
)
_SHA256_CHARS = frozenset("0123456789abcdef")


def validate_private_credentials(
    *,
    secret_root: Path,
    runner_paths: dict[str, Path],
    evidence_key_sha256: str,
    read_private: Callable[..., bytes],
) -> dict[str, str]:
    if any(path != secret_root / name for name, path in runner_paths.items()):
        raise ValueError("mem0_v5_live_private_file_invalid")
    adapter_digests = {
        name: hashlib.sha256(read_private(secret_root / name, parent=secret_root)).hexdigest()
        for name in ADAPTER_SECRET_NAMES
    }
    runner_digests = {
        name: hashlib.sha256(read_private(path, parent=secret_root)).hexdigest()
        for name, path in runner_paths.items()
        if name not in adapter_digests
    }
    attestation_digest = adapter_digests["runtime-attestation-secret"]
    if any(
        digest == attestation_digest
        for name, digest in {**adapter_digests, **runner_digests}.items()
        if name != "runtime-attestation-secret"
    ):
        raise ValueError("mem0_v5_live_runtime_attestation_secret_not_distinct")
    if adapter_digests["result-hmac"] != evidence_key_sha256:
        raise ValueError("mem0_v5_live_evidence_key_commitment_differs")
    return adapter_digests


def verify_container_copy_authority(
    *,
    path: Path,
    expected_sha256: str,
    input_manifest_sha256: str,
    secret_digests: dict[str, str],
    maximum_bytes: int,
) -> None:
    raw = _read_public_immutable(path, expected_sha256, maximum_bytes=maximum_bytes)
    expected = {
        "schema_version": CONTAINER_COPY_SCHEMA,
        "container_uid": CONTAINER_UID,
        "container_gid": CONTAINER_UID,
        "directory_mode": "0700",
        "input": {
            "manifest.json": {
                "source_sha256": input_manifest_sha256,
                "prepared_sha256": input_manifest_sha256,
                "mode": "0400",
            }
        },
        "secrets": {
            name: {
                "source_sha256": digest,
                "prepared_sha256": digest,
                "mode": "0600",
            }
            for name, digest in sorted(secret_digests.items())
        },
        "state": {
            name: {"uid": CONTAINER_UID, "gid": CONTAINER_UID, "mode": "0700"}
            for name in ("adapter", "qdrant")
        },
    }
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("mem0_v5_live_container_copy_authority_invalid") from None
    if payload != expected:
        raise ValueError("mem0_v5_live_container_copy_authority_invalid")


def _read_public_immutable(path: Path, expected: str, *, maximum_bytes: int) -> bytes:
    if not path.is_absolute() or not _is_sha256(expected):
        raise ValueError("mem0_v5_live_public_immutable_invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(opened.st_mode) not in {0o400, 0o440, 0o444}
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= maximum_bytes
            or identity != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        ):
            raise ValueError
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, maximum_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum_bytes:
                raise ValueError
        final = os.fstat(descriptor)
        if identity != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise ValueError
        raw = b"".join(chunks)
    except (OSError, ValueError):
        raise ValueError("mem0_v5_live_public_immutable_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("mem0_v5_live_public_immutable_invalid")
    return raw


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA256_CHARS


__all__ = (
    "ADAPTER_SECRET_NAMES",
    "CONTAINER_COPY_SCHEMA",
    "CONTAINER_UID",
    "validate_private_credentials",
    "verify_container_copy_authority",
)
