"""Git-friendly profile snapshot bundle helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "memo_stack.profile_snapshot_manifest.v1"


def default_manifest_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name(f"{snapshot_path.name}.manifest.json")


def write_snapshot_bundle(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    manifest_path: Path | None,
    space_slug: str,
    profile_external_ref: str,
    redacted: bool,
) -> dict[str, Any] | None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_bytes = _stable_json_bytes(snapshot)
    snapshot_path.write_bytes(snapshot_bytes)
    if manifest_path is None:
        return None
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        snapshot_bytes=snapshot_bytes,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        redacted=redacted,
    )
    manifest_path.write_bytes(_stable_json_bytes(manifest))
    return manifest


def build_snapshot_manifest(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    snapshot_bytes: bytes,
    space_slug: str,
    profile_external_ref: str,
    redacted: bool,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "snapshot_file": snapshot_path.name,
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "snapshot_bytes": len(snapshot_bytes),
        "space_slug": space_slug,
        "profile_external_ref": profile_external_ref,
        "redacted": redacted,
        "snapshot_schema_version": snapshot.get("schema_version"),
        "counts": {
            "facts": _list_count(snapshot.get("facts")),
            "documents": _list_count(snapshot.get("documents")),
            "chunks": _list_count(snapshot.get("chunks")),
            "source_refs": _list_count(snapshot.get("source_refs")),
        },
    }


def verify_snapshot_manifest(
    *,
    snapshot_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "errors": [f"manifest_unreadable:{exc.__class__.__name__}"],
        }
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest_not_object"]}
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported_manifest_schema")
    if manifest.get("snapshot_file") != snapshot_path.name:
        errors.append("snapshot_file_mismatch")
    try:
        snapshot_bytes = snapshot_path.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "errors": [*errors, f"snapshot_unreadable:{exc.__class__.__name__}"],
            "manifest": manifest,
        }
    actual_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
    expected_sha256 = str(manifest.get("snapshot_sha256") or "")
    if expected_sha256 != actual_sha256:
        errors.append("snapshot_sha256_mismatch")
    expected_size = manifest.get("snapshot_bytes")
    if isinstance(expected_size, int) and expected_size != len(snapshot_bytes):
        errors.append("snapshot_size_mismatch")
    return {
        "ok": not errors,
        "errors": errors,
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "snapshot_bytes": len(snapshot_bytes),
        "manifest": manifest,
    }


def _stable_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
