"""Authenticated singleton admission inventory and state initialization barrier."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from .domain import canonical_json_bytes, canonical_sha256
from .state_sqlite import SqliteOperationState, StateError

_SCHEMA = "mem0-oss-adapter-v5.admission-evidence.v1"


def bind_admission(
    *,
    directory: Path,
    hmac_key: bytes,
    admission: dict[str, object],
    inventory: tuple[dict[str, object], ...],
    state: SqliteOperationState,
    artifact_paths: tuple[Path, ...],
) -> str:
    """Initialize state once, then reject missing rows or changed inventory forever."""

    inventory_root = canonical_sha256(
        {
            "schema_version": "mem0-oss-adapter-v5.operation-inventory.v1",
            "admission_commitment_sha256": admission["admission_commitment_sha256"],
            "operations": inventory,
        }
    )
    expected = {
        "schema_version": _SCHEMA,
        "admission": admission,
        "inventory": list(inventory),
        "operation_inventory_root_sha256": inventory_root,
    }
    path = directory / "admission.json"
    phase = _load(path, expected=expected, hmac_key=hmac_key) if path.exists() else None
    if phase is None:
        if any(_row_exists(state, item["unit_identity_sha256"]) for item in inventory):
            raise ValueError("admission_state_unbound")
        if any(path.exists() for path in artifact_paths):
            raise ValueError("admission_state_unbound")
        _write(path, expected=expected, phase="initializing", hmac_key=hmac_key)
        phase = "initializing"
    if phase == "initializing":
        if any(path.exists() for path in artifact_paths):
            raise ValueError("admission_state_unbound")
        for item in inventory:
            state.admit(
                _text(item["unit_identity_sha256"]),
                _text(item["request_body_sha256"]),
            )
        _write(path, expected=expected, phase="initialized", hmac_key=hmac_key)
    for item in inventory:
        try:
            record = state.get(_text(item["unit_identity_sha256"]))
        except StateError:
            raise ValueError("admission_state_unbound") from None
        if record.request_sha256 != item["request_body_sha256"]:
            raise ValueError("admission_state_unbound")
    return inventory_root


def bind_cleanup_authority(
    *,
    directory: Path,
    hmac_key: bytes,
    expected: dict[str, object] | None,
) -> dict[str, object]:
    """Seal independently reconstructed cleanup commitments before deletion starts."""

    path = directory / "cleanup-authority.json"
    if path.exists():
        stored = _load_authority(path, hmac_key=hmac_key)
        if expected is not None and stored != expected:
            raise ValueError("cleanup_authority_conflict")
        return stored
    if expected is None:
        raise ValueError("cleanup_authority_missing")
    unsigned = {
        "schema_version": "mem0-oss-adapter-v5.cleanup-authority.v1",
        "commitments": expected,
    }
    signature = hmac.new(hmac_key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()
    _atomic_write(
        path,
        canonical_json_bytes({**unsigned, "evidence_hmac_sha256": signature}),
    )
    return expected


def _load_authority(path: Path, *, hmac_key: bytes) -> dict[str, object]:
    try:
        root = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("cleanup_authority_invalid") from None
    if type(root) is not dict or set(root) != {
        "schema_version",
        "commitments",
        "evidence_hmac_sha256",
    }:
        raise ValueError("cleanup_authority_invalid")
    signature = _digest(root.pop("evidence_hmac_sha256"))
    calculated = hmac.new(hmac_key, canonical_json_bytes(root), hashlib.sha256).hexdigest()
    commitments = root["commitments"]
    if (
        not hmac.compare_digest(signature, calculated)
        or root["schema_version"] != "mem0-oss-adapter-v5.cleanup-authority.v1"
        or type(commitments) is not dict
        or set(commitments)
        != {
            "seal_commitment_sha256",
            "operation_root_sha256",
            "operation_inventory_root_sha256",
        }
    ):
        raise ValueError("cleanup_authority_invalid")
    return commitments


def _row_exists(state: SqliteOperationState, identity: object) -> bool:
    try:
        state.get(_text(identity))
    except StateError:
        return False
    return True


def _load(path: Path, *, expected: dict[str, object], hmac_key: bytes) -> str:
    try:
        root = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("admission_evidence_invalid") from None
    if type(root) is not dict or set(root) != {*expected, "phase", "evidence_hmac_sha256"}:
        raise ValueError("admission_evidence_invalid")
    signature = _digest(root.pop("evidence_hmac_sha256"))
    unsigned = dict(root)
    calculated = hmac.new(hmac_key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, calculated):
        raise ValueError("admission_evidence_invalid")
    phase = root.pop("phase")
    if root != expected or phase not in {"initializing", "initialized"}:
        raise ValueError("admission_evidence_invalid")
    return phase


def _write(
    path: Path,
    *,
    expected: dict[str, object],
    phase: str,
    hmac_key: bytes,
) -> None:
    unsigned = {**expected, "phase": phase}
    signature = hmac.new(hmac_key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()
    _atomic_write(
        path,
        canonical_json_bytes({**unsigned, "evidence_hmac_sha256": signature}),
    )


def _atomic_write(path: Path, content: bytes) -> None:
    import os
    import tempfile

    descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _digest(value: object) -> str:
    text = _text(value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("admission_evidence_invalid")
    return text


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("admission_evidence_invalid")
    return value


__all__ = ("bind_admission", "bind_cleanup_authority")
