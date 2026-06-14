from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.main import create_app


def make_client(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            capture_mode=CaptureMode.SUGGEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-token"}
    if extra:
        headers.update(extra)
    return headers


def test_anchor_backfill_merge_and_split_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-anchor-lifecycle",
                "text": "Alex shared Project Atlas notes from meeting last week.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "text": "Алекс confirmed Project Atlas priorities after the call yesterday.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "fact-alex"}],
            },
            headers=auth_headers({"Idempotency-Key": "fact-alex"}),
        )
        assert fact.status_code == 201, fact.text

        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "title": "Atlas review notes",
                "text": "Project Atlas review mentions Alex and Qdrant document memory.",
                "source_type": "document",
                "source_external_id": "atlas-review-doc",
            },
            headers=auth_headers({"Idempotency-Key": "atlas-review-doc"}),
        )
        assert document.status_code == 201, document.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text
        backfill_data = backfill.json()["data"]
        assert backfill_data["created"] >= 4
        assert {item["source_type"] for item in backfill_data["sources"]} == {
            "capture",
            "fact",
            "chunk",
        }

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        active_anchors = anchors.json()["data"]
        keys = {(item["kind"], item["normalized_key"]) for item in active_anchors}
        assert ("person", "alex") in keys
        assert ("person", "алекс") in keys
        assert ("project", "atlas") in keys
        assert ("event", "meeting last week") in keys

        merge_suggestions = client.get(
            "/v1/anchors/merge-suggestions",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "person",
            },
            headers=auth_headers(),
        )
        assert merge_suggestions.status_code == 200, merge_suggestions.text
        candidates = merge_suggestions.json()["data"]["candidates"]
        alex_candidate = next(
            candidate
            for candidate in candidates
            if {
                candidate["source_anchor"]["normalized_key"],
                candidate["target_anchor"]["normalized_key"],
            }
            == {"alex", "алекс"}
        )
        assert alex_candidate["confidence"] in {"high", "medium"}
        assert alex_candidate["score"] >= 78

        merged = client.post(
            f"/v1/anchors/{alex_candidate['source_anchor']['id']}/merge",
            json={
                "target_anchor_id": alex_candidate["target_anchor"]["id"],
                "reason": "same person confirmed by reviewer",
            },
            headers=auth_headers(),
        )
        assert merged.status_code == 200, merged.text
        merged_anchor = merged.json()["data"]
        assert {
            "Alex",
            "Алекс",
        }.issubset(set(merged_anchor["aliases"]))
        assert merged_anchor["metadata"]["merged_anchor_ids"]

        deleted_source = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "status": "deleted",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert deleted_source.status_code == 200, deleted_source.text
        deleted = deleted_source.json()["data"]
        assert any(
            item["id"] == alex_candidate["source_anchor"]["id"]
            and item["metadata"]["merged_into_anchor_id"] == alex_candidate["target_anchor"]["id"]
            for item in deleted
        )

        split = client.post(
            f"/v1/anchors/{merged_anchor['id']}/split",
            json={
                "alias": "Алекс",
                "new_label": "Алексей",
                "reason": "reviewer split alias into a different person",
            },
            headers=auth_headers(),
        )
        assert split.status_code == 200, split.text
        split_anchor = split.json()["data"]
        assert split_anchor["normalized_key"] == "алексей"
        assert split_anchor["metadata"]["split_from_anchor_id"] == merged_anchor["id"]

        active_after_split = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "status": "active",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        by_id = {item["id"]: item for item in active_after_split.json()["data"]}
        assert "Алекс" not in by_id[merged_anchor["id"]]["aliases"]
