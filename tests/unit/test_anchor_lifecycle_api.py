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

        manual_anchor = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": ["Project Atlas"],
                "description": "Manual project anchor created by reviewer.",
                "confidence": "high",
                "evidence_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "manual-anchor-atlas",
                        "quote_preview": "Reviewer confirmed Atlas is the canonical project.",
                    }
                ],
                "observed_at": "2026-01-02T03:04:05+00:00",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_to": "2026-12-31T23:59:59+00:00",
            },
            headers=auth_headers(),
        )
        assert manual_anchor.status_code == 200, manual_anchor.text
        manual_anchor_data = manual_anchor.json()["data"]
        assert manual_anchor_data["kind"] == "project"
        assert manual_anchor_data["normalized_key"] == "atlas"
        assert "Project Atlas" in manual_anchor_data["aliases"]
        assert manual_anchor_data["confidence"] == "high"
        assert manual_anchor_data["evidence_refs"] == [
            {
                "source_type": "manual",
                "source_id": "manual-anchor-atlas",
                "chunk_id": None,
                "char_start": None,
                "char_end": None,
                "quote_preview": "Reviewer confirmed Atlas is the canonical project.",
            }
        ]
        assert manual_anchor_data["observed_at"] == "2026-01-02T03:04:05+00:00"
        assert manual_anchor_data["valid_from"] == "2026-01-01T00:00:00+00:00"
        assert manual_anchor_data["valid_to"] == "2026-12-31T23:59:59+00:00"
        assert manual_anchor_data["metadata"]["creation_source"] == "manual"

        manual_anchor_duplicate = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": ["Atlas roadmap"],
                "description": "Updated manual project anchor.",
            },
            headers=auth_headers(),
        )
        assert manual_anchor_duplicate.status_code == 200, manual_anchor_duplicate.text
        duplicate_data = manual_anchor_duplicate.json()["data"]
        assert duplicate_data["id"] == manual_anchor_data["id"]
        assert "Atlas roadmap" in duplicate_data["aliases"]
        assert duplicate_data["description"] == "Updated manual project anchor."

        edited_anchor = client.patch(
            f"/v1/anchors/{manual_anchor_data['id']}",
            json={
                "label": "Atlas Roadmap",
                "aliases": ["Project Atlas", "Atlas delivery"],
                "description": "Edited manual project anchor.",
                "confidence": "medium",
                "evidence_refs": [
                    {
                        "source_type": "document",
                        "source_id": "atlas-roadmap-doc",
                        "chunk_id": "chunk-1",
                    }
                ],
                "observed_at": "2026-01-03T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        assert edited_anchor.status_code == 200, edited_anchor.text
        edited_data = edited_anchor.json()["data"]
        assert edited_data["id"] == manual_anchor_data["id"]
        assert edited_data["normalized_key"] == "atlas roadmap"
        assert "Atlas delivery" in edited_data["aliases"]
        assert edited_data["description"] == "Edited manual project anchor."
        assert edited_data["confidence"] == "high"
        assert {ref["source_id"] for ref in edited_data["evidence_refs"]} == {
            "manual-anchor-atlas",
            "atlas-roadmap-doc",
        }
        assert edited_data["observed_at"] == "2026-01-03T00:00:00+00:00"
        assert edited_data["metadata"]["last_edit_source"] == "manual"

        deleted_anchor = client.request(
            "DELETE",
            f"/v1/anchors/{manual_anchor_data['id']}",
            json={"reason": "obsolete manual project anchor"},
            headers=auth_headers(),
        )
        assert deleted_anchor.status_code == 200, deleted_anchor.text
        deleted_anchor_data = deleted_anchor.json()["data"]
        assert deleted_anchor_data["status"] == "deleted"
        assert deleted_anchor_data["metadata"]["delete_reason"] == "obsolete manual project anchor"

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
        assert ("project", "atlas roadmap") not in keys
        assert ("event", "meeting last week") in keys
        alex_anchor = next(item for item in active_anchors if item["normalized_key"] == "alex")
        assert alex_anchor["confidence"] in {"high", "medium"}
        assert any(
            ref["source_type"] in {"capture", "fact"} for ref in alex_anchor["evidence_refs"]
        )

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
        assert merged_anchor["evidence_refs"]

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


def test_anchor_backfill_collapses_russian_person_case_variants(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-aleksom",
                "text": "Час назад я переписывался с Алексом по Project Atlas.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "text": "Алекс подтвердил Project Atlas после переписки.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "fact-alex"}],
            },
            headers=auth_headers({"Idempotency-Key": "fact-alex-case-variant"}),
        )
        assert fact.status_code == 201, fact.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "person",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        person_anchors = anchors.json()["data"]
        assert len(person_anchors) == 1
        assert person_anchors[0]["normalized_key"] == "алекс"
        assert person_anchors[0]["label"] == "Алекс"
        assert {"Алекс", "Алексом"}.issubset(set(person_anchors[0]["aliases"]))
        assert person_anchors[0]["metadata"]["canonical_key"] == "aleks"


def test_anchor_backfill_preserves_manual_event_label_for_case_variants(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-maria-event-variant",
                "text": "Созвон с Мария вчера подтвердил Project Atlas.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        manual_anchor = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "event",
                "label": "Созвон с Марией вчера",
                "aliases": ["Вчерашний созвон с Марией"],
                "description": "Reviewer-confirmed event anchor.",
            },
            headers=auth_headers(),
        )
        assert manual_anchor.status_code == 200, manual_anchor.text
        manual_anchor_data = manual_anchor.json()["data"]
        assert manual_anchor_data["metadata"]["canonical_key"] == "sozvon s mariya vchera"

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "event",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        event_anchors = anchors.json()["data"]
        participant_events = [
            item
            for item in event_anchors
            if item["metadata"]["canonical_key"] == "sozvon s mariya vchera"
        ]
        assert len(participant_events) == 1
        event_anchor = participant_events[0]
        assert event_anchor["id"] == manual_anchor_data["id"]
        assert event_anchor["label"] == "Созвон с Марией вчера"
        assert event_anchor["normalized_key"] == "созвон с марией вчера"
        assert {
            "Созвон с Марией вчера",
            "Созвон с Мария вчера",
        }.issubset(set(event_anchor["aliases"]))
        assert any(item["normalized_key"] == "созвон вчера" for item in event_anchors)
