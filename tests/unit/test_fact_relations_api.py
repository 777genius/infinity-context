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


def fact_payload(text: str, *, profile_id: str = "profile_default") -> dict[str, Any]:
    return {
        "space_id": "space_client_app",
        "profile_id": profile_id,
        "text": text,
        "kind": "architecture_decision",
        "source_refs": [{"source_type": "manual", "source_id": text[:40]}],
    }


def create_fact(client: TestClient, text: str, *, profile_id: str = "profile_default") -> str:
    response = client.post(
        "/v1/facts",
        json=fact_payload(text, profile_id=profile_id),
        headers=auth_headers(),
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


def test_fact_relations_link_list_unlink_and_relink(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_SOURCE: Postgres is canonical truth.")
        target_id = create_fact(client, "RELATION_TARGET: Graphiti is derived temporal graph.")

        linked = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": target_id,
                "relation_type": "supports",
                "reason": "ADR says Graphiti remains a derived adapter.",
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
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["direction"] == "outgoing"
    assert listed.json()["data"]["items"][0]["relation"]["relation_type"] == "supports"
    assert listed.json()["data"]["items"][0]["related_fact"]["id"] == target_id
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert deleted_list.status_code == 200
    assert deleted_list.json()["data"]["items"][0]["relation"]["status"] == "deleted"
    assert relinked.status_code == 201
    assert relinked.json()["data"]["id"] != linked.json()["data"]["id"]


def test_fact_relations_reject_cross_profile_and_restricted_links(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source_id = create_fact(client, "RELATION_SCOPE: source fact.")
        other_profile_id = create_fact(
            client,
            "RELATION_SCOPE: other profile fact.",
            profile_id="profile_other",
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

        cross_profile = client.post(
            f"/v1/facts/{source_id}/relations",
            json={
                "target_fact_id": other_profile_id,
                "relation_type": "related_to",
                "reason": "Cross profile should be rejected.",
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

    assert cross_profile.status_code == 409
    assert restricted_link.status_code == 409
