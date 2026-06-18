import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_adapters.postgres.fact_repositories import PostgresFactRelationRepository
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
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


def fact_payload(text: str, *, memory_scope_id: str = "memory_scope_default") -> dict[str, Any]:
    return {
        "space_id": "space_client_app",
        "memory_scope_id": memory_scope_id,
        "text": text,
        "kind": "architecture_decision",
        "source_refs": [{"source_type": "manual", "source_id": text[:40]}],
    }


def create_fact(
    client: TestClient, text: str, *, memory_scope_id: str = "memory_scope_default"
) -> str:
    response = client.post(
        "/v1/facts",
        json=fact_payload(text, memory_scope_id=memory_scope_id),
        headers=auth_headers(),
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


def test_fact_relations_link_list_unlink_and_relink(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_SOURCE: Postgres is canonical truth.")
        target_id = create_fact(client, "RELATION_TARGET: Graphiti is derived temporal graph.")
        observed_at = "2026-01-02T12:00:00+00:00"
        valid_from = "2026-01-01T00:00:00+00:00"
        valid_to = "2026-02-01T00:00:00+00:00"

        linked = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supports",
                "reason": "ADR says Graphiti remains a derived adapter.",
                "observed_at": observed_at,
                "valid_from": valid_from,
                "valid_to": valid_to,
            },
            headers=auth_headers(),
        )
        repeated = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supports",
                "reason": "Duplicate request should be idempotent.",
            },
            headers=auth_headers(),
        )
        listed = client.get(f"/v1/facts/{source_id}/relations", headers=auth_headers())
        deleted = client.delete(
            f"/v1/facts/relations/{linked.json()['data']['id']}",
            headers=auth_headers(),
        )
        deleted_list = client.get(
            f"/v1/facts/{source_id}/relations?status=deleted",
            headers=auth_headers(),
        )
        relinked = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supports",
                "reason": "Active relation can be recreated after unlink.",
            },
            headers=auth_headers(),
        )

    assert linked.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["data"]["id"] == linked.json()["data"]["id"]
    assert linked.json()["data"]["observed_at"] == observed_at
    assert linked.json()["data"]["valid_from"] == valid_from
    assert linked.json()["data"]["valid_to"] == valid_to
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["direction"] == "outgoing"
    assert listed.json()["data"]["items"][0]["relation"]["relation_type"] == "supports"
    assert listed.json()["data"]["items"][0]["relation"]["valid_to"].startswith(
        "2026-02-01T00:00:00"
    )
    assert listed.json()["data"]["items"][0]["related_fact"]["id"] == target_id
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert deleted_list.status_code == 200
    assert deleted_list.json()["data"]["items"][0]["relation"]["status"] == "deleted"
    assert relinked.status_code == 201
    assert relinked.json()["data"]["id"] != linked.json()["data"]["id"]
    assert relinked.json()["data"]["observed_at"] is not None
    assert relinked.json()["data"]["valid_from"] is None
    assert relinked.json()["data"]["valid_to"] is None


def test_fact_relations_batch_list_enforces_limit_per_fact(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first_source_id = create_fact(client, "RELATION_BATCH_LIMIT: first source.")
        second_source_id = create_fact(client, "RELATION_BATCH_LIMIT: second source.")
        target_ids = [
            create_fact(client, f"RELATION_BATCH_LIMIT: target {index}.") for index in range(4)
        ]

        second_relation = client.post(
            f"/v1/facts/{second_source_id}/relations",
            json={
                "target_fact_id": target_ids[0],
                "relation_type": "related_to",
                "reason": "Second source relation should not be starved by first source.",
            },
            headers=auth_headers(),
        )
        first_relations = [
            client.post(
                f"/v1/facts/{first_source_id}/relations",
                json={
                    "target_fact_id": target_id,
                    "relation_type": "related_to",
                    "reason": "First source has multiple newer relations.",
                },
                headers=auth_headers(),
            )
            for target_id in target_ids[1:]
        ]

        async def load_batch() -> dict[str, list[object]]:
            async with AsyncSession(client.app.state.container.engine) as session:
                repository = PostgresFactRelationRepository(session)
                return await repository.list_for_facts(
                    fact_ids=(first_source_id, second_source_id),
                    status="active",
                    limit_per_fact=1,
                )

        relations_by_fact_id = asyncio.run(load_batch())

    assert second_relation.status_code == 201, second_relation.text
    assert all(relation.status_code == 201 for relation in first_relations)
    assert set(relations_by_fact_id) == {first_source_id, second_source_id}
    assert len(relations_by_fact_id[first_source_id]) == 1
    assert len(relations_by_fact_id[second_source_id]) == 1
    assert str(relations_by_fact_id[first_source_id][0].source_fact_id) == first_source_id
    assert str(relations_by_fact_id[second_source_id][0].source_fact_id) == second_source_id


def test_fact_relations_reject_invalid_temporal_range(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_TEMPORAL: current fact.")
        target_id = create_fact(client, "RELATION_TEMPORAL: previous fact.")
        response = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supersedes",
                "reason": "New fact replaces the old fact.",
                "valid_from": "2026-02-01T00:00:00+00:00",
                "valid_to": "2026-01-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )

    assert response.status_code == 400


def test_fact_relations_reject_duplicate_with_different_temporal_window(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_TEMPORAL_DUPLICATE: current fact.")
        target_id = create_fact(client, "RELATION_TEMPORAL_DUPLICATE: previous fact.")
        linked = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supersedes",
                "reason": "Current fact supersedes previous fact in January.",
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        repeated_same_window = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supersedes",
                "reason": "Duplicate request with the same temporal window.",
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        conflicting_window = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supersedes",
                "reason": "Duplicate request with a different temporal window.",
                "valid_from": "2026-02-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )

    assert linked.status_code == 201, linked.text
    assert repeated_same_window.status_code == 201, repeated_same_window.text
    assert repeated_same_window.json()["data"]["id"] == linked.json()["data"]["id"]
    assert conflicting_window.status_code == 409, conflicting_window.text
    assert "different temporal fields" in conflicting_window.text


def test_contradicts_relation_marks_target_disputed_and_context_hides_it(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        old_id = create_fact(
            client,
            "CONTRADICTED_OLD_FACT: legacy billing owner is Alex.",
        )
        new_id = create_fact(
            client,
            "CONTRADICTING_NEW_FACT: billing owner is Dana, not legacy Alex.",
        )
        linked = client.post(
            f"/v1/facts/{new_id}/relations",
            json={
                "target_fact_id": old_id,
                "relation_type": "contradicts",
                "reason": "New owner evidence contradicts the old owner fact.",
                "observed_at": "2026-01-02T12:00:00+00:00",
            },
            headers=auth_headers(),
        )
        old_fact = client.get(f"/v1/facts/{old_id}", headers=auth_headers())
        context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "legacy billing owner Alex",
                "token_budget": 512,
                "max_facts": 5,
                "max_chunks": 0,
            },
            headers=auth_headers(),
        )

    assert linked.status_code == 201
    assert old_fact.status_code == 200
    assert old_fact.json()["data"]["status"] == "disputed"
    assert context.status_code == 200
    rendered = context.json()["data"]["rendered_text"]
    assert "CONTRADICTING_NEW_FACT" in rendered
    assert "CONTRADICTED_OLD_FACT" not in rendered


def test_context_include_stale_can_show_disputed_review_only_evidence(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        old_id = create_fact(
            client,
            "DISPUTED_REVIEW_OLD_FACT: legacy incident owner is Alex.",
        )
        new_id = create_fact(
            client,
            "DISPUTED_REVIEW_NEW_FACT: incident owner is Dana, not Alex.",
        )
        linked = client.post(
            f"/v1/facts/{new_id}/relations",
            json={
                "target_fact_id": old_id,
                "relation_type": "contradicts",
                "reason": "New incident owner evidence contradicts old owner.",
                "observed_at": "2026-01-02T12:00:00+00:00",
            },
            headers=auth_headers(),
        )
        default_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "DISPUTED_REVIEW_OLD_FACT legacy incident owner Alex",
                "token_budget": 512,
                "max_facts": 5,
                "max_chunks": 0,
            },
            headers=auth_headers(),
        )
        superseded_only_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "DISPUTED_REVIEW_OLD_FACT legacy incident owner Alex",
                "token_budget": 512,
                "max_facts": 5,
                "max_chunks": 0,
                "include_superseded": True,
            },
            headers=auth_headers(),
        )
        stale_context = client.post(
            "/v1/context",
            json={
                "space_id": "space_client_app",
                "memory_scope_ids": ["memory_scope_default"],
                "query": "DISPUTED_REVIEW_OLD_FACT legacy incident owner Alex",
                "token_budget": 512,
                "max_facts": 5,
                "max_chunks": 0,
                "include_stale": True,
            },
            headers=auth_headers(),
        )

    assert linked.status_code == 201
    assert default_context.status_code == 200
    assert superseded_only_context.status_code == 200
    assert stale_context.status_code == 200

    default_data = default_context.json()["data"]
    assert "DISPUTED_REVIEW_OLD_FACT" not in default_data["rendered_text"]
    assert default_data["diagnostics"]["stale_facts_used"] == 0

    superseded_only_data = superseded_only_context.json()["data"]
    assert "DISPUTED_REVIEW_OLD_FACT" not in superseded_only_data["rendered_text"]
    assert superseded_only_data["diagnostics"]["stale_facts_used"] == 0

    stale_data = stale_context.json()["data"]
    assert "DISPUTED_REVIEW_OLD_FACT" in stale_data["rendered_text"]
    assert "disputed_review" in stale_data["diagnostics"]["retrieval_sources_used"]
    assert stale_data["diagnostics"]["stale_facts_considered"] >= 1
    assert stale_data["diagnostics"]["stale_facts_used"] == 1
    assert stale_data["diagnostics"]["superseded_facts_used"] == 0
    review_item = next(item for item in stale_data["items"] if item["item_id"] == old_id)
    assert review_item["diagnostics"]["retrieval_source"] == "disputed_review"
    assert review_item["diagnostics"]["review_only"] is True
    assert review_item["diagnostics"]["stale_reason"] == "fact_status_disputed"
    assert review_item["diagnostics"]["provenance"]["visibility"] == "review_only"


def test_fact_relations_reject_cross_memory_scope_and_restricted_links(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_SCOPE: source fact.")
        other_memory_scope_id = create_fact(
            client,
            "RELATION_SCOPE: other memory_scope fact.",
            memory_scope_id="memory_scope_other",
        )
        restricted = client.post(
            "/v1/facts",
            json={
                **fact_payload("RELATION_SCOPE: restricted fact."),
                "classification": "restricted",
            },
            headers=auth_headers(),
        )
        assert restricted.status_code == 201

        cross_memory_scope = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": other_memory_scope_id,
                "relation_type": "related_to",
                "reason": "Cross memory_scope should be rejected.",
            },
            headers=auth_headers(),
        )
        restricted_link = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": restricted.json()["data"]["id"],
                "relation_type": "related_to",
                "reason": "Restricted facts should not leak through links.",
            },
            headers=auth_headers(),
        )

    assert cross_memory_scope.status_code == 409
    assert restricted_link.status_code == 409
