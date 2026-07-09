from __future__ import annotations

from copy import deepcopy

import pytest
from infinity_context_core.memory_scope_snapshots import (
    build_snapshot_manifest,
    verify_snapshot_manifest_payload,
)
from infinity_context_server.features.memory_scopes import public as server_public


def test_snapshot_manifest_verification_rejects_tampered_counts() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    tampered = deepcopy(manifest)
    tampered["counts"]["facts"] = 99

    verification = verify_snapshot_manifest_payload(snapshot=snapshot, manifest=tampered)

    assert verification["ok"] is False
    assert verification["actual_sha256"] == verification["expected_sha256"]
    assert verification["errors"] == ["count_mismatch:facts"]


def test_snapshot_manifest_verification_rejects_schema_version_mismatch() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    tampered = deepcopy(manifest)
    tampered["snapshot_schema_version"] = 8

    verification = verify_snapshot_manifest_payload(snapshot=snapshot, manifest=tampered)

    assert verification["ok"] is False
    assert verification["errors"] == ["snapshot_schema_version_mismatch"]


def test_snapshot_manifest_verification_rejects_redacted_mismatch() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    tampered = deepcopy(manifest)
    tampered["redacted"] = True

    verification = verify_snapshot_manifest_payload(snapshot=snapshot, manifest=tampered)

    assert verification["ok"] is False
    assert verification["errors"] == ["redacted_mismatch"]


def test_snapshot_manifest_verification_rejects_missing_counts_contract() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    tampered = deepcopy(manifest)
    tampered.pop("counts")

    verification = verify_snapshot_manifest_payload(snapshot=snapshot, manifest=tampered)

    assert verification["ok"] is False
    assert verification["errors"] == ["counts_missing"]


def test_memory_scopes_public_seam_builds_snapshot_export_envelope() -> None:
    snapshot = _snapshot()

    response = server_public.memory_scope_snapshot_export_response(
        result={
            "status": "ok",
            "snapshot": snapshot,
            "counts": {"facts": 1},
            "redacted": False,
        },
        space_slug="team",
        memory_scope_external_ref="atlas",
    )

    assert response["data"] is snapshot
    assert response["status"] == "ok"
    assert response["counts"] == {"facts": 1}
    assert response["redacted"] is False
    assert response["manifest"]["space_slug"] == "team"
    assert response["manifest"]["memory_scope_external_ref"] == "atlas"
    assert verify_snapshot_manifest_payload(
        snapshot=snapshot,
        manifest=response["manifest"],
    )["ok"] is True
    assert server_public.memory_scope_snapshot_export_response(
        result={"status": "not_found"},
        space_slug="team",
        memory_scope_external_ref="missing",
    ) == {"data": None, "status": "not_found"}


def test_memory_scopes_public_seam_validates_snapshot_import_requests() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    request = server_public.ImportMemoryScopeSnapshotRequest(
        space_slug="team",
        memory_scope_external_ref="atlas",
        snapshot=snapshot,
        manifest=manifest,
        dry_run=True,
        merge_strategy="fail_on_conflict",
    )

    server_public.validate_memory_scope_snapshot_import_request(
        request,
        supported_merge_strategies={"fail_on_conflict"},
    )

    with pytest.raises(
        server_public.MemoryScopeSnapshotCompatibilityError,
        match="Unsupported memory_scope snapshot merge strategy",
    ):
        server_public.validate_memory_scope_snapshot_preview_request(
            server_public.PreviewMemoryScopeSnapshotRequest(
                space_slug="team",
                memory_scope_external_ref="atlas",
                snapshot=snapshot,
                merge_strategy="replace",
            ),
            supported_merge_strategies={"fail_on_conflict"},
        )

    with pytest.raises(
        server_public.MemoryScopeSnapshotCompatibilityError,
        match="requires confirmed=true",
    ):
        server_public.validate_memory_scope_snapshot_import_request(
            server_public.ImportMemoryScopeSnapshotRequest(
                space_slug="team",
                memory_scope_external_ref="atlas",
                snapshot=snapshot,
                dry_run=False,
                merge_strategy="fail_on_conflict",
            ),
            supported_merge_strategies={"fail_on_conflict"},
        )


def test_memory_scopes_public_seam_rejects_snapshot_manifest_mismatch() -> None:
    snapshot = _snapshot()
    manifest = build_snapshot_manifest(
        snapshot=snapshot,
        space_slug="team",
        memory_scope_external_ref="atlas",
        redacted=False,
    )
    tampered = deepcopy(snapshot)
    tampered["facts"] = []

    with pytest.raises(
        server_public.MemoryScopeSnapshotCompatibilityError,
        match="count_mismatch:facts",
    ):
        server_public.verify_memory_scope_snapshot_manifest(tampered, manifest)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": 9,
        "redacted": False,
        "threads": [{"id": "thread_1"}],
        "facts": [{"id": "fact_1"}],
        "documents": [],
        "episodes": [],
        "chunks": [{"id": "chunk_1"}],
        "assets": [],
        "asset_blobs": [],
        "asset_extraction_jobs": [],
        "extraction_artifacts": [],
        "extraction_artifact_blobs": [],
        "captures": [],
        "anchors": [{"id": "anchor_1"}],
        "context_links": [],
        "context_link_suggestions": [],
        "relations": [],
        "source_refs": [],
    }
