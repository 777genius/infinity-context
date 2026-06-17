from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app


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
