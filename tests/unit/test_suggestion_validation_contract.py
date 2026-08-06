from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
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
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "candidate_text": "Use Postgres as canonical truth.",
        "kind": "architecture_decision",
        "safe_reason": "manual_review",
        "source_refs": [{"source_type": "manual", "source_id": "review-1"}],
    }
    payload.update(overrides)
    return payload


def test_create_suggestion_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json=_payload(unexpected_raw_payload="must not be ignored"),
            headers={"Authorization": "Bearer test-token"},
        )

    assert created.status_code == 400
    assert created.json()["error"]["code"] == "memory.validation"


def test_create_suggestion_rejects_unknown_source_ref_fields(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/v1/suggestions",
            json=_payload(
                source_refs=[
                    {
                        "source_type": "manual",
                        "source_id": "strict-ref",
                        "unknown_raw_path": "/private/session.jsonl",
                    }
                ]
            ),
            headers={"Authorization": "Bearer test-token"},
        )

    assert created.status_code == 400
    assert created.json()["error"]["code"] == "memory.validation"
