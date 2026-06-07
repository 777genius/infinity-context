import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.models import MemoryFactRow
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


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


async def expire_fact(client: TestClient, fact_id: str) -> None:
    engine = client.app.state.container.engine
    async with AsyncSession(engine) as session:
        await session.execute(
            update(MemoryFactRow)
            .where(MemoryFactRow.id == fact_id)
            .values(expires_at=datetime.now(tz=UTC) - timedelta(minutes=1))
        )
        await session.commit()


def test_remember_fact_persists_normalized_taxonomy_and_filters_by_tag(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Fact taxonomy belongs to canonical facts.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "taxonomy"}],
                "category": "Architecture",
                "tags": ["Graphiti", "Graphiti", "Memory"],
                "ttl_policy": "durable",
            },
            headers=auth_headers(),
        )
        listed = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "category": "architecture",
                "tag": "memory",
            },
            headers=auth_headers(),
        )

    assert created.status_code == 201
    fact = created.json()["data"]
    assert fact["category"] == "architecture"
    assert fact["tags"] == ["graphiti", "memory"]
    assert fact["ttl_policy"] == "durable"
    assert fact["expires_at"] is None
    assert [item["id"] for item in listed.json()["data"]] == [fact["id"]]


def test_approved_suggestion_preserves_taxonomy_on_created_fact(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        suggestion = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "candidate_text": "Task memory should expire from active context.",
                "kind": "note",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": "taxonomy-review"}],
                "category": "current_task",
                "tags": ["todo"],
                "ttl_policy": "task",
            },
            headers=auth_headers(),
        )
        suggestion_id = suggestion.json()["data"]["id"]
        approved = client.post(
            f"/v1/suggestions/{suggestion_id}/approve",
            json={"reason": "reviewed"},
            headers=auth_headers(),
        )

    assert suggestion.status_code == 201
    assert approved.status_code == 200
    fact = approved.json()["data"]["fact"]
    assert fact["category"] == "current_task"
    assert fact["tags"] == ["todo"]
    assert fact["ttl_policy"] == "task"


def test_expired_active_fact_is_hidden_from_active_memory_surfaces(tmp_path: Path) -> None:
    marker = "EXPIRED_FACT_CONTEXT_MARKER"
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": f"{marker} should be auditable but absent from active context.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "ttl"}],
                "category": "current_task",
                "ttl_policy": "task",
            },
            headers=auth_headers(),
        )
        fact_id = created.json()["data"]["id"]
        asyncio.run(expire_fact(client, fact_id))

        listed = client.get(
            "/v1/facts",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "status": "active",
            },
            headers=auth_headers(),
        )
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": marker,
                "max_facts": 5,
                "max_chunks": 0,
                "token_budget": 512,
            },
            headers=auth_headers(),
        )
        exported = client.get(
            "/v1/export/graph.json",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "max_documents": 0,
                "max_chunks": 0,
            },
            headers=auth_headers(),
        )
        direct = client.get(f"/v1/facts/{fact_id}", headers=auth_headers())

    assert created.status_code == 201
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == []
    assert context.status_code == 200
    assert marker not in context.json()["data"]["rendered_text"]
    assert exported.status_code == 200
    assert exported.json()["data"]["counts"]["facts"] == 0
    assert direct.status_code == 200
    assert direct.json()["data"]["id"] == fact_id


def test_search_filters_active_facts_by_category_and_tags(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for text, category, tags in (
            (
                "FILTERED_TAXONOMY_MARKER: Graphiti memory owns temporal facts.",
                "architecture",
                ["graphiti", "memory"],
            ),
            (
                "FILTERED_TAXONOMY_MARKER: Redis memory cache is unrelated.",
                "debug_notes",
                ["redis"],
            ),
        ):
            client.post(
                "/v1/facts",
                json={
                    "space_id": "space_client_app",
                    "profile_id": "profile_default",
                    "text": text,
                    "kind": "note",
                    "source_refs": [{"source_type": "manual", "source_id": text[:16]}],
                    "category": category,
                    "tags": tags,
                },
                headers=auth_headers(),
            )
        filtered = client.post(
            "/v1/search",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "query": "FILTERED_TAXONOMY_MARKER memory",
                "max_facts": 10,
                "max_chunks": 0,
                "category": "Architecture",
                "tags_all": ["Memory"],
                "tags_none": ["redis"],
            },
            headers=auth_headers(),
        )

    assert filtered.status_code == 200
    items = filtered.json()["data"]["items"]
    assert [item["text"] for item in items] == [
        "FILTERED_TAXONOMY_MARKER: Graphiti memory owns temporal facts."
    ]
