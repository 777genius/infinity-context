import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_server.admin import token_create
from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.db import upgrade
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
        link_id = link.json()["data"]["id"]
        deleted_link = client.delete(
            f"/v1/context-links/{link_id}",
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
    assert {"alex", "frontend", "capture"}.issubset(set(candidate["metadata"]["matched_terms"]))
    assert link.status_code == 200
    assert link.json()["data"]["duplicate"] is False
    assert listed_links.status_code == 200
    assert listed_links.json()["data"][0]["target_id"] == fact.json()["data"]["id"]
    assert deleted_link.status_code == 200
    assert deleted_link.json()["data"]["status"] == "deleted"
    assert active_links_after_delete.status_code == 200
    assert active_links_after_delete.json()["data"] == []
    assert deleted_links.status_code == 200
    assert deleted_links.json()["data"][0]["id"] == link_id


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
    assert repeated.status_code == 200
    assert repeated.json()["data"]["candidates"][0]["suggestion_id"] == suggestion_id
    assert pending.status_code == 200
    assert pending.json()["data"][0]["id"] == suggestion_id
    assert pending.json()["data"][0]["status"] == "pending"
    assert approved.status_code == 200
    assert approved.json()["data"]["suggestion"]["status"] == "approved"
    assert approved.json()["data"]["suggestion"]["review_reason"] == "reviewed by user"
    assert approved.json()["data"]["suggestion"]["reviewed_at"]
    assert approved.json()["data"]["link"]["target_id"] == fact.json()["data"]["id"]
    assert approved.json()["data"]["link"]["reason"] == "reviewed by user"
    assert approved.json()["data"]["duplicate_link"] is False
    assert approve_again.status_code == 200
    assert approve_again.json()["data"]["duplicate_link"] is True
    assert links.status_code == 200
    assert links.json()["data"][0]["target_id"] == fact.json()["data"]["id"]


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
