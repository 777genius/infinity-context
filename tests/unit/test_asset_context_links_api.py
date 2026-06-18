import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import MemoryFactRow, MemoryThreadRow
from memo_stack_server.admin import token_create
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.db import upgrade
from memo_stack_server.main import create_app
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


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


def stored_blob_files(asset_storage_dir: Path) -> list[Path]:
    return sorted(
        (path for path in asset_storage_dir.rglob("*") if path.is_file()),
        key=lambda path: str(path),
    )


def test_asset_upload_download_dedupe_and_context_link_flow(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "text": "Alex call last week decided the frontend capture UI needs context links.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "alex-call"}],
                "category": "project_context",
                "tags": ["alex", "frontend"],
            },
            headers=auth_headers({"Idempotency-Key": "alex-fact"}),
        )
        second_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "text": "Project Atlas screenshot evidence should support the capture workflow.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-workflow"}],
                "category": "project_context",
                "tags": ["atlas", "workflow"],
            },
            headers=auth_headers({"Idempotency-Key": "atlas-workflow-fact"}),
        )
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "filename": "alex-screenshot.png",
            },
            content=b"fake image bytes",
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        duplicate = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "filename": "renamed.png",
            },
            content=b"fake image bytes",
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        asset_id = upload.json()["data"]["id"]
        download = client.get(f"/v1/assets/{asset_id}/download", headers=auth_headers())
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-with-asset",
                "text": "Screenshot from Alex about frontend capture context links.",
                "source_authority": "user_statement",
                "evidence_refs": [{"source_type": "asset", "source_id": asset_id}],
            },
            headers=auth_headers(),
        )
        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "frontend capture Alex",
            },
            headers=auth_headers(),
        )
        link = client.post(
            "/v1/context-links",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "target_type": "fact",
                "target_id": fact.json()["data"]["id"],
                "relation_type": "related_to",
                "confidence": "high",
                "reason": "same person and same frontend capture topic",
            },
            headers=auth_headers(),
        )
        updated_link = client.patch(
            f"/v1/context-links/{link.json()['data']['id']}",
            json={
                "target_type": "fact",
                "target_id": second_fact.json()["data"]["id"],
                "relation_type": "supports",
                "confidence": "medium",
                "reason": "reviewer corrected target fact",
                "metadata": {"updated_from": "api_test"},
            },
            headers=auth_headers(),
        )
        listed_links = client.get(
            "/v1/context-links",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
            },
            headers=auth_headers(),
        )
        second_link = client.post(
            "/v1/context-links",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "target_type": "fact",
                "target_id": fact.json()["data"]["id"],
                "relation_type": "supports",
                "confidence": "low",
                "reason": "secondary reviewer link for conflict coverage",
            },
            headers=auth_headers(),
        )
        conflicting_update = client.patch(
            f"/v1/context-links/{second_link.json()['data']['id']}",
            json={
                "target_type": "fact",
                "target_id": second_fact.json()["data"]["id"],
                "relation_type": "supports",
                "confidence": "medium",
                "reason": "would duplicate the corrected link",
            },
            headers=auth_headers(),
        )
        link_id = link.json()["data"]["id"]
        deleted_link = client.delete(
            f"/v1/context-links/{link_id}",
            headers=auth_headers(),
        )
        deleted_second_link = client.delete(
            f"/v1/context-links/{second_link.json()['data']['id']}",
            headers=auth_headers(),
        )
        active_links_after_delete = client.get(
            "/v1/context-links",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "status": "active",
            },
            headers=auth_headers(),
        )
        deleted_links = client.get(
            "/v1/context-links",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "status": "deleted",
            },
            headers=auth_headers(),
        )

    assert fact.status_code == 201
    assert second_fact.status_code == 201
    assert upload.status_code == 201
    assert upload.json()["data"]["duplicate"] is False
    assert upload.json()["data"]["content_type"] == "image/png"
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["duplicate"] is True
    assert duplicate.json()["data"]["id"] == asset_id
    assert download.status_code == 200
    assert download.content == b"fake image bytes"
    assert capture.status_code == 201
    assert suggestions.status_code == 200
    candidate = suggestions.json()["data"]["candidates"][0]
    assert candidate["target_type"] == "fact"
    assert candidate["target_id"] == fact.json()["data"]["id"]
    assert "matching text" in candidate["reasons"]
    assert "text_match" in candidate["metadata"]["reason_codes"]
    assert candidate["metadata"]["suggestion_policy_version"] == "context-link-policy-v1"
    assert candidate["metadata"]["policy_decision"] in {
        "needs_review",
        "auto_approve_candidate",
    }
    assert candidate["metadata"]["policy_decision_canonical"] in {
        "pending_review",
        "auto_approve_candidate",
    }
    assert candidate["metadata"]["review_gate"] == "required"
    assert {"alex", "frontend", "capture"}.issubset(set(candidate["metadata"]["matched_terms"]))
    assert link.status_code == 200
    assert link.json()["data"]["duplicate"] is False
    assert updated_link.status_code == 200
    updated_data = updated_link.json()["data"]
    assert updated_data["target_id"] == second_fact.json()["data"]["id"]
    assert updated_data["relation_type"] == "supports"
    assert updated_data["confidence"] == "medium"
    assert updated_data["reason"] == "reviewer corrected target fact"
    assert updated_data["metadata"]["updated_from"] == "api_test"
    assert updated_data["metadata"]["last_edit_source"] == "manual"
    edit_event = updated_data["metadata"]["edit_events"][-1]
    assert edit_event["source"] == "manual"
    assert set(edit_event["changed_fields"]) == {
        "target_id",
        "relation_type",
        "confidence",
        "reason",
    }
    assert edit_event["previous"]["target_id"] == fact.json()["data"]["id"]
    assert edit_event["next"]["target_id"] == second_fact.json()["data"]["id"]
    assert listed_links.status_code == 200
    assert listed_links.json()["data"][0]["target_id"] == second_fact.json()["data"]["id"]
    assert second_link.status_code == 200
    assert second_link.json()["data"]["duplicate"] is False
    assert conflicting_update.status_code == 409
    assert deleted_link.status_code == 200
    assert deleted_link.json()["data"]["status"] == "deleted"
    assert deleted_second_link.status_code == 200
    assert deleted_second_link.json()["data"]["status"] == "deleted"
    assert active_links_after_delete.status_code == 200
    assert active_links_after_delete.json()["data"] == []
    assert deleted_links.status_code == 200
    deleted_link_ids = {item["id"] for item in deleted_links.json()["data"]}
    assert {link_id, second_link.json()["data"]["id"]}.issubset(deleted_link_ids)


def test_context_link_suggestions_include_thread_anchor(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "thread-anchor-capture",
                "text": "Alex call notes about frontend memory linking.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex call memory",
                "persist": True,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        thread_candidate = next(item for item in candidates if item["target_type"] == "thread")
        assert thread_candidate["label"] == "alex-call"
        assert thread_candidate["metadata"]["external_ref"] == "alex-call"
        assert "same thread" in thread_candidate["reasons"]
        assert "same_thread" in thread_candidate["metadata"]["reason_codes"]
        assert thread_candidate["suggestion_id"]

        approved = client.post(
            f"/v1/context-link-suggestions/{thread_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "attached to source thread"},
            headers=auth_headers(),
        )

    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["duplicate_link"] is False
    assert approved_data["suggestion"]["target_type"] == "thread"
    assert approved_data["suggestion"]["review_reason"] == "attached to source thread"
    assert approved_data["link"]["target_type"] == "thread"
    assert approved_data["link"]["target_id"] == thread_candidate["target_id"]
    assert approved_data["link"]["metadata"]["external_ref"] == "alex-call"


def test_context_link_suggestions_include_episode_target(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        episode = client.post(
            "/v1/episodes",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_type": "transcript",
                "source_external_id": "alex-call-last-week",
                "text": "Alex call episode confirmed frontend memory linking decisions.",
                "speaker": "user",
            },
            headers=auth_headers(),
        )
        assert episode.status_code == 200, episode.text
        episode_id = episode.json()["data"]["episode_id"]

        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "episode-link-capture",
                "text": "Attach this screenshot to the Alex call memory linking episode.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-call",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex call memory linking episode",
                "persist": True,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        episode_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "episode" and item["target_id"] == episode_id
        )
        assert episode_candidate["label"] == "transcript - alex-call-last-week"
        assert episode_candidate["metadata"]["source_external_id"] == "alex-call-last-week"
        assert episode_candidate["metadata"]["thread_id"]
        assert "same_thread" in episode_candidate["metadata"]["reason_codes"]
        assert episode_candidate["suggestion_id"]

        approved = client.post(
            f"/v1/context-link-suggestions/{episode_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "linked to prior call episode"},
            headers=auth_headers(),
        )

    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["duplicate_link"] is False
    assert approved_data["suggestion"]["target_type"] == "episode"
    assert approved_data["suggestion"]["review_reason"] == "linked to prior call episode"
    assert approved_data["link"]["target_type"] == "episode"
    assert approved_data["link"]["target_id"] == episode_id
    assert approved_data["link"]["metadata"]["source_external_id"] == "alex-call-last-week"


def test_context_link_suggestions_include_document_and_chunk_targets(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "doc-review",
                "title": "Qdrant memory architecture",
                "text": (
                    "Memo Stack keeps canonical memory in Postgres. "
                    "Qdrant stores derived document chunks for retrieval."
                ),
                "source_type": "document",
                "source_external_id": "qdrant-architecture.md",
            },
            headers=auth_headers(),
        )
        assert document.status_code == 201, document.text
        document_id = document.json()["data"]["id"]

        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "doc-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "document-link-capture",
                "text": "Need to link this screenshot to the Qdrant document chunks.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "doc-review",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Qdrant document chunks",
                "persist": True,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        document_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "document" and item["target_id"] == document_id
        )
        chunk_candidate = next(item for item in candidates if item["target_type"] == "chunk")
        assert document_candidate["label"] == "Qdrant memory architecture"
        assert document_candidate["metadata"]["source_external_id"] == "qdrant-architecture.md"
        assert "text_match" in document_candidate["metadata"]["reason_codes"]
        assert chunk_candidate["metadata"]["document_id"] == document_id
        assert chunk_candidate["metadata"]["source_external_id"] == "qdrant-architecture.md"
        assert "qdrant" in chunk_candidate["metadata"]["matched_terms"]
        assert chunk_candidate["suggestion_id"]

        approved = client.post(
            f"/v1/context-link-suggestions/{chunk_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "linked to exact document chunk"},
            headers=auth_headers(),
        )

    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["suggestion"]["target_type"] == "chunk"
    assert approved_data["suggestion"]["review_reason"] == "linked to exact document chunk"
    assert approved_data["link"]["target_type"] == "chunk"
    assert approved_data["link"]["metadata"]["document_id"] == document_id


def test_persisted_context_link_suggestions_can_be_reviewed(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "text": "Alex agreed that screenshots should be linked to context memory.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "alex-review"}],
            },
            headers=auth_headers({"Idempotency-Key": "review-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-review",
                "text": "Screenshot note from Alex about context memory links.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex screenshot context memory",
                "persist": True,
            },
            headers=auth_headers(),
        )
        repeated = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex screenshot context memory",
                "persist": True,
            },
            headers=auth_headers(),
        )
        suggestion_id = suggestions.json()["data"]["candidates"][0]["suggestion_id"]
        pending = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
            },
            headers=auth_headers(),
        )
        approved = client.post(
            f"/v1/context-link-suggestions/{suggestion_id}/review",
            json={"action": "approve", "reason": "  reviewed by user  "},
            headers=auth_headers(),
        )
        approve_again = client.post(
            f"/v1/context-link-suggestions/{suggestion_id}/review",
            json={"action": "approve"},
            headers=auth_headers(),
        )
        links = client.get(
            "/v1/context-links",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
            },
            headers=auth_headers(),
        )

    assert fact.status_code == 201
    assert capture.status_code == 201
    assert suggestions.status_code == 200
    candidate = suggestions.json()["data"]["candidates"][0]
    assert candidate["target_type"] == "fact"
    assert candidate["target_id"] == fact.json()["data"]["id"]
    assert candidate["suggestion_id"]
    assert candidate["status"] == "pending"
    assert candidate["metadata"]["suggestion_policy_version"] == "context-link-policy-v1"
    assert candidate["metadata"]["policy_confidence"] in {"medium", "high"}
    assert candidate["metadata"]["review_gate"] == "required"
    assert repeated.status_code == 200
    assert repeated.json()["data"]["candidates"][0]["suggestion_id"] == suggestion_id
    assert pending.status_code == 200
    pending_suggestion = next(
        item for item in pending.json()["data"] if item["id"] == suggestion_id
    )
    assert pending_suggestion["status"] == "pending"
    assert pending_suggestion["review_audit"] == {
        "events": [],
        "event_count": 0,
        "truncated": False,
    }
    assert approved.status_code == 200
    approved_data = approved.json()["data"]
    approved_suggestion = approved_data["suggestion"]
    assert approved_suggestion["status"] == "approved"
    assert approved_suggestion["review_reason"] == "reviewed by user"
    assert approved_suggestion["reviewed_at"]
    assert approved_suggestion["review_audit"]["event_count"] == 1
    assert approved_suggestion["review_audit"]["truncated"] is False
    assert approved_suggestion["review_audit"]["events"][-1]["action"] == "approve"
    assert approved_suggestion["review_audit"]["events"][-1]["reason"] == "reviewed by user"
    assert approved_suggestion["review_audit"]["events"][-1]["new_status"] == "approved"
    assert approved_data["link"]["target_id"] == fact.json()["data"]["id"]
    assert approved_data["link"]["reason"] == "reviewed by user"
    assert "approved_override" not in approved_data["link"]["metadata"]
    assert approved_data["duplicate_link"] is False
    assert approve_again.status_code == 200
    assert approve_again.json()["data"]["duplicate_link"] is True
    assert links.status_code == 200
    assert links.json()["data"][0]["target_id"] == fact.json()["data"]["id"]


def test_context_link_review_response_redacts_sensitive_reason(tmp_path: Path) -> None:
    sensitive_reason = "Authorization: Bearer sk-proj-review-secret-value"
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "text": "Alex screenshot evidence belongs to the secure review fact.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "secure-review"}],
                "tags": ["alex", "screenshot"],
            },
            headers=auth_headers({"Idempotency-Key": "secure-review-link-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "secure-review-capture",
                "text": "Screenshot note from Alex about secure review links.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex screenshot secure review",
                "persist": True,
            },
            headers=auth_headers(),
        )
        suggestion_id = suggestions.json()["data"]["candidates"][0]["suggestion_id"]
        approved = client.post(
            f"/v1/context-link-suggestions/{suggestion_id}/review",
            json={"action": "approve", "reason": sensitive_reason},
            headers=auth_headers(),
        )

    assert fact.status_code == 201
    assert capture.status_code == 201
    assert suggestions.status_code == 200
    assert approved.status_code == 200, approved.text
    assert "sk-proj-review-secret-value" not in approved.text
    data = approved.json()["data"]
    assert data["suggestion"]["review_reason"] == "[redacted]"
    assert data["suggestion"]["review_audit"]["events"][-1]["reason"] == "[redacted]"
    assert data["link"]["reason"] == "[redacted]"


def test_rejected_context_link_suggestion_is_not_recreated(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "text": "Alex Project Atlas screenshot evidence belongs to the reviewed fact.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "alex-review"}],
                "tags": ["alex", "atlas", "screenshot"],
            },
            headers=auth_headers({"Idempotency-Key": "rejected-link-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "rejected-link-capture",
                "text": "Save Alex Project Atlas screenshot evidence.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert fact.status_code == 201, fact.text
        assert capture.status_code == 201, capture.text

        payload = {
            "space_slug": "quick-capture",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "review-thread",
            "source_type": "capture",
            "source_id": capture.json()["data"]["id"],
            "text": "Alex Project Atlas screenshot evidence",
            "persist": True,
            "limit": 8,
        }
        suggestions = client.post("/v1/link-suggestions", json=payload, headers=auth_headers())
        assert suggestions.status_code == 200, suggestions.text
        fact_candidate = next(
            item
            for item in suggestions.json()["data"]["candidates"]
            if item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
        )
        rejected = client.post(
            f"/v1/context-link-suggestions/{fact_candidate['suggestion_id']}/review",
            json={"action": "reject", "reason": "not relevant after review"},
            headers=auth_headers(),
        )
        assert rejected.status_code == 200, rejected.text

        repeated = client.post("/v1/link-suggestions", json=payload, headers=auth_headers())
        assert repeated.status_code == 200, repeated.text
        repeated_data = repeated.json()["data"]
        assert all(
            item["target_id"] != fact.json()["data"]["id"]
            for item in repeated_data["candidates"]
            if item["target_type"] == "fact"
        )
        assert repeated_data["diagnostics"]["skipped_reviewed_suggestion_count"] >= 1
        assert (
            repeated_data["diagnostics"]["skipped_reviewed_suggestion_status_counts"]["rejected"]
            >= 1
        )

        history = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "status": "all",
            },
            headers=auth_headers(),
        )
        assert history.status_code == 200, history.text
        same_pair = [
            item
            for item in history.json()["data"]
            if item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
        ]
        assert len(same_pair) == 1
        assert same_pair[0]["status"] == "rejected"


def test_context_link_suggestion_approve_can_override_target(tmp_path: Path) -> None:
    raw_sensitive_value = "sk-" + "proj-link-reason-value1234567890"
    with make_client(tmp_path) as client:
        suggested_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-source",
                "text": "Project Atlas screenshot belongs to Alex review evidence.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "suggested"}],
                "tags": ["atlas", "alex"],
            },
            headers=auth_headers({"Idempotency-Key": "override-link-review-suggested"}),
        )
        override_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-source",
                "text": "Project Atlas final decision should be the approved link target.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "override"}],
                "tags": ["atlas", "decision"],
            },
            headers=auth_headers({"Idempotency-Key": "override-link-review-target"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-source",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "override-link-review-capture",
                "text": "Attach this screenshot to Alex Project Atlas review evidence.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert suggested_fact.status_code == 201, suggested_fact.text
        assert override_fact.status_code == 201, override_fact.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-source",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex Project Atlas screenshot review evidence",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        fact_candidate = next(
            item
            for item in suggestions.json()["data"]["candidates"]
            if item["target_type"] == "fact"
        )

        approved = client.post(
            f"/v1/context-link-suggestions/{fact_candidate['suggestion_id']}/review",
            json={
                "action": "approve",
                "reason": "reviewer corrected target",
                "target_type": "fact",
                "target_id": override_fact.json()["data"]["id"],
                "relation_type": "supports",
                "confidence": "high",
                "link_reason": f"approved corrected target with {raw_sensitive_value}",
            },
            headers=auth_headers(),
        )
        scope_links = client.get(
            "/v1/context-links",
            params={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
            },
            headers=auth_headers(),
        )
        repeated = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "override-link-review",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review-source",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex Project Atlas screenshot review evidence",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )

    assert approved.status_code == 200, approved.text
    assert raw_sensitive_value not in approved.text
    payload = approved.json()["data"]
    assert payload["suggestion"]["status"] == "approved"
    assert payload["suggestion"]["target_id"] == fact_candidate["target_id"]
    assert payload["suggestion"]["metadata"]["approved_override"] is True
    assert payload["suggestion"]["metadata"]["original_target_id"] == fact_candidate["target_id"]
    assert (
        payload["suggestion"]["metadata"]["approved_target_id"]
        == override_fact.json()["data"]["id"]
    )
    assert payload["suggestion"]["metadata"]["approved_relation_type"] == "supports"
    assert (
        payload["suggestion"]["metadata"]["approved_link_reason"]
        == "approved corrected target with [redacted]"
    )
    assert payload["link"]["target_id"] == override_fact.json()["data"]["id"]
    assert payload["link"]["relation_type"] == "supports"
    assert payload["link"]["confidence"] == "high"
    assert payload["link"]["reason"] == "[redacted]"
    assert payload["link"]["metadata"]["approved_override"] is True
    assert payload["link"]["metadata"]["original_target_id"] == fact_candidate["target_id"]
    assert payload["link"]["metadata"]["approved_target_id"] == override_fact.json()["data"]["id"]
    assert (
        payload["link"]["metadata"]["approved_link_reason"]
        == "approved corrected target with [redacted]"
    )
    assert scope_links.status_code == 200, scope_links.text
    assert [item["id"] for item in scope_links.json()["data"]] == [payload["link"]["id"]]
    assert repeated.status_code == 200, repeated.text
    repeated_data = repeated.json()["data"]
    assert all(
        item["target_id"] != fact_candidate["target_id"]
        for item in repeated_data["candidates"]
        if item["target_type"] == "fact"
    )
    assert (
        repeated_data["diagnostics"]["skipped_reviewed_suggestion_status_counts"]["approved"] >= 1
    )


def test_persisted_context_link_suggestions_create_semantic_anchors(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "anchor-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-anchor-review",
                "text": (
                    "Alex shared Project Atlas notes from meeting last week "
                    "about Qdrant document memory."
                ),
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "anchor-thread",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex Project Atlas meeting last week Qdrant",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        anchor_candidates = [item for item in candidates if item["target_type"] == "anchor"]
        anchor_kinds = {item["metadata"]["anchor_kind"] for item in anchor_candidates}

        assert {"person", "project", "event"} <= anchor_kinds
        assert any(item["metadata"]["normalized_key"] == "alex" for item in anchor_candidates)
        assert any(
            item["metadata"]["normalized_key"] == "atlas"
            and item["metadata"]["anchor_kind"] == "project"
            for item in anchor_candidates
        )
        assert any(
            item["metadata"]["normalized_key"] == "meeting last week"
            and item["metadata"]["anchor_kind"] == "event"
            for item in anchor_candidates
        )
        reason_codes_by_anchor = {
            (item["metadata"]["anchor_kind"], item["metadata"]["normalized_key"]): set(
                item["metadata"]["reason_codes"]
            )
            for item in anchor_candidates
        }
        assert "person_name" in reason_codes_by_anchor[("person", "alex")]
        assert "explicit_project_reference" in reason_codes_by_anchor[("project", "atlas")]
        assert "event_phrase" in reason_codes_by_anchor[("event", "meeting last week")]

        person_suggestion = next(
            item for item in anchor_candidates if item["metadata"]["normalized_key"] == "alex"
        )
        approved = client.post(
            f"/v1/context-link-suggestions/{person_suggestion['suggestion_id']}/review",
            json={"action": "approve", "reason": "confirmed person anchor"},
            headers=auth_headers(),
        )
        assert approved.status_code == 200, approved.text
        review_data = approved.json()["data"]
        assert review_data["suggestion"]["target_type"] == "anchor"
        assert review_data["suggestion"]["status"] == "approved"
        assert review_data["link"]["target_type"] == "anchor"
        assert review_data["link"]["metadata"]["anchor_kind"] == "person"


def test_persisted_context_link_suggestions_merge_observed_anchor_case_variants(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        first_capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture-anchor-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-alex",
                "text": "Алекс подтвердил Project Atlas.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        second_capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture-anchor-variants",
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
        assert first_capture.status_code == 201, first_capture.text
        assert second_capture.status_code == 201, second_capture.text

        first_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture-anchor-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_type": "capture",
                "source_id": first_capture.json()["data"]["id"],
                "text": "Алекс Project Atlas",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        second_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture-anchor-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_type": "capture",
                "source_id": second_capture.json()["data"]["id"],
                "text": "Час назад переписывался с Алексом Project Atlas",
                "persist": True,
                "limit": 10,
            },
            headers=auth_headers(),
        )
        assert first_suggestions.status_code == 200, first_suggestions.text
        assert second_suggestions.status_code == 200, second_suggestions.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "quick-capture-anchor-variants",
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


def test_context_linking_quality_golden_handles_people_events_projects_and_decoys(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        right_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "text": (
                    "Project Atlas uses Qdrant chunks for screenshot memory. "
                    "Alex owns the follow-up from the meeting last week."
                ),
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-right"}],
                "category": "project_context",
                "tags": ["project-atlas", "alex", "qdrant"],
            },
            headers=auth_headers({"Idempotency-Key": "linking-quality-right"}),
        )
        decoy_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "text": (
                    "Project Atlas Mobile tracks onboarding copy and unrelated "
                    "launch checklist work."
                ),
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-decoy"}],
                "category": "project_context",
                "tags": ["project-atlas-mobile"],
            },
            headers=auth_headers({"Idempotency-Key": "linking-quality-decoy"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "linking-quality-capture",
                "text": (
                    "Screenshot from Alex after Project Atlas meeting last week "
                    "about Qdrant chunks. Chat with Alex an hour ago confirmed it."
                ),
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert right_fact.status_code == 201, right_fact.text
        assert decoy_fact.status_code == 201, decoy_fact.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": (
                    "Alex Project Atlas meeting last week Qdrant chunks chat with Alex an hour ago"
                ),
                "persist": True,
                "limit": 12,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        fact_candidates = [item for item in candidates if item["target_type"] == "fact"]
        anchor_candidates = [item for item in candidates if item["target_type"] == "anchor"]

        assert fact_candidates, candidates
        assert fact_candidates[0]["target_id"] == right_fact.json()["data"]["id"]
        assert fact_candidates[0]["target_id"] != decoy_fact.json()["data"]["id"]
        assert {"alex", "project", "atlas", "qdrant"}.issubset(
            set(fact_candidates[0]["metadata"]["matched_terms"])
        )

        anchor_keys = {
            (item["metadata"]["anchor_kind"], item["metadata"]["normalized_key"])
            for item in anchor_candidates
        }
        assert ("person", "alex") in anchor_keys
        assert ("project", "atlas") in anchor_keys
        assert ("event", "meeting last week") in anchor_keys
        assert ("event", "chat an hour ago") in anchor_keys or (
            "event",
            "chat hour ago",
        ) in anchor_keys


def test_context_linking_quality_golden_empty_scope_returns_no_candidates(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "empty-linking-quality", "name": "Empty linking quality"},
            headers=auth_headers(),
        )
        assert space.status_code == 201, space.text
        scope = client.post(
            "/v1/memory-scopes",
            json={
                "space_id": space.json()["data"]["id"],
                "external_ref": "default",
                "name": "Default",
            },
            headers=auth_headers(),
        )
        assert scope.status_code == 201, scope.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "empty-linking-quality",
                "memory_scope_external_ref": "default",
                "text": "No existing candidate should match this isolated note.",
                "limit": 10,
            },
            headers=auth_headers(),
        )

    assert suggestions.status_code == 200, suggestions.text
    payload = suggestions.json()["data"]
    assert payload["candidates"] == []
    assert payload["diagnostics"]["candidate_count"] == 0


def test_context_linking_quality_golden_unrelated_existing_memory_returns_no_candidates(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        unrelated = client.post(
            "/v1/facts",
            json={
                "space_slug": "unrelated-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "billing-launch",
                "text": "Billing Portal launch checklist uses Stripe invoices and tax copy.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "billing"}],
                "tags": ["billing", "stripe"],
            },
            headers=auth_headers({"Idempotency-Key": "unrelated-linking-quality-fact"}),
        )
        assert unrelated.status_code == 201, unrelated.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "unrelated-linking-quality",
                "memory_scope_external_ref": "default",
                "text": "Plant watering schedule kitchen humidity reminder.",
                "limit": 10,
            },
            headers=auth_headers(),
        )

    assert suggestions.status_code == 200, suggestions.text
    payload = suggestions.json()["data"]
    assert payload["candidates"] == []
    assert payload["diagnostics"]["candidate_count"] == 0


def test_context_linking_quality_golden_links_files_documents_and_chunks(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "file-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-files",
                "text": (
                    "Alex said Project Atlas screenshot evidence should stay linked "
                    "to the Qdrant chunk memory document."
                ),
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-file-fact"}],
                "tags": ["project-atlas", "screenshot", "qdrant"],
            },
            headers=auth_headers({"Idempotency-Key": "file-linking-quality-fact"}),
        )
        asset = client.post(
            "/v1/assets",
            params={
                "space_slug": "file-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-files",
                "filename": "project-atlas-screenshot.png",
            },
            content=b"fake screenshot bytes",
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "file-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-files",
                "title": "Project Atlas screenshot memory notes",
                "text": (
                    "Alex Project Atlas screenshot evidence says Qdrant chunk memory "
                    "must attach to uploaded files."
                ),
                "source_type": "document",
                "source_external_id": "project-atlas-screenshot-notes",
            },
            headers=auth_headers({"Idempotency-Key": "file-linking-quality-doc"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "file-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-files",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "file-linking-quality-capture",
                "text": (
                    "Screenshot from Alex for Project Atlas file memory should link "
                    "to uploaded file, document and exact Qdrant chunk."
                ),
                "source_authority": "user_statement",
                "evidence_refs": [
                    {"source_type": "asset", "source_id": asset.json()["data"]["id"]}
                ],
            },
            headers=auth_headers(),
        )
        assert fact.status_code == 201, fact.text
        assert asset.status_code == 201, asset.text
        assert document.status_code == 201, document.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "file-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-files",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": (
                    "Alex Project Atlas screenshot uploaded file document exact Qdrant chunk memory"
                ),
                "persist": True,
                "limit": 20,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        target_types = {item["target_type"] for item in candidates}
        assert {"asset", "document", "chunk", "fact"}.issubset(target_types)
        assert any(
            item["target_type"] == "asset" and item["target_id"] == asset.json()["data"]["id"]
            for item in candidates
        )
        assert any(
            item["target_type"] == "document" and item["target_id"] == document.json()["data"]["id"]
            for item in candidates
        )

        chunk_candidate = next(item for item in candidates if item["target_type"] == "chunk")
        approved = client.post(
            f"/v1/context-link-suggestions/{chunk_candidate['suggestion_id']}/review",
            json={"action": "approve", "reason": "linked to exact chunk evidence"},
            headers=auth_headers(),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["link"]["target_type"] == "chunk"
        assert (
            approved.json()["data"]["link"]["metadata"]["document_id"]
            == document.json()["data"]["id"]
        )


def test_context_linking_quality_golden_links_temporal_thread_and_event_anchor(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "temporal-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-chat-hour-ago",
                "text": "Chat with Alex an hour ago confirmed Project Atlas billing cutoff.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "alex-hour-chat"}],
                "tags": ["alex", "project-atlas", "billing"],
            },
            headers=auth_headers({"Idempotency-Key": "temporal-linking-quality-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "temporal-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "temporal-linking-quality-capture",
                "text": (
                    "Attach this billing cutoff note to the chat with Alex an hour ago "
                    "for Project Atlas."
                ),
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert fact.status_code == 201, fact.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "temporal-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Project Atlas billing cutoff chat with Alex an hour ago",
                "persist": True,
                "limit": 16,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        assert any(
            item["target_type"] == "thread"
            and item["metadata"]["external_ref"] == "alex-chat-hour-ago"
            for item in candidates
        )
        assert any(
            item["target_type"] == "anchor"
            and item["metadata"]["anchor_kind"] == "event"
            and item["metadata"]["normalized_key"] in {"chat an hour ago", "chat hour ago"}
            for item in candidates
        )
        assert any(
            item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
            for item in candidates
        )


def test_context_linking_quality_golden_links_temporal_intent_without_text_match(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "temporal-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-chat-hour-ago",
                "text": "Payment exception window was confirmed for Atlas cutoff.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "recent-alex-thread"}],
                "tags": ["atlas", "payment"],
            },
            headers=auth_headers({"Idempotency-Key": "temporal-intent-linking-quality-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "temporal-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "temporal-intent-linking-quality-capture",
                "text": "Сохрани заметку и привяжи к разговору час назад.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert fact.status_code == 201, fact.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "temporal-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "привяжи к разговору час назад",
                "persist": True,
                "limit": 16,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        payload = suggestions.json()["data"]
        candidates = payload["candidates"]

        assert payload["diagnostics"]["temporal_hints"] == ["hour_ago"]
        fact_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
        )
        thread_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "thread"
            and item["metadata"]["external_ref"] == "alex-chat-hour-ago"
        )
        assert fact_candidate["metadata"]["matched_terms"] == []
        assert thread_candidate["metadata"]["matched_terms"] == []
        assert "temporal intent match" in fact_candidate["reasons"]
        assert "temporal_intent_match" in fact_candidate["metadata"]["reason_codes"]
        assert fact_candidate["suggestion_id"]
        assert thread_candidate["suggestion_id"]


def test_context_linking_quality_golden_links_last_week_intent_without_text_match(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "last-week-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-review-week-old",
                "text": "Payment exception window was confirmed for Atlas cutoff.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "week-old-review"}],
                "tags": ["atlas", "payment"],
            },
            headers=auth_headers({"Idempotency-Key": "last-week-intent-linking-quality-fact"}),
        )
        assert fact.status_code == 201, fact.text
        asyncio.run(
            _age_fact_and_thread(
                client,
                fact_id=fact.json()["data"]["id"],
                thread_external_ref="alex-review-week-old",
                age=timedelta(days=7),
            )
        )

        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "last-week-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "last-week-intent-linking-quality-capture",
                "text": "Сохрани заметку и привяжи к встрече неделю назад.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "last-week-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "привяжи к встрече неделю назад",
                "persist": True,
                "limit": 16,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        payload = suggestions.json()["data"]
        candidates = payload["candidates"]

        assert payload["diagnostics"]["temporal_hints"] == ["last_week"]
        fact_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
        )
        thread_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "thread"
            and item["metadata"]["external_ref"] == "alex-review-week-old"
        )
        assert fact_candidate["metadata"]["matched_terms"] == []
        assert thread_candidate["metadata"]["matched_terms"] == []
        assert "temporal intent match" in fact_candidate["reasons"]
        assert "temporal_intent_match" in fact_candidate["metadata"]["reason_codes"]
        assert fact_candidate["suggestion_id"]
        assert thread_candidate["suggestion_id"]


def test_context_linking_quality_golden_links_numeric_hours_intent_without_text_match(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "numeric-hours-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "alex-chat-five-hours-ago",
                "text": "Payment exception window was confirmed for Atlas cutoff.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "five-hour-review"}],
                "tags": ["atlas", "payment"],
            },
            headers=auth_headers({"Idempotency-Key": "numeric-hours-intent-linking-fact"}),
        )
        assert fact.status_code == 201, fact.text
        asyncio.run(
            _age_fact_and_thread(
                client,
                fact_id=fact.json()["data"]["id"],
                thread_external_ref="alex-chat-five-hours-ago",
                age=timedelta(hours=5),
            )
        )

        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "numeric-hours-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "numeric-hours-intent-linking-capture",
                "text": "Сохрани заметку и привяжи к разговору 5 часов назад.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "numeric-hours-intent-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quick-save",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "привяжи к разговору 5 часов назад",
                "persist": True,
                "limit": 16,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        payload = suggestions.json()["data"]
        candidates = payload["candidates"]

        assert payload["diagnostics"]["temporal_hints"] == ["5_hours_ago"]
        fact_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "fact" and item["target_id"] == fact.json()["data"]["id"]
        )
        thread_candidate = next(
            item
            for item in candidates
            if item["target_type"] == "thread"
            and item["metadata"]["external_ref"] == "alex-chat-five-hours-ago"
        )
        assert fact_candidate["metadata"]["matched_terms"] == []
        assert thread_candidate["metadata"]["matched_terms"] == []
        assert "temporal intent match" in fact_candidate["reasons"]
        assert "temporal_intent_match" in fact_candidate["metadata"]["reason_codes"]
        assert fact_candidate["suggestion_id"]
        assert thread_candidate["suggestion_id"]


def test_context_link_suggestions_redact_public_diagnostics(tmp_path: Path) -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "diagnostic-redaction-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "text": "Project Atlas uses safe context links.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "safe-fact"}],
                "tags": ["atlas"],
            },
            headers=auth_headers({"Idempotency-Key": "diagnostic-redaction-linking-fact"}),
        )
        assert fact.status_code == 201, fact.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "diagnostic-redaction-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "source_type": "capture",
                "source_id": raw_secret,
                "text": f"Project Atlas token={raw_secret}",
                "limit": 10,
            },
            headers=auth_headers(),
        )

    assert suggestions.status_code == 200, suggestions.text
    rendered = json.dumps(suggestions.json(), sort_keys=True)
    assert raw_secret not in rendered
    assert "[redacted]" in rendered


def test_operations_console_summarizes_ingestion_and_link_review(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "ops-thread",
                "filename": "ops-note.txt",
                "extract": "true",
            },
            content=b"Operational note about Alex link review and ingestion retry.",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        assert upload.status_code == 201, upload.text
        extraction_id = upload.json()["data"]["extraction"]["id"]

        canceled = client.post(
            f"/v1/asset-extractions/{extraction_id}/cancel",
            headers=auth_headers(),
        )
        assert canceled.status_code == 202, canceled.text
        assert canceled.json()["data"]["status"] == "canceled"

        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "ops-thread",
                "text": "Alex link review should explain why memory candidates were suggested.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "ops-fact"}],
            },
            headers=auth_headers({"Idempotency-Key": "ops-fact"}),
        )
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "ops-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "ops-capture",
                "text": "Alex asked for link review explanations in the operations console.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert fact.status_code == 201, fact.text
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "ops-thread",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex link review explanations",
                "persist": True,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        suggestion_id = suggestions.json()["data"]["candidates"][0]["suggestion_id"]

        console = client.get(
            "/v1/operations-console",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
            },
            headers=auth_headers(),
        )
        assert console.status_code == 200, console.text
        data = console.json()["data"]
        assert data["extraction_status_counts"]["canceled"] == 1
        assert data["link_suggestion_status_counts"]["pending"] >= 1
        assert data["diagnostics"]["extraction_retryable_count"] == 1
        assert data["diagnostics"]["link_suggestion_pending_count"] >= 1
        assert "no_suggestion_note" in data["diagnostics"]["link_suggestion_explainability"]
        stored_fields = data["diagnostics"]["link_suggestion_explainability"]["stored_fields"]
        assert "review_reason" in stored_fields
        assert "metadata.matched_terms" in stored_fields
        extraction_fields = data["diagnostics"]["extraction_observability"]["stored_fields"]
        assert "metadata.cancellation_status" in extraction_fields
        assert "metadata.cancellation_message" in extraction_fields
        no_suggestion_reasons = data["diagnostics"]["link_suggestion_explainability"][
            "no_suggestion_reasons"
        ]
        assert [item["code"] for item in no_suggestion_reasons] == [
            "no_visible_same_scope_candidate",
            "source_not_persisted",
            "already_linked",
            "not_pending",
        ]
        assert data["extraction_jobs"][0]["id"] == extraction_id
        assert data["extraction_jobs"][0]["execution"]["cancellation_requested_at"]
        saved_suggestion = next(
            item for item in data["context_link_suggestions"] if item["id"] == suggestion_id
        )
        assert saved_suggestion["metadata"]["resolver_version"]
        assert "text_match" in saved_suggestion["metadata"]["reason_codes"]
        assert {"alex", "link", "review"}.issubset(
            set(saved_suggestion["metadata"]["matched_terms"])
        )
        assert saved_suggestion["reason"]

        reviewed = client.post(
            f"/v1/context-link-suggestions/{suggestion_id}/review",
            json={"action": "approve", "reason": "approved from operations console"},
            headers=auth_headers(),
        )
        assert reviewed.status_code == 200, reviewed.text

        after_review = client.get(
            "/v1/operations-console",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
            },
            headers=auth_headers(),
        )
        assert after_review.status_code == 200, after_review.text
        review_data = after_review.json()["data"]
        assert review_data["link_suggestion_status_counts"]["approved"] >= 1
        assert review_data["diagnostics"]["link_suggestion_reviewed_count"] >= 1
        reviewed_suggestion = next(
            item for item in review_data["context_link_suggestions"] if item["id"] == suggestion_id
        )
        assert reviewed_suggestion["status"] == "approved"
        assert reviewed_suggestion["review_reason"] == "approved from operations console"
        assert reviewed_suggestion["reviewed_at"]

        retry = client.post(
            f"/v1/asset-extractions/{extraction_id}/retry",
            headers=auth_headers(),
        )
        assert retry.status_code == 202, retry.text
        assert retry.json()["data"]["status"] == "pending"

        after_retry = client.get(
            "/v1/operations-console",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
            },
            headers=auth_headers(),
        )
        assert after_retry.status_code == 200, after_retry.text
        retry_data = after_retry.json()["data"]
        assert retry_data["extraction_status_counts"]["pending"] == 1
        assert retry_data["diagnostics"]["extraction_active_count"] == 1


def test_operations_console_reports_missing_scope_as_empty_diagnostic(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        response = client.get(
            "/v1/operations-console",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "missing-scope",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["generated_at"] is None
    assert data["scope"] is None
    assert data["extraction_status_counts"] == {}
    assert data["link_suggestion_status_counts"] == {}
    assert data["extraction_jobs"] == []
    assert data["context_link_suggestions"] == []
    assert data["diagnostics"] == {"scope_not_found": True}


def test_asset_upload_limit_uses_ingress_error(tmp_path: Path) -> None:
    with make_client(tmp_path, max_asset_upload_bytes=4) as client:
        response = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "filename": "too-large.txt",
            },
            content=b"12345",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "memory.capture.ingress_limited"


def test_asset_upload_rejects_invalid_content_length(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "filename": "bad-length.txt",
            },
            content=b"data",
            headers=auth_headers({"Content-Type": "text/plain", "Content-Length": "not-a-number"}),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "memory.validation"


def test_asset_delete_soft_deletes_and_blocks_reads(tmp_path: Path) -> None:
    asset_storage_dir = tmp_path / "assets"
    with make_client(tmp_path, extraction_enabled=True) as client:
        upload = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "filename": "delete-me.txt",
            },
            content=b"delete me",
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        asset_id = upload.json()["data"]["id"]

        deleted = client.delete(f"/v1/assets/{asset_id}", headers=auth_headers())
        fetched = client.get(f"/v1/assets/{asset_id}", headers=auth_headers())
        stored_list = client.get(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "status": "stored",
            },
            headers=auth_headers(),
        )
        deleted_list = client.get(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "status": "deleted",
            },
            headers=auth_headers(),
        )
        download = client.get(f"/v1/assets/{asset_id}/download", headers=auth_headers())
        extraction = client.post(
            f"/v1/assets/{asset_id}/extractions",
            headers=auth_headers(),
        )

    assert upload.status_code == 201
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert fetched.status_code == 200
    assert fetched.json()["data"]["status"] == "deleted"
    assert stored_list.status_code == 200
    assert stored_list.json()["data"] == []
    assert deleted_list.status_code == 200
    assert deleted_list.json()["data"][0]["id"] == asset_id
    assert download.status_code == 404
    assert extraction.status_code == 404
    assert stored_blob_files(asset_storage_dir) == []


def test_asset_delete_retains_shared_blob_until_last_reference(tmp_path: Path) -> None:
    asset_storage_dir = tmp_path / "assets"
    content = b"shared blob bytes"
    with make_client(tmp_path, extraction_enabled=True) as client:
        first = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-a",
                "filename": "shared.txt",
            },
            content=content,
            headers=auth_headers({"Content-Type": "text/plain"}),
        )
        second = client.post(
            "/v1/assets",
            params={
                "space_slug": "quick-capture",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-b",
                "filename": "shared.txt",
            },
            content=content,
            headers=auth_headers({"Content-Type": "text/plain"}),
        )

        assert first.status_code == 201
        assert second.status_code == 201
        first_id = first.json()["data"]["id"]
        second_id = second.json()["data"]["id"]
        first_delete = client.delete(f"/v1/assets/{first_id}", headers=auth_headers())
        second_download = client.get(f"/v1/assets/{second_id}/download", headers=auth_headers())
        files_after_first_delete = stored_blob_files(asset_storage_dir)
        second_delete = client.delete(f"/v1/assets/{second_id}", headers=auth_headers())
        second_download_after_delete = client.get(
            f"/v1/assets/{second_id}/download",
            headers=auth_headers(),
        )

    assert first_id != second_id
    assert first_delete.status_code == 200
    assert second_download.status_code == 200
    assert second_download.content == content
    assert files_after_first_delete != []
    assert second_delete.status_code == 200
    assert second_download_after_delete.status_code == 404
    assert stored_blob_files(asset_storage_dir) == []


def test_scoped_tokens_can_only_access_assets_and_links_in_their_memory_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'scoped-assets.db'}"
    monkeypatch.setenv("MEMORY_DEPLOY_PROFILE", "test")
    monkeypatch.setenv("MEMORY_DATABASE_URL", database_url)
    monkeypatch.setenv("MEMORY_SERVICE_TOKEN", "root-token")
    asyncio.run(upgrade())

    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=database_url,
            auto_create_schema=True,
            service_token="root-token",
            capture_mode=CaptureMode.SUGGEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "scoped-assets", "name": "Scoped Assets"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        memory_scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "beta", "name": "Beta"},
            headers=root_headers,
        ).json()["data"]
        fact_a = client.post(
            "/v1/facts",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "text": "Alpha asset can link to this fact.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "alpha"}],
            },
            headers=root_headers,
        ).json()["data"]
        upload_a = client.post(
            "/v1/assets",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "filename": "alpha.txt",
            },
            content=b"alpha asset",
            headers={**root_headers, "Content-Type": "text/plain"},
        ).json()["data"]
        upload_b = client.post(
            "/v1/assets",
            params={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "filename": "beta.txt",
            },
            content=b"beta secret asset",
            headers={**root_headers, "Content-Type": "text/plain"},
        ).json()["data"]
        capture_a = client.post(
            "/v1/captures",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "alpha-capture",
                "text": "Alpha asset link fact",
                "source_authority": "user_statement",
                "evidence_refs": [{"source_type": "asset", "source_id": upload_a["id"]}],
            },
            headers=root_headers,
        ).json()["data"]

    scoped = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(memory_scope_a["id"],),
            description="alpha asset scope",
            permissions=("memory:read", "memory:write"),
        )
    )
    scoped_headers = {"Authorization": f"Bearer {scoped['token']}"}

    with TestClient(app) as client:
        same_asset_download = client.get(
            f"/v1/assets/{upload_a['id']}/download",
            headers=scoped_headers,
        )
        cross_asset_download = client.get(
            f"/v1/assets/{upload_b['id']}/download",
            headers=scoped_headers,
        )
        same_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "source_type": "capture",
                "source_id": capture_a["id"],
                "text": "Alpha asset link",
                "persist": True,
            },
            headers=scoped_headers,
        )
        cross_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "text": "beta secret",
            },
            headers=scoped_headers,
        )
        same_link = client.post(
            "/v1/context-links",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "source_type": "capture",
                "source_id": capture_a["id"],
                "target_type": "fact",
                "target_id": fact_a["id"],
                "relation_type": "related_to",
                "confidence": "high",
                "reason": "same scoped memory_scope",
            },
            headers=scoped_headers,
        )
        scoped_review = client.post(
            "/v1/context-link-suggestions/"
            f"{same_suggestions.json()['data']['candidates'][0]['suggestion_id']}/review",
            json={"action": "approve", "reason": "scoped token accepted"},
            headers=scoped_headers,
        )
        cross_link = client.post(
            "/v1/context-links",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_b["id"],
                "source_type": "asset",
                "source_id": upload_b["id"],
                "target_type": "fact",
                "target_id": fact_a["id"],
                "relation_type": "related_to",
                "confidence": "high",
                "reason": "must not cross memory_scope",
            },
            headers=scoped_headers,
        )
        hidden_cross_target = client.post(
            "/v1/context-links",
            json={
                "space_id": space["id"],
                "memory_scope_id": memory_scope_a["id"],
                "source_type": "capture",
                "source_id": capture_a["id"],
                "target_type": "asset",
                "target_id": upload_b["id"],
                "relation_type": "related_to",
                "confidence": "high",
                "reason": "body scope is alpha but target object is beta",
            },
            headers=scoped_headers,
        )

    assert same_asset_download.status_code == 200
    assert same_asset_download.content == b"alpha asset"
    assert cross_asset_download.status_code == 403
    assert same_suggestions.status_code == 200
    assert same_suggestions.json()["data"]["candidates"][0]["status"] == "pending"
    assert cross_suggestions.status_code == 403
    assert same_link.status_code == 200
    assert scoped_review.status_code == 200
    assert scoped_review.json()["data"]["suggestion"]["status"] == "approved"
    assert cross_link.status_code == 403
    assert hidden_cross_target.status_code == 400
    assert hidden_cross_target.json()["error"]["code"] == "memory.validation"
    assert "beta secret asset" not in cross_asset_download.text


async def _age_fact_and_thread(
    client: TestClient,
    *,
    fact_id: str,
    thread_external_ref: str,
    age: timedelta,
) -> None:
    aged_at = client.app.state.container.clock.now() - age
    async with AsyncSession(client.app.state.container.engine) as session:
        await session.execute(
            update(MemoryFactRow)
            .where(MemoryFactRow.id == fact_id)
            .values(created_at=aged_at, updated_at=aged_at)
        )
        await session.execute(
            update(MemoryThreadRow)
            .where(MemoryThreadRow.external_ref == thread_external_ref)
            .values(created_at=aged_at, updated_at=aged_at)
        )
        await session.commit()
