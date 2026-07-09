from pathlib import Path

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


def test_export_graph_includes_facts_documents_fragments_and_evidence_edges(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
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
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
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
        episode = client.post(
            "/v1/episodes",
            json={
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
                "source_type": "system_audio",
                "source_external_id": "meeting-graph-export",
                "text": "Episode graph export marker should become a first-class graph node.",
                "speaker": "user",
                "trust_level": "high",
            },
            headers=auth_headers(),
        )
        assert episode.status_code == 200, episode.text
        episode_id = episode.json()["data"]["episode_id"]
        episode_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
                "text": "Episode evidence must be exportable as canonical graph context.",
                "kind": "note",
                "source_refs": [
                    {"source_type": "system_audio", "source_id": "meeting-graph-export"}
                ],
                "classification": "internal",
            },
            headers=auth_headers(),
        )
        related_fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
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
                "space_slug": "graph-export",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "thread-graph-export",
            },
            headers=auth_headers(),
        )

    assert document.status_code == 201
    assert chunks.status_code == 200
    assert fact.status_code == 201
    assert episode_fact.status_code == 201
    assert related_fact.status_code == 201
    assert relation.status_code == 201
    assert graph.status_code == 200
    data = graph.json()["data"]
    node_ids = {node["id"] for node in data["nodes"]}
    episode_chunk_nodes = [
        node
        for node in data["nodes"]
        if node["type"] == "chunk" and node["data"].get("episode_id") == episode_id
    ]
    edge_types = {edge["type"] for edge in data["edges"]}
    assert data["schema_version"] == "infinity_context.graph_export.v1"
    assert data["counts"]["facts"] == 3
    assert data["counts"]["documents"] == 1
    assert data["counts"]["episodes"] == 1
    assert data["counts"]["chunks"] == 3
    assert data["counts"]["relations"] == 1
    assert f"fact:{fact.json()['data']['id']}" in node_ids
    assert f"fact:{episode_fact.json()['data']['id']}" in node_ids
    assert f"document:{document_id}" in node_ids
    assert f"episode:{episode_id}" in node_ids
    assert f"chunk:{chunk_id}" in node_ids
    assert len(episode_chunk_nodes) == 1
    assert {
        "contains_fact",
        "contains_document",
        "contains_episode",
        "has_chunk",
        "evidenced_by_chunk",
        "evidenced_by_episode",
        "supports",
    }.issubset(edge_types)


def test_export_graph_excludes_restricted_memory_by_default(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        restricted = client.post(
            "/v1/facts",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "text": "Restricted graph export marker must be hidden by default.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "restricted"}],
                "classification": "restricted",
            },
            headers=auth_headers(),
        )
        default_graph = client.get(
            "/v1/export/graph.json",
            params={"space_id": "space_client_app", "memory_scope_id": "memory_scope_default"},
            headers=auth_headers(),
        )
        unrestricted_graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "include_restricted": True,
            },
            headers=auth_headers(),
        )

    assert restricted.status_code == 201
    assert default_graph.json()["data"]["counts"]["facts"] == 0
    assert unrestricted_graph.json()["data"]["counts"]["facts"] == 1


def test_export_graph_returns_empty_payload_when_scope_is_not_found(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_slug": "missing-graph-export",
                "memory_scope_external_ref": "missing",
            },
            headers=auth_headers(),
        )

    assert graph.status_code == 200
    assert graph.json()["data"] == {
        "schema_version": "infinity_context.graph_export.v1",
        "scope": {"scope_not_found": True},
        "nodes": [],
        "edges": [],
        "counts": {
            "facts": 0,
            "documents": 0,
            "episodes": 0,
            "chunks": 0,
            "anchors": 0,
            "nodes": 0,
            "edges": 0,
            "relations": 0,
            "anchor_relations": 0,
        },
        "truncated": False,
        "warnings": ["scope_not_found"],
    }


def test_export_graph_includes_anchor_relation_projection(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        person = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "person",
                "label": "Alex",
                "metadata": {"canonical_key": "alex", "person_canonical_key": "alex"},
            },
            headers=auth_headers(),
        )
        project = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "project",
                "label": "Project Atlas",
                "aliases": ["Atlas"],
                "metadata": {"canonical_key": "atlas", "project_canonical_key": "atlas"},
            },
            headers=auth_headers(),
        )
        event = client.post(
            "/v1/anchors",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "event",
                "label": "Launch review",
                "metadata": {
                    "event_participant_canonical_key": "alex",
                    "event_project_canonical_key": "atlas",
                    "event_temporal_phrase": "last week",
                },
            },
            headers=auth_headers(),
        )
        graph = client.get(
            "/v1/export/graph.json",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
            },
            headers=auth_headers(),
        )

    assert person.status_code == 200, person.text
    assert project.status_code == 200, project.text
    assert event.status_code == 200, event.text
    assert graph.status_code == 200, graph.text
    data = graph.json()["data"]
    node_ids = {node["id"] for node in data["nodes"]}
    edge_types = {edge["type"] for edge in data["edges"]}
    assert data["counts"]["anchors"] == 3
    assert data["counts"]["anchor_relations"] == 2
    assert f"anchor:{person.json()['data']['id']}" in node_ids
    assert f"anchor:{project.json()['data']['id']}" in node_ids
    assert f"anchor:{event.json()['data']['id']}" in node_ids
    assert {"contains_anchor", "event_participant", "event_project"}.issubset(edge_types)
    relation_edges = [
        edge
        for edge in data["edges"]
        if edge["type"] in {"event_participant", "event_project"}
    ]
    assert {edge["source"] for edge in relation_edges} == {
        f"anchor:{event.json()['data']['id']}"
    }
    assert {
        edge["target"] for edge in relation_edges
    } == {
        f"anchor:{person.json()['data']['id']}",
        f"anchor:{project.json()['data']['id']}",
    }
