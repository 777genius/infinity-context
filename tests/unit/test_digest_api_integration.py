from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


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


def test_digest_api_returns_evidence_only_sections(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        fact_payload: dict[str, Any] = {
            "space_slug": "default",
            "memory_scope_external_ref": "engineering",
            "text": "Graphiti is the temporal graph projection engine.",
            "kind": "architecture_decision",
            "source_refs": [{"source_type": "manual", "source_id": "src_fact"}],
        }
        fact_response = client.post("/v1/facts", json=fact_payload, headers=auth_headers())
        assert fact_response.status_code == 201, fact_response.text

        suggestion_payload = {
            "space_slug": "default",
            "memory_scope_external_ref": "engineering",
            "candidate_text": "Add memory_digest as a read-only MCP tool.",
            "kind": "architecture_decision",
            "safe_reason": "review before canonical memory",
            "source_refs": [{"source_type": "manual", "source_id": "src_suggestion"}],
        }
        suggestion_response = client.post(
            "/v1/suggestions",
            json=suggestion_payload,
            headers=auth_headers(),
        )
        assert suggestion_response.status_code == 201, suggestion_response.text

        response = client.post(
            "/v1/digest",
            json={
                "space_slug": "default",
                "memory_scope_external_ref": "engineering",
                "topic": "Graphiti memory digest",
                "include_pending_suggestions": True,
            },
            headers=auth_headers(),
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["diagnostics"]["evidence_only"] is True
        assert "Graphiti is the temporal graph projection engine." in data["rendered_markdown"]
        assert "Add memory_digest as a read-only MCP tool." in data["rendered_markdown"]
        assert "not_canonical" in data["rendered_markdown"]
        assert {section["title"] for section in data["sections"]} >= {
            "Active facts",
            "Pending suggestions",
        }
        assert data["source_refs"]


def test_digest_api_rejects_unknown_fields(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/digest",
            json={"topic": "hello", "unexpected": "raw"},
            headers=auth_headers(),
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "memory.validation"
