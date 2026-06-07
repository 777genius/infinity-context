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


def test_memory_insights_reports_review_and_taxonomy_state(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        active = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Insights should count categorized memory facts.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "insights-active"}],
                "category": "architecture",
                "tags": ["memory", "review"],
                "ttl_policy": "durable",
            },
            headers=auth_headers(),
        )
        similar_a = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": (
                    "Memo Stack should use Graphiti as the temporal graph adapter "
                    "for coding agent memory."
                ),
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "insights-similar-a"}],
                "category": "architecture",
                "tags": ["memory", "graph"],
            },
            headers=auth_headers(),
        )
        similar_b = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": (
                    "Memo Stack should use Graphiti as temporal graph engine adapter "
                    "for coding-agent memory."
                ),
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "insights-similar-b"}],
                "category": "architecture",
                "tags": ["memory", "graph"],
            },
            headers=auth_headers(),
        )
        expiring = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "INSIGHTS_EXPIRED_MARKER should become an action item.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "insights-expired"}],
                "category": "current_task",
                "tags": ["todo"],
                "ttl_policy": "task",
            },
            headers=auth_headers(),
        )
        suggestion = client.post(
            "/v1/suggestions",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "candidate_text": "Insights should expose pending review workload.",
                "kind": "note",
                "safe_reason": "manual_review",
                "source_refs": [{"source_type": "manual", "source_id": "insights-suggestion"}],
                "category": "review",
                "tags": ["memory"],
            },
            headers=auth_headers(),
        )
        asyncio.run(expire_fact(client, expiring.json()["data"]["id"]))

        insights = client.post(
            "/v1/insights",
            json={
                "space_id": "space_client_app",
                "profile_ids": ["profile_default"],
                "max_facts": 20,
                "max_suggestions": 20,
                "max_activity": 10,
            },
            headers=auth_headers(),
        )

    assert active.status_code == 201
    assert similar_a.status_code == 201
    assert similar_b.status_code == 201
    assert expiring.status_code == 201
    assert suggestion.status_code == 201
    assert insights.status_code == 200
    data = insights.json()["data"]
    assert data["diagnostics"]["evidence_only"] is True
    assert data["diagnostics"]["read_only"] is True
    assert data["health_score"] < 100
    assert data["metrics"]["facts"]["expired_active"] == 1
    assert data["metrics"]["suggestions"]["pending"] == 1
    assert {"value": "architecture", "count": 3} in data["taxonomy"]["top_categories"]
    actions = {item["action"] for item in data["action_items"]}
    similar_action = next(
        item for item in data["action_items"] if item["action"] == "review_similar_facts"
    )
    assert "review_expired_fact" in actions
    assert "review_pending_suggestions" in actions
    assert similar_action["metadata"]["match_type"] == "same_kind_category_token_overlap"
    assert similar_action["metadata"]["similarity"] >= 0.82
    plan = data["consolidation_plan"][0]
    assert plan["plan_type"] == "similar_fact_review"
    assert plan["confidence"] == "medium"
    assert plan["canonical_candidate_id"] == similar_action["metadata"]["canonical_candidate_id"]
    assert plan["candidate_fact_ids"] == similar_action["metadata"]["similar_fact_ids"]
    assert any("Do not merge automatically" in step for step in plan["recommended_steps"])
    activity_types = {item["event_type"] for item in data["recent_activity"]}
    assert {"fact_created", "suggestion_created"} <= activity_types
    assert all(item["preview"] for item in data["recent_activity"])
    assert data["diagnostics"]["max_activity"] == 10
