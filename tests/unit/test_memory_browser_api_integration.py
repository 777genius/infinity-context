from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.main import create_app


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


def test_memory_browser_returns_scope_threads_evidence_anchors_and_links(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "text": "Alex confirmed Project Atlas file memory requirements.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "atlas-fact"}],
            },
            headers=auth_headers({"Idempotency-Key": "browser-fact"}),
        )
        assert fact.status_code == 201, fact.text

        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "title": "Project Atlas notes",
                "text": "Project Atlas document memory should appear in the browser.",
                "source_type": "document",
                "source_external_id": "atlas-doc",
            },
            headers=auth_headers({"Idempotency-Key": "browser-document"}),
        )
        assert document.status_code == 201, document.text

        episode = client.post(
            "/v1/episodes",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "source_type": "transcript",
                "source_external_id": "atlas-call-episode",
                "text": "Alex call episode captured Project Atlas memory requirements.",
                "speaker": "user",
            },
            headers=auth_headers(),
        )
        assert episode.status_code == 200, episode.text
        episode_id = episode.json()["data"]["episode_id"]

        asset = client.post(
            "/v1/assets",
            params={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "filename": "atlas.png",
                "extract": True,
            },
            content=b"fake image bytes",
            headers=auth_headers({"Content-Type": "image/png"}),
        )
        assert asset.status_code == 201, asset.text
        extraction_id = asset.json()["data"]["extraction"]["id"]

        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "browser-capture",
                "text": "Screenshot from Alex for Project Atlas file memory.",
                "source_authority": "user_statement",
                "evidence_refs": [
                    {"source_type": "asset", "source_id": asset.json()["data"]["id"]}
                ],
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "thread_external_ref": "alex-call",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "text": "Alex Project Atlas file memory",
                "persist": True,
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text
        assert suggestions.json()["data"]["candidates"]

        link = client.post(
            "/v1/context-links",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "source_type": "capture",
                "source_id": capture.json()["data"]["id"],
                "target_type": "fact",
                "target_id": fact.json()["data"]["id"],
                "relation_type": "related_to",
                "confidence": "high",
                "reason": "same person and same project",
            },
            headers=auth_headers(),
        )
        assert link.status_code == 200, link.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "limit_per_source": 30,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        browser = client.get(
            "/v1/memory-browser",
            params={
                "space_slug": "browser",
                "memory_scope_external_ref": "project-atlas",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert browser.status_code == 200, browser.text

    data = browser.json()["data"]
    assert data["memory_scope"]["external_ref"] == "project-atlas"
    assert {item["id"] for item in data["facts"]} == {fact.json()["data"]["id"]}
    assert {item["id"] for item in data["episodes"]} == {episode_id}
    assert {item["id"] for item in data["documents"]} == {document.json()["data"]["id"]}
    assert any(
        item["document_id"] == document.json()["data"]["id"]
        and item["text"] == "Project Atlas document memory should appear in the browser."
        for item in data["chunks"]
    )
    assert any(
        item["episode_id"] == episode_id
        and item["text"] == "Alex call episode captured Project Atlas memory requirements."
        for item in data["chunks"]
    )
    assert {item["id"] for item in data["extraction_jobs"]} == {extraction_id}
    assert {item["external_ref"] for item in data["threads"]} == {"alex-call"}
    assert {item["id"] for item in data["captures"]} == {capture.json()["data"]["id"]}
    assert {item["id"] for item in data["assets"]} == {asset.json()["data"]["id"]}
    assert any(item["label"] == "Alex" for item in data["anchors"])
    assert any(item["label"] == "Atlas" for item in data["anchors"])
    assert {item["id"] for item in data["context_links"]} == {link.json()["data"]["id"]}
    assert data["context_link_suggestions"]
    assert data["stats"]["facts"] == 1
    assert data["stats"]["episodes"] == 1
    assert data["stats"]["documents"] == 1
    assert data["stats"]["chunks"] == 2
    assert data["stats"]["extraction_jobs"] == 1
    assert data["stats"]["threads"] == 1
    assert data["stats"]["active_context_links"] == 1
    assert data["visual_summary"]["status"] == "review_needed"
    assert data["visual_summary"]["evidence_count"] == 7
    assert data["visual_summary"]["active_link_count"] == 1
    assert data["visual_summary"]["pending_review_count"] >= 1
    assert "pending_review" in data["visual_summary"]["health_hints"]
    assert "captures" in data["visual_summary"]["visible_sources"]
    assert data["quick_actions"][0]["id"] == "review_pending_links"
    assert data["diagnostics"]["browser_version"] == "memory-browser-v1"
    assert data["diagnostics"]["visual_summary_version"] == "visual-memory-summary-v1"
    assert data["diagnostics"]["statuses"]["episode"] == "active"
    assert data["diagnostics"]["statuses"]["chunk"] == "active"


def test_memory_browser_empty_scope_response_includes_visual_next_action(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        browser = client.get(
            "/v1/memory-browser",
            params={
                "space_slug": "browser",
                "memory_scope_external_ref": "missing-scope",
            },
            headers=auth_headers(),
        )
        assert browser.status_code == 200, browser.text

    data = browser.json()["data"]
    assert data["memory_scope"] is None
    assert data["visual_summary"]["status"] == "empty"
    assert data["visual_summary"]["health_hints"] == ["scope_not_found", "empty_scope"]
    assert data["quick_actions"][0]["id"] == "create_memory_scope"
