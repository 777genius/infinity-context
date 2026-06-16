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


def test_context_link_suggestions_support_all_and_multi_status_filters(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "text": "Alex Project Atlas review evidence should be linked to captures.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-review"}],
                "tags": ["alex", "atlas"],
            },
            headers=auth_headers({"Idempotency-Key": "review-history-fact"}),
        )
        assert fact.status_code == 201, fact.text
        approved_capture = _create_capture(
            client,
            source_event_id="approved-link-source",
            text="Approved Project Atlas capture from Alex review.",
        )
        rejected_capture = _create_capture(
            client,
            source_event_id="rejected-link-source",
            text="Rejected Project Atlas capture from Alex review.",
        )

        approved_suggestion_id = _persist_first_suggestion(
            client,
            source_id=approved_capture.json()["data"]["id"],
            text="Alex Project Atlas approved capture",
        )
        rejected_suggestion_id = _persist_first_suggestion(
            client,
            source_id=rejected_capture.json()["data"]["id"],
            text="Alex Project Atlas rejected capture",
        )
        approved = client.post(
            f"/v1/context-link-suggestions/{approved_suggestion_id}/review",
            json={"action": "approve", "reason": "confirmed by reviewer"},
            headers=auth_headers(),
        )
        rejected = client.post(
            f"/v1/context-link-suggestions/{rejected_suggestion_id}/review",
            json={"action": "reject", "reason": "not the right context"},
            headers=auth_headers(),
        )
        review_history = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "statuses": "approved,rejected",
                "limit": "50",
            },
            headers=auth_headers(),
        )
        all_history = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "status": "all",
                "limit": "50",
            },
            headers=auth_headers(),
        )
        approved_source_history = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": approved_capture.json()["data"]["id"],
                "statuses": "approved,rejected",
                "limit": "50",
            },
            headers=auth_headers(),
        )
        link_history = client.get(
            "/v1/context-links",
            params={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "statuses": "active,deleted",
                "limit": "50",
            },
            headers=auth_headers(),
        )

    assert approved.status_code == 200, approved.text
    assert rejected.status_code == 200, rejected.text
    assert review_history.status_code == 200, review_history.text
    review_items = review_history.json()["data"]
    assert {item["status"] for item in review_items} <= {"approved", "rejected"}
    assert approved_suggestion_id in {item["id"] for item in review_items}
    assert rejected_suggestion_id in {item["id"] for item in review_items}
    assert all_history.status_code == 200, all_history.text
    assert {approved_suggestion_id, rejected_suggestion_id}.issubset(
        {item["id"] for item in all_history.json()["data"]}
    )
    assert approved_source_history.status_code == 200, approved_source_history.text
    assert [item["id"] for item in approved_source_history.json()["data"]] == [
        approved_suggestion_id
    ]
    assert link_history.status_code == 200, link_history.text
    assert link_history.json()["data"][0]["status"] == "active"


def test_context_link_suggestions_batch_review_applies_mixed_actions(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-review",
                "text": "Alex Project Atlas review links should support batch actions.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "batch-review"}],
                "tags": ["alex", "atlas"],
            },
            headers=auth_headers({"Idempotency-Key": "review-history-batch-fact"}),
        )
        assert fact.status_code == 201, fact.text
        approved_capture = _create_capture(
            client,
            source_event_id="batch-approved-link-source",
            text="Batch approved Project Atlas capture from Alex review.",
        )
        rejected_capture = _create_capture(
            client,
            source_event_id="batch-rejected-link-source",
            text="Batch rejected Project Atlas capture from Alex review.",
        )
        approved_suggestion_id = _persist_first_suggestion(
            client,
            source_id=approved_capture.json()["data"]["id"],
            text="Alex Project Atlas batch approved capture",
        )
        rejected_suggestion_id = _persist_first_suggestion(
            client,
            source_id=rejected_capture.json()["data"]["id"],
            text="Alex Project Atlas batch rejected capture",
        )

        batch = client.post(
            "/v1/context-link-suggestions/review-batch",
            json={
                "items": [
                    {
                        "suggestion_id": approved_suggestion_id,
                        "action": "approve",
                        "reason": "batch confirmed",
                        "link_reason": "batch confirmed link",
                    },
                    {
                        "suggestion_id": rejected_suggestion_id,
                        "action": "reject",
                        "reason": "batch rejected",
                    },
                ],
            },
            headers=auth_headers(),
        )
        duplicate_approve = client.post(
            "/v1/context-link-suggestions/review-batch",
            json={
                "items": [
                    {
                        "suggestion_id": approved_suggestion_id,
                        "action": "approve",
                    },
                ],
            },
            headers=auth_headers(),
        )
        review_history = client.get(
            "/v1/context-link-suggestions",
            params={
                "space_slug": "review-history",
                "memory_scope_external_ref": "default",
                "statuses": "approved,rejected",
                "limit": "50",
            },
            headers=auth_headers(),
        )

    assert batch.status_code == 200, batch.text
    data = batch.json()["data"]
    assert data["applied"] == 2
    assert data["failed"] == 0
    assert data["stopped"] is False
    approved_item, rejected_item = data["results"]
    assert approved_item["suggestion_id"] == approved_suggestion_id
    assert approved_item["status"] == "applied"
    assert approved_item["suggestion"]["status"] == "approved"
    assert approved_item["suggestion"]["review_reason"] == "batch confirmed"
    assert approved_item["link"]["reason"] == "batch confirmed link"
    assert approved_item["duplicate_link"] is False
    assert rejected_item["suggestion_id"] == rejected_suggestion_id
    assert rejected_item["status"] == "applied"
    assert rejected_item["suggestion"]["status"] == "rejected"
    assert rejected_item["suggestion"]["review_reason"] == "batch rejected"
    assert rejected_item["link"] is None
    assert duplicate_approve.status_code == 200, duplicate_approve.text
    duplicate_item = duplicate_approve.json()["data"]["results"][0]
    assert duplicate_item["status"] == "applied"
    assert duplicate_item["duplicate_link"] is True
    assert review_history.status_code == 200, review_history.text
    assert {approved_suggestion_id, rejected_suggestion_id}.issubset(
        {item["id"] for item in review_history.json()["data"]}
    )


def _create_capture(
    client: TestClient,
    *,
    source_event_id: str,
    text: str,
) -> Any:
    return client.post(
        "/v1/captures",
        json={
            "space_slug": "review-history",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "atlas-review",
            "source_agent": "memo-frontend",
            "source_kind": "manual",
            "event_type": "QuickCapture",
            "actor_role": "user",
            "source_event_id": source_event_id,
            "text": text,
            "source_authority": "user_statement",
        },
        headers=auth_headers(),
    )


def _persist_first_suggestion(client: TestClient, *, source_id: str, text: str) -> str:
    response = client.post(
        "/v1/link-suggestions",
        json={
            "space_slug": "review-history",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "atlas-review",
            "source_type": "capture",
            "source_id": source_id,
            "text": text,
            "persist": True,
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200, response.text
    candidates = response.json()["data"]["candidates"]
    candidate = next(item for item in candidates if item["suggestion_id"])
    suggestion_id = candidate["suggestion_id"]
    assert suggestion_id
    return suggestion_id
