"""Compatibility helpers for the legacy memory_scope snapshot export API."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, cast

from infinity_context_core.memory_scope_snapshots import (
    build_snapshot_manifest,
    verify_snapshot_manifest_payload,
)
from pydantic import BaseModel, ConfigDict, Field


class MemoryScopeSnapshotCompatibilityError(ValueError):
    """Raised when a snapshot compatibility request is invalid."""


class ImportMemoryScopeSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_slug: str = Field(min_length=1, max_length=160)
    memory_scope_external_ref: str = Field(min_length=1, max_length=200)
    snapshot: dict[str, Any]
    manifest: dict[str, Any] | None = None
    dry_run: bool = True
    merge_strategy: str = Field(default="fail_on_conflict", max_length=80)
    confirmed: bool = False
    source_name: str = Field(default="api-memory_scope-snapshot", max_length=160)


class PreviewMemoryScopeSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_slug: str = Field(min_length=1, max_length=160)
    memory_scope_external_ref: str = Field(min_length=1, max_length=200)
    snapshot: dict[str, Any]
    manifest: dict[str, Any] | None = None
    merge_strategy: str = Field(default="fail_on_conflict", max_length=80)


def validate_memory_scope_snapshot_import_request(
    request: ImportMemoryScopeSnapshotRequest,
    *,
    supported_merge_strategies: Collection[str],
) -> None:
    """Validate snapshot import compatibility fields before route orchestration."""

    _ensure_supported_merge_strategy(
        request.merge_strategy,
        supported_merge_strategies=supported_merge_strategies,
    )
    if not request.dry_run and not request.confirmed:
        raise MemoryScopeSnapshotCompatibilityError(
            "MemoryScope snapshot import requires confirmed=true"
        )
    verify_memory_scope_snapshot_manifest(request.snapshot, request.manifest)


def validate_memory_scope_snapshot_preview_request(
    request: PreviewMemoryScopeSnapshotRequest,
    *,
    supported_merge_strategies: Collection[str],
) -> None:
    """Validate snapshot preview compatibility fields before route orchestration."""

    _ensure_supported_merge_strategy(
        request.merge_strategy,
        supported_merge_strategies=supported_merge_strategies,
    )
    verify_memory_scope_snapshot_manifest(request.snapshot, request.manifest)


def verify_memory_scope_snapshot_manifest(
    snapshot: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> None:
    """Verify an optional snapshot manifest and raise a compatibility error on failure."""

    if manifest is None:
        return
    verification = verify_snapshot_manifest_payload(
        snapshot=snapshot,
        manifest=manifest,
        expected_snapshot_file=None,
    )
    if not verification["ok"]:
        errors = ", ".join(verification["errors"])
        raise MemoryScopeSnapshotCompatibilityError(
            f"MemoryScope snapshot manifest verification failed: {errors}"
        )


def memory_scope_snapshot_export_response(
    *,
    result: Mapping[str, object],
    space_slug: str,
    memory_scope_external_ref: str,
) -> dict[str, Any]:
    """Return the legacy response envelope for a memory_scope snapshot export."""

    if result["status"] != "ok":
        return {"data": None, "status": result["status"]}
    snapshot = cast(dict[str, Any], result["snapshot"])
    redacted = bool(result["redacted"])
    return {
        "data": snapshot,
        "status": "ok",
        "counts": result["counts"],
        "redacted": redacted,
        "manifest": build_snapshot_manifest(
            snapshot=snapshot,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            redacted=redacted,
        ),
    }


def memory_scope_snapshot_transfer_response(result: Mapping[str, object]) -> dict[str, Any]:
    """Return the legacy response envelope for snapshot import and preview transfers."""

    return {"data": result}


def _ensure_supported_merge_strategy(
    merge_strategy: str,
    *,
    supported_merge_strategies: Collection[str],
) -> None:
    if merge_strategy not in supported_merge_strategies:
        raise MemoryScopeSnapshotCompatibilityError(
            "Unsupported memory_scope snapshot merge strategy"
        )


__all__ = (
    "ImportMemoryScopeSnapshotRequest",
    "MemoryScopeSnapshotCompatibilityError",
    "PreviewMemoryScopeSnapshotRequest",
    "memory_scope_snapshot_export_response",
    "memory_scope_snapshot_transfer_response",
    "validate_memory_scope_snapshot_import_request",
    "validate_memory_scope_snapshot_preview_request",
    "verify_memory_scope_snapshot_manifest",
)
