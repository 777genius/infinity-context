from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id
from infinity_context_core.domain.errors import MemoryConflictError, MemoryError
from infinity_context_core.ports.graph_evidence import (
    GraphProjectionDeleteEvidence,
    GraphProjectionDeletePass,
    GraphProjectionIdentitySnapshot,
)
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionPointIdentity,
    VectorProjectionPresenceEvidence,
)
from infinity_context_server import composition
from infinity_context_server.api.auth import _required_permission
from infinity_context_server.api.errors import memory_error_handler
from infinity_context_server.api.v1 import diagnostics as diagnostics_api
from infinity_context_server.auth_tokens import (
    MEMORY_PERMISSION_ADMIN,
    MEMORY_PERMISSION_DIAGNOSTICS,
)
from infinity_context_server.config import Settings
from infinity_context_server.derived_identity_evidence import (
    CanonicalProjectionScope,
    DerivedIdentityEvidenceCoordinator,
    ProjectionOutboxCompletion,
    _prove_delete_event_completion,
    graphiti_target_commitment_sha256,
)


class _Readiness:
    def __init__(self) -> None:
        self.calls: list[tuple[CanonicalProjectionScope, tuple[str, ...], tuple[str, ...]]] = []

    async def prove_presence_ready(self, *, scope, chunk_ids, fact_ids):
        self.calls.append((scope, chunk_ids, fact_ids))
        return ProjectionOutboxCompletion(chunk_ids, fact_ids, len(chunk_ids) + len(fact_ids))

    async def prove_delete_ready(self, *, scope, chunk_ids, fact_ids):
        self.calls.append((scope, chunk_ids, fact_ids))
        return ProjectionOutboxCompletion(chunk_ids, fact_ids, len(chunk_ids) + len(fact_ids))


class _VectorEvidence:
    target = "a" * 64

    def __init__(self) -> None:
        self.delete_passes: list[int] = []
        self.absent = False

    async def observe_exact(self, *, scope, chunk_ids):
        expected = tuple(
            VectorProjectionPointIdentity(chunk_id, f"point-{chunk_id}") for chunk_id in chunk_ids
        )
        return VectorProjectionPresenceEvidence(
            scope=scope,
            target_commitment_sha256=self.target,
            expected=expected,
            observed=() if self.absent else expected,
            scoped_point_ids=(() if self.absent else tuple(item.point_id for item in expected)),
            exact_scoped_count=0 if self.absent else len(expected),
            issues=("qdrant.evidence_expected_points_missing",) if self.absent else (),
        )

    async def delete_and_observe_exact(self, *, scope, chunk_ids, pass_index):
        self.delete_passes.append(pass_index)
        expected = tuple(
            VectorProjectionPointIdentity(chunk_id, f"point-{chunk_id}") for chunk_id in chunk_ids
        )
        present_before = () if self.absent else expected
        self.absent = True
        return VectorProjectionDeleteEvidence(
            scope=scope,
            target_commitment_sha256=self.target,
            pass_index=pass_index,
            expected=expected,
            present_before=present_before,
            remaining=(),
            scoped_point_ids_after=(),
            exact_scoped_count_after=0,
            delete_completed=True,
        )


class _GraphEvidence:
    def __init__(self, snapshot: GraphProjectionIdentitySnapshot) -> None:
        self.snapshot = snapshot
        self.groups: list[str] = []
        self.absent = False

    async def inventory_group(self, group_id: str, *, expected_fact_ids):
        self.groups.append(group_id)
        return GraphProjectionIdentitySnapshot() if self.absent else self.snapshot

    async def readback_identities(self, expected):
        return GraphProjectionIdentitySnapshot() if self.absent else self.snapshot

    async def delete_group_two_pass(self, *, group_id, expected, expected_fact_ids):
        self.groups.append(group_id)
        empty = GraphProjectionIdentitySnapshot()
        first = GraphProjectionDeletePass(1, expected, expected, empty, empty)
        second = GraphProjectionDeletePass(2, empty, empty, empty, empty)
        self.absent = True
        return GraphProjectionDeleteEvidence(group_id, expected, first, second)


def _coordinator():
    scope = CanonicalProjectionScope("space-1", "scope-1", "thread-1")
    group_id = graphiti_group_id(scope.space_id, scope.memory_scope_id)
    snapshot = GraphProjectionIdentitySnapshot(
        group_ids=(group_id,),
        episode_ids=("episode-1",),
        entity_ids=("entity-1",),
        mentions_edge_ids=("edge-1",),
    )
    readiness = _Readiness()
    vector = _VectorEvidence()
    graph = _GraphEvidence(snapshot)
    target = graphiti_target_commitment_sha256(neo4j_uri="bolt://configured:7687")
    coordinator = DerivedIdentityEvidenceCoordinator(
        readiness=readiness,
        vector_evidence=vector,
        graph_evidence=graph,
        graph_target_commitment_sha256=target,
    )
    return coordinator, scope, readiness, vector, graph, target


def test_coordinator_binds_exact_lanes_to_outbox_scope_and_target() -> None:
    coordinator, scope, readiness, vector, graph, target = _coordinator()

    evidence = asyncio.run(
        coordinator.observe_presence(
            scope=scope,
            chunk_ids=("chunk-1",),
            fact_ids=("fact-1",),
        )
    )

    assert evidence.outbox.complete is True
    assert evidence.outbox.done_chunk_ids == ("chunk-1",)
    assert evidence.outbox.done_fact_ids == ("fact-1",)
    assert evidence.qdrant is not None
    assert evidence.qdrant.evidence.complete is True
    assert evidence.qdrant.evidence.scope.projection_version == "v1"
    assert evidence.graphiti is not None
    assert evidence.graphiti.target_commitment_sha256 == target
    assert evidence.graphiti.snapshot == graph.snapshot
    assert len(evidence.qdrant.manifest_binding_sha256) == 64
    assert len(evidence.graphiti.manifest_binding_sha256) == 64
    assert readiness.calls == [(scope, ("chunk-1",), ("fact-1",))]
    assert graph.groups == [graphiti_group_id("space-1", "scope-1")]


def test_graphiti_target_commitment_strips_uri_secrets_and_binds_host() -> None:
    secret_uri = "BOLT://user:password@NEO4J.EXAMPLE:7687/graph?token=secret#credential"
    clean_uri = "bolt://neo4j.example:7687/graph"

    assert graphiti_target_commitment_sha256(
        neo4j_uri=secret_uri,
        database="memory",
    ) == graphiti_target_commitment_sha256(
        neo4j_uri=clean_uri,
        database="memory",
    )
    assert graphiti_target_commitment_sha256(
        neo4j_uri=clean_uri,
        database="memory",
    ) != graphiti_target_commitment_sha256(
        neo4j_uri="bolt://other.example:7687/graph",
        database="memory",
    )


def test_coordinator_requires_receipt_before_two_pass_deletion() -> None:
    coordinator, scope, _readiness, vector, graph, _target = _coordinator()
    presence = asyncio.run(
        coordinator.observe_presence(
            scope=scope,
            chunk_ids=("chunk-1",),
            fact_ids=("fact-1",),
        )
    )
    assert presence.qdrant is not None
    assert presence.graphiti is not None

    qdrant = asyncio.run(
        coordinator.delete_qdrant_two_pass(
            scope=scope,
            chunk_ids=("chunk-1",),
            target_commitment_sha256=presence.qdrant.evidence.target_commitment_sha256,
            manifest_binding_sha256=presence.qdrant.manifest_binding_sha256,
        )
    )
    graphiti = asyncio.run(
        coordinator.delete_graphiti_two_pass(
            scope=scope,
            fact_ids=("fact-1",),
            episode_ids=graph.snapshot.episode_ids,
            entity_ids=graph.snapshot.entity_ids,
            mentions_edge_ids=graph.snapshot.mentions_edge_ids,
            relates_to_edge_ids=graph.snapshot.relates_to_edge_ids,
            target_commitment_sha256=presence.graphiti.target_commitment_sha256,
            manifest_binding_sha256=presence.graphiti.manifest_binding_sha256,
        )
    )

    assert qdrant.first_pass.pass_index == 1
    assert qdrant.second_pass.pass_index == 2
    assert vector.delete_passes == [1, 2]
    assert graphiti.evidence.first_pass.pass_index == 1
    assert graphiti.evidence.second_pass.pass_index == 2
    qdrant_response = diagnostics_api._qdrant_delete_response(
        qdrant,
        target_commitment_sha256=presence.qdrant.evidence.target_commitment_sha256,
        manifest_binding_sha256=presence.qdrant.manifest_binding_sha256,
    )
    graphiti_response = diagnostics_api._graphiti_delete_response(
        graphiti,
        target_commitment_sha256=presence.graphiti.target_commitment_sha256,
        manifest_binding_sha256=presence.graphiti.manifest_binding_sha256,
    )
    assert qdrant_response["target_commitment_sha256"] == _VectorEvidence.target
    assert qdrant_response["manifest_binding_sha256"] == presence.qdrant.manifest_binding_sha256
    assert (
        graphiti_response["target_commitment_sha256"] == presence.graphiti.target_commitment_sha256
    )
    assert graphiti_response["manifest_binding_sha256"] == presence.graphiti.manifest_binding_sha256

    replay_qdrant = asyncio.run(
        coordinator.delete_qdrant_two_pass(
            scope=scope,
            chunk_ids=("chunk-1",),
            target_commitment_sha256=presence.qdrant.evidence.target_commitment_sha256,
            manifest_binding_sha256=presence.qdrant.manifest_binding_sha256,
        )
    )
    replay_graphiti = asyncio.run(
        coordinator.delete_graphiti_two_pass(
            scope=scope,
            fact_ids=("fact-1",),
            episode_ids=graph.snapshot.episode_ids,
            entity_ids=graph.snapshot.entity_ids,
            mentions_edge_ids=graph.snapshot.mentions_edge_ids,
            relates_to_edge_ids=graph.snapshot.relates_to_edge_ids,
            target_commitment_sha256=presence.graphiti.target_commitment_sha256,
            manifest_binding_sha256=presence.graphiti.manifest_binding_sha256,
        )
    )
    assert replay_qdrant.first_pass.present_before == ()
    assert replay_qdrant.second_pass.present_before == ()
    assert replay_graphiti.bound_expected == graph.snapshot
    assert replay_graphiti.evidence.expected.empty is True
    replay_response = diagnostics_api._graphiti_delete_response(
        replay_graphiti,
        target_commitment_sha256=presence.graphiti.target_commitment_sha256,
        manifest_binding_sha256=presence.graphiti.manifest_binding_sha256,
    )
    assert replay_response["verified_absent"] is True
    assert replay_response["bound_expected"]["episode_ids"] == ["episode-1"]
    assert replay_response["delete_expected"]["episode_ids"] == []


@pytest.mark.parametrize(
    ("path", "expected_permission"),
    [
        (
            "/v1/diagnostics/derived-evidence/presence",
            MEMORY_PERMISSION_DIAGNOSTICS,
        ),
        (
            "/v1/diagnostics/derived-evidence/qdrant/delete",
            MEMORY_PERMISSION_ADMIN,
        ),
        (
            "/v1/diagnostics/derived-evidence/graphiti/delete",
            MEMORY_PERMISSION_ADMIN,
        ),
    ],
)
def test_derived_evidence_permission_boundary(path: str, expected_permission: str) -> None:
    request = SimpleNamespace(url=SimpleNamespace(path=path), method="POST")
    assert _required_permission(request) == expected_permission


def test_coordinator_rejects_unbound_delete_without_mutation() -> None:
    coordinator, scope, _readiness, vector, _graph, _target = _coordinator()

    with pytest.raises(MemoryConflictError, match="receipt"):
        asyncio.run(
            coordinator.delete_qdrant_two_pass(
                scope=scope,
                chunk_ids=("chunk-1",),
                target_commitment_sha256="a" * 64,
                manifest_binding_sha256="0" * 64,
            )
        )

    assert vector.delete_passes == []


def test_delete_readiness_accepts_deleted_rows_only_after_done_delete_event() -> None:
    row = SimpleNamespace(id="chunk-1", status="deleted")
    upsert = SimpleNamespace(
        aggregate_id="chunk-1",
        aggregate_type="chunk",
        status="done",
        payload_json={"chunk_id": "chunk-1"},
    )
    delete = SimpleNamespace(
        aggregate_id="document-1",
        aggregate_type="document",
        status="done",
        payload_json={"chunk_ids": ["chunk-1"]},
    )

    assert _prove_delete_event_completion(("chunk-1",), [row], [upsert], [delete]) == ("chunk-1",)
    delete.status = "dead"
    with pytest.raises(MemoryConflictError, match="not terminal"):
        _prove_delete_event_completion(("chunk-1",), [row], [upsert], [delete])


@dataclass
class _RouteCoordinator:
    evidence: object
    request: object | None = None

    async def observe_presence(self, **kwargs: object):
        self.request = kwargs
        return self.evidence


def test_presence_route_is_service_token_protected_and_identity_only() -> None:
    coordinator, scope, _readiness, _vector, _graph, _target = _coordinator()
    evidence = asyncio.run(
        coordinator.observe_presence(
            scope=scope,
            chunk_ids=("chunk-1",),
            fact_ids=("fact-1",),
        )
    )
    route_coordinator = _RouteCoordinator(evidence)
    container = SimpleNamespace(
        settings=SimpleNamespace(service_token="service-secret"),
        derived_identity_evidence=route_coordinator,
    )
    app = FastAPI()
    app.state.container = container
    app.add_exception_handler(MemoryError, memory_error_handler)
    app.include_router(diagnostics_api.router, prefix="/v1")
    client = TestClient(app)
    body = {
        "space_id": "space-1",
        "memory_scope_id": "scope-1",
        "thread_id": "thread-1",
        "expected_chunk_ids": ["chunk-1"],
        "expected_fact_ids": ["fact-1"],
    }

    unauthenticated = client.post("/v1/diagnostics/derived-evidence/presence", json=body)
    response = client.post(
        "/v1/diagnostics/derived-evidence/presence",
        json=body,
        headers={"Authorization": "Bearer service-secret"},
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["outbox"] == {
        "complete": True,
        "done_chunk_ids": ["chunk-1"],
        "done_fact_ids": ["fact-1"],
        "done_event_count": 2,
    }
    assert payload["lanes"]["qdrant"]["complete"] is True
    assert payload["lanes"]["graphiti"]["complete"] is True
    assert "group_id" not in response.text
    assert "service-secret" not in response.text
    assert route_coordinator.request == {
        "scope": scope,
        "chunk_ids": ("chunk-1",),
        "fact_ids": ("fact-1",),
    }


def test_composition_wires_optional_exact_evidence_ports_without_provider_calls() -> None:
    disabled = composition.build_container(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    assert disabled.vector_projection_evidence is None
    assert disabled.graph_projection_evidence is None
    asyncio.run(disabled.aclose())

    enabled = composition.build_container(
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            qdrant_enabled=True,
            embeddings_enabled=True,
            embeddings_provider="openai",
            openai_api_key="test-only-openai-key",
            graphiti_enabled=True,
            graphiti_neo4j_password="test-only-password",
        )
    )
    assert enabled.vector_projection_evidence is not None
    assert enabled.graph_projection_evidence is not None
    assert enabled.derived_identity_evidence is not None
    asyncio.run(enabled.aclose())
