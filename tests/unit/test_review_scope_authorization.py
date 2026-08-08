import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_server.admin import token_create
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.db import upgrade
from infinity_context_server.main import create_app


def test_govern_token_can_review_only_its_memory_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'review_scope.db'}"
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
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    root_headers = {"Authorization": "Bearer root-token"}
    with TestClient(app) as client:
        space = client.post(
            "/v1/spaces",
            json={"slug": "review-scope", "name": "Review Scope"},
            headers=root_headers,
        ).json()["data"]
        scope_a = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "alpha", "name": "Alpha"},
            headers=root_headers,
        ).json()["data"]
        scope_b = client.post(
            "/v1/memory-scopes",
            json={"space_id": space["id"], "external_ref": "beta", "name": "Beta"},
            headers=root_headers,
        ).json()["data"]

        def suggest(memory_scope_id: str, source_id: str) -> dict:
            return client.post(
                "/v1/suggestions",
                json={
                    "space_id": space["id"],
                    "memory_scope_id": memory_scope_id,
                    "candidate_text": f"Scoped review {source_id}.",
                    "kind": "note",
                    "safe_reason": "scope_test",
                    "source_refs": [{"source_type": "manual", "source_id": source_id}],
                },
                headers=root_headers,
            ).json()["data"]

        suggestion_a = suggest(scope_a["id"], "review-a")
        suggestion_b = suggest(scope_b["id"], "review-b")

    reviewer = asyncio.run(
        token_create(
            space_id=space["id"],
            memory_scope_ids=(scope_a["id"],),
            description="alpha reviewer",
            permissions=("memory:govern",),
        )
    )
    govern_headers = {"Authorization": f"Bearer {reviewer['token']}"}
    with TestClient(app) as client:
        same_scope = client.post(
            f"/v1/suggestions/{suggestion_a['id']}/approve",
            json={"reason": "authorized scoped review"},
            headers=govern_headers,
        )
        cross_scope = client.post(
            f"/v1/suggestions/{suggestion_b['id']}/reject",
            json={"reason": "must not cross scope"},
            headers=govern_headers,
        )

    assert same_scope.status_code == 200
    assert (
        same_scope.json()["data"]["suggestion"]["review_payload"]["canonical_review_actor_id"]
        == reviewer["token_id"]
    )
    assert cross_scope.status_code == 403
