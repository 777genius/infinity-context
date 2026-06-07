from pathlib import Path

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


def test_export_graph_includes_facts_documents_fragments_and_evidence_edges(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "title": "ADR graph export",
                "text": "\n".join(
                    [
                        "## Decision",
                        "- Canonical memory graph exports from Postgres.",
                        "## Risks",
                        "- Graphiti is a projection and must not be the export source.",
                    ]
                ),
                "source_type": "document",
                "source_external_id": "adr-graph-export",
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        document_id = document.json()["data"]["id"]
        chunks = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        )
        chunk_id = chunks.json()["data"][0]["id"]
        fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Canonical graph export must use Postgres as source of truth.",
                "kind": "architecture_decision",
                "source_refs": [
                    {
                        "source_type": "document",
                        "source_id": "adr-graph-export",
                        "chunk_id": chunk_id,
                        "quote_preview": "Canonical memory graph exports from Postgres.",
                    }
                ],
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        related_fact = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Graphiti remains a derived temporal graph adapter.",
                "kind": "architecture_decision",
                "source_refs": [{"source_type": "manual", "source_id": "graphiti-derived"}],
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        relation = client.post(
            f"/v1/facts/{fact.json()['data']['id']}/relations",
            json={
                "target_fact_id": related_fact.json()["data"]["id"],
                "relation_type": "supports",
                "reason": "ADR links canonical export and derived graph policy.",
            },
            headers=auth_headers(),
        )
        graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
            },
            headers=auth_headers(),
        )

    assert document.status_code == 201
    assert chunks.status_code == 200
    assert fact.status_code == 201
    assert related_fact.status_code == 201
    assert relation.status_code == 201
    assert graph.status_code == 200
    data = graph.json()["data"]
    node_ids = {node["id"] for node in data["nodes"]}
    edge_types = {edge["type"] for edge in data["edges"]}
    assert data["schema_version"] == "memo_stack.graph_export.v1"
    assert data["counts"]["facts"] == 2
    assert data["counts"]["documents"] == 1
    assert data["counts"]["chunks"] == 2
    assert data["counts"]["relations"] == 1
    assert f"fact:{fact.json()['data']['id']}" in node_ids
    assert f"document:{document_id}" in node_ids
    assert f"chunk:{chunk_id}" in node_ids
    assert {
        "contains_fact",
        "contains_document",
        "has_chunk",
        "evidenced_by_chunk",
        "supports",
    }.issubset(edge_types)


def test_export_graph_excludes_restricted_memory_by_default(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        restricted = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "text": "Restricted graph export marker must be hidden by default.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "restricted"}],
                "classification": "restricted",
            },
            headers=auth_headers(),
        )
        default_graph = client.get(
            "/v1/export/graph.json",
            params={"space_id": "space_client_app", "profile_id": "profile_default"},
            headers=auth_headers(),
        )
        unrestricted_graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_id": "space_client_app",
                "profile_id": "profile_default",
                "include_restricted": True,
            },
            headers=auth_headers(),
        )

    assert restricted.status_code == 201
    assert default_graph.json()["data"]["counts"]["facts"] == 0
    assert unrestricted_graph.json()["data"]["counts"]["facts"] == 1
