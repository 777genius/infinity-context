from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_core.profile_snapshots import verify_snapshot_manifest_payload
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_profile_snapshot_export_dry_run_and_confirmed_import(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "text": "SNAPSHOT_API_MARKER: profile snapshots are portable.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "snapshot-api"}],
                "category": "architecture",
                "tags": ["snapshot"],
                "ttl_policy": "durable",
            },
            headers=auth_headers(),
        )
        exported = client.get(
            "/v1/export/profile-snapshot",
            params={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "redacted": False,
            },
            headers=auth_headers(),
        )
        snapshot = exported.json()["data"]
        manifest = exported.json()["manifest"]
        dry_run = client.post(
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": "agents",
                "profile_external_ref": "restore-base",
                "snapshot": snapshot,
                "manifest": manifest,
                "dry_run": True,
                "merge_strategy": "create_new_profile",
            },
            headers=auth_headers(),
        )
        refused = client.post(
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": "agents",
                "profile_external_ref": "restore-base",
                "snapshot": snapshot,
                "dry_run": False,
                "merge_strategy": "create_new_profile",
                "confirmed": False,
            },
            headers=auth_headers(),
        )
        imported = client.post(
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": "agents",
                "profile_external_ref": "restore-base",
                "snapshot": snapshot,
                "manifest": manifest,
                "dry_run": False,
                "merge_strategy": "create_new_profile",
                "confirmed": True,
                "source_name": "unit-profile-snapshot",
            },
            headers=auth_headers(),
        )
        created_profile = imported.json()["data"]["created_profile"]
        restored = client.get(
            "/v1/facts",
            params={
                "space_slug": "agents",
                "profile_external_ref": created_profile["external_ref"],
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert exported.status_code == 200
    assert exported.json()["counts"]["facts"] == 1
    assert snapshot["schema_version"] == 1
    assert manifest["schema_version"] == "memo_stack.profile_snapshot_manifest.v1"
    assert manifest["snapshot_sha256"]
    assert verify_snapshot_manifest_payload(snapshot=snapshot, manifest=manifest)["ok"] is True
    assert snapshot["facts"][0]["text"] == "SNAPSHOT_API_MARKER: profile snapshots are portable."
    assert snapshot["facts"][0]["category"] == "architecture"
    assert snapshot["facts"][0]["tags"] == ["snapshot"]
    assert dry_run.status_code == 200
    assert dry_run.json()["data"]["dry_run"] is True
    assert dry_run.json()["data"]["would_create_profile"] is True
    assert dry_run.json()["data"]["would_import"]["facts"] == 1
    assert refused.status_code == 400
    assert imported.status_code == 200
    assert imported.json()["data"]["merge_strategy"] == "create_new_profile"
    assert restored.status_code == 200
    assert restored.json()["data"][0]["text"] == snapshot["facts"][0]["text"]
    assert restored.json()["data"][0]["id"] != created.json()["data"]["id"]


def test_profile_snapshot_import_rejects_manifest_mismatch(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "text": "SNAPSHOT_API_TAMPER_MARKER: manifest catches edits.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "snapshot-tamper"}],
            },
            headers=auth_headers(),
        )
        exported = client.get(
            "/v1/export/profile-snapshot",
            params={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "redacted": False,
            },
            headers=auth_headers(),
        )
        snapshot = exported.json()["data"]
        snapshot["facts"][0]["text"] = "tampered"
        imported = client.post(
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": "agents",
                "profile_external_ref": "restore-base",
                "snapshot": snapshot,
                "manifest": exported.json()["manifest"],
                "dry_run": True,
            },
            headers=auth_headers(),
        )

    assert imported.status_code == 400
    assert "manifest verification failed" in imported.text
    assert "snapshot_sha256_mismatch" in imported.text


def test_profile_snapshot_import_refuses_redacted_memory(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/v1/facts",
            json={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "text": "Redacted snapshots are export-only.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "snapshot-redacted"}],
            },
            headers=auth_headers(),
        )
        exported = client.get(
            "/v1/export/profile-snapshot",
            params={
                "space_slug": "agents",
                "profile_external_ref": "source-profile",
                "redacted": True,
            },
            headers=auth_headers(),
        )
        imported = client.post(
            "/v1/export/profile-snapshot/import",
            json={
                "space_slug": "agents",
                "profile_external_ref": "restore-base",
                "snapshot": exported.json()["data"],
                "dry_run": False,
                "merge_strategy": "create_new_profile",
                "confirmed": True,
            },
            headers=auth_headers(),
        )

    assert exported.status_code == 200
    assert exported.json()["data"]["redacted"] is True
    assert exported.json()["data"]["facts"][0]["text"] is None
    assert imported.status_code == 200
    assert imported.json()["data"]["status"] == "refused"
    assert imported.json()["data"]["reason"] == "redacted_profile_export_cannot_be_imported"
