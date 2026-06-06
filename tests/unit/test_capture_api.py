import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_server.config import CaptureMode, DeployProfile, MemoryPolicyMode, Settings
from memo_stack_server.main import create_app


def make_client(tmp_path: Path, **overrides: Any) -> TestClient:
    settings_values = {
        "deploy_profile": DeployProfile.TEST,
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
        "auto_create_schema": True,
        "service_token": "test-token",
        "qdrant_enabled": False,
        "graphiti_enabled": False,
        "embeddings_enabled": False,
        "capture_mode": CaptureMode.SUGGEST,
        **overrides,
    }
    app = create_app(
        Settings(**settings_values)
    )
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def capture_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "space_slug": "capture-api",
        "profile_external_ref": "default",
        "thread_external_ref": "thread-1",
        "source_agent": "codex",
        "source_kind": "hook",
        "event_type": "UserPromptSubmit",
        "actor_role": "user",
        "source_event_id": "event-1",
        "text": "Remember: CAPTURE_API_MARKER Graphiti remains the temporal graph.",
        "trust_level": "medium",
        "source_authority": "user_statement",
    }
    payload.update(overrides)
    return payload


def test_capture_create_is_idempotent_and_safe_to_list(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post("/v1/captures", json=capture_payload(), headers=auth_headers())
        second = client.post("/v1/captures", json=capture_payload(), headers=auth_headers())
        listed = client.get(
            "/v1/captures",
            params={"space_slug": "capture-api", "profile_external_ref": "default"},
            headers=auth_headers(),
        )

    assert first.status_code == 201
    assert first.json()["data"]["duplicate"] is False
    assert first.json()["data"]["consolidation_status"] == "pending"
    assert second.status_code == 201
    assert second.json()["data"]["duplicate"] is True
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1
    assert "text_preview" in listed.json()["data"][0]
    assert "Authorization" not in listed.text


def test_capture_consolidates_into_pending_suggestion_only(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post("/v1/captures", json=capture_payload(), headers=auth_headers())
        capture_id = created.json()["data"]["id"]
        consolidated = client.post(
            f"/v1/captures/{capture_id}/consolidate",
            json={},
            headers=auth_headers(),
        )
        suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "status": "pending",
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "query": "CAPTURE_API_MARKER",
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )

    assert consolidated.status_code == 200
    assert consolidated.json()["data"]["created_suggestions"] == 1
    assert suggestions.status_code == 200
    suggestion = suggestions.json()["data"][0]
    assert suggestion["status"] == "pending"
    assert suggestion["operation"] == "add"
    assert suggestion["category"] in {"uncategorized", "project_context", "architecture"}
    assert suggestion["created_from_capture_id"] == capture_id
    assert "CAPTURE_API_MARKER" in suggestion["candidate_text"]
    assert "CAPTURE_API_MARKER" not in context.json()["data"]["rendered_text"]


def test_capture_policy_disabled_blocks_writes(tmp_path: Path) -> None:
    with make_client(tmp_path, capture_mode=CaptureMode.RETRIEVE_ONLY) as client:
        response = client.post("/v1/captures", json=capture_payload(), headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"


def test_capture_manual_only_policy_blocks_automatic_capture(tmp_path: Path) -> None:
    with make_client(
        tmp_path,
        policy_mode=MemoryPolicyMode.MANUAL_ONLY,
        capture_mode=CaptureMode.SUGGEST,
    ) as client:
        response = client.post("/v1/captures", json=capture_payload(), headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "memory.policy_blocked"


def test_capture_only_mode_ignores_client_consolidate_request(tmp_path: Path) -> None:
    with make_client(tmp_path, capture_mode=CaptureMode.CAPTURE_ONLY) as client:
        response = client.post(
            "/v1/captures",
            json=capture_payload(consolidate=True),
            headers=auth_headers(),
        )

    assert response.status_code == 201
    assert response.json()["data"]["consolidation_status"] == "not_required"
    assert response.json()["data"]["created_suggestions"] == 0


def test_capture_secret_is_redacted_or_rejected_before_storage(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="secret-event",
                text="Remember: token=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 must not leak",
            ),
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/captures",
            params={"space_slug": "capture-api", "profile_external_ref": "default"},
            headers=auth_headers(),
        )

    assert response.status_code == 201
    assert "sk-proj" not in listed.text
    assert "[redacted-secret]" in listed.text


def test_capture_text_ingress_limit_uses_stable_public_error(tmp_path: Path) -> None:
    with make_client(tmp_path, max_capture_text_chars=120) as client:
        response = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="oversized-event",
                text=f"Remember: {'x' * 140}",
            ),
            headers=auth_headers(),
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "memory.capture.ingress_limited"
    assert response.json()["error"]["retryable"] is True


def test_capture_pending_ingress_limit_allows_idempotent_retry(tmp_path: Path) -> None:
    with make_client(tmp_path, max_pending_captures_per_profile=1) as client:
        first = client.post(
            "/v1/captures",
            json=capture_payload(source_event_id="pending-limit-first"),
            headers=auth_headers(),
        )
        duplicate = client.post(
            "/v1/captures",
            json=capture_payload(source_event_id="pending-limit-first"),
            headers=auth_headers(),
        )
        second = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="pending-limit-second",
                text="Remember: CAPTURE_API_PENDING_LIMIT second new event.",
            ),
            headers=auth_headers(),
        )

    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["duplicate"] is True
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "memory.capture.ingress_limited"


def test_capture_metadata_is_sanitized_before_canonical_storage(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="metadata-sanitize-event",
                metadata={
                    "client_minimization_version": "hook-v1",
                    "safe_scalar": "ok",
                    "nested": {"raw": "should not be stored"},
                    "token": "secret-token-value",
                    "long": "x" * 900,
                },
            ),
            headers=auth_headers(),
        )
        capture_id = created.json()["data"]["id"]

        async def load_metadata() -> dict[str, object]:
            async with client.app.state.container.uow_factory() as uow:
                capture = await uow.captures.get_by_id(capture_id)
                assert capture is not None
                return dict(capture.metadata)

        metadata = asyncio.run(load_metadata())

    assert created.status_code == 201
    assert metadata["client_minimization_version"] == "hook-v1"
    assert metadata["safe_scalar"] == "ok"
    assert metadata["admission_reason"] == "accepted"
    assert "nested" not in metadata
    assert "token" not in metadata
    assert metadata["long"] == "x" * 500


def test_capture_consolidation_respects_pending_suggestion_limit(tmp_path: Path) -> None:
    with make_client(tmp_path, max_pending_suggestions_per_profile=1) as client:
        first = client.post(
            "/v1/captures",
            json=capture_payload(source_event_id="suggestion-limit-first"),
            headers=auth_headers(),
        )
        first_consolidated = client.post(
            f"/v1/captures/{first.json()['data']['id']}/consolidate",
            json={},
            headers=auth_headers(),
        )
        second = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="suggestion-limit-second",
                text="Remember: CAPTURE_API_SUGGESTION_LIMIT second suggestion blocked.",
            ),
            headers=auth_headers(),
        )
        second_consolidated = client.post(
            f"/v1/captures/{second.json()['data']['id']}/consolidate",
            json={},
            headers=auth_headers(),
        )
        suggestions = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "status": "pending",
            },
            headers=auth_headers(),
        )

    assert first_consolidated.status_code == 200
    assert first_consolidated.json()["data"]["created_suggestions"] == 1
    assert second.status_code == 201
    assert second_consolidated.status_code == 200
    assert second_consolidated.json()["data"]["consolidation_status"] == "consolidated"
    assert second_consolidated.json()["data"]["created_suggestions"] == 0
    assert suggestions.status_code == 200
    assert len(suggestions.json()["data"]) == 1


def test_capture_privacy_purge_redacts_evidence_and_keeps_idempotency(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="purge-event",
                evidence_refs=[
                    {
                        "source_type": "hook",
                        "source_id": "purge-event",
                        "char_start": 0,
                        "char_end": 30,
                        "quote_preview": "Remember: CAPTURE_PURGE_MARKER",
                    }
                ],
                text="Remember: CAPTURE_PURGE_MARKER raw private evidence.",
            ),
            headers=auth_headers(),
        )
        capture_id = created.json()["data"]["id"]
        purged = client.request(
            "DELETE",
            f"/v1/captures/{capture_id}",
            json={"reason": "test privacy purge"},
            headers=auth_headers(),
        )
        fetched = client.get(f"/v1/captures/{capture_id}", headers=auth_headers())
        duplicate = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="purge-event",
                text="Remember: CAPTURE_PURGE_MARKER raw private evidence.",
            ),
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert purged.status_code == 200
    assert purged.json()["data"]["status"] == "purged"
    assert purged.json()["data"]["text_preview"] == "[purged]"
    assert purged.json()["data"]["evidence_refs"][0]["quote_preview"] == "[purged]"
    assert purged.json()["data"]["evidence_refs"][0]["char_start"] is None
    assert fetched.status_code == 200
    assert "CAPTURE_PURGE_MARKER" not in fetched.text
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["duplicate"] is True
    assert duplicate.json()["data"]["status"] == "purged"


def test_capture_privacy_purge_expires_pending_suggestions(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/captures",
            json=capture_payload(
                source_event_id="purge-suggestion-event",
                text="Remember: CAPTURE_PURGE_SUGGESTION_MARKER should not remain pending.",
            ),
            headers=auth_headers(),
        )
        capture_id = created.json()["data"]["id"]
        consolidated = client.post(
            f"/v1/captures/{capture_id}/consolidate",
            json={},
            headers=auth_headers(),
        )
        pending_before = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "status": "pending",
            },
            headers=auth_headers(),
        )
        suggestion_id = pending_before.json()["data"][0]["id"]
        purged = client.request(
            "DELETE",
            f"/v1/captures/{capture_id}",
            json={"reason": "test privacy purge"},
            headers=auth_headers(),
        )
        pending_after = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "status": "pending",
            },
            headers=auth_headers(),
        )
        expired_after = client.get(
            "/v1/suggestions",
            params={
                "space_slug": "capture-api",
                "profile_external_ref": "default",
                "status": "expired",
            },
            headers=auth_headers(),
        )
        approve = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": "should not approve purged capture suggestion"},
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert consolidated.status_code == 200
    assert consolidated.json()["data"]["created_suggestions"] == 1
    assert pending_before.status_code == 200
    assert pending_before.json()["data"][0]["created_from_capture_id"] == capture_id
    assert "CAPTURE_PURGE_SUGGESTION_MARKER" in pending_before.text
    assert purged.status_code == 200
    assert pending_after.status_code == 200
    assert pending_after.json()["data"] == []
    assert expired_after.status_code == 200
    assert expired_after.json()["data"][0]["id"] == suggestion_id
    assert expired_after.json()["data"][0]["status"] == "expired"
    assert expired_after.json()["data"][0]["review_reason"] == "capture_privacy_purged"
    assert approve.status_code == 409
