from pathlib import Path

from fastapi.testclient import TestClient
from memory_core.domain.entities import SourceRef
from memory_core.domain.errors import MemoryInfrastructureError, MemoryInvariantError
from memory_core.ports import (
    CapabilityDescriptor,
    CapabilityMode,
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityStatus,
    ConsistencyMode,
    DocumentMemoryPort,
    EngineHealthSnapshot,
    FactProjectionPort,
    MemoryCapability,
    MemoryScopeFilter,
    ProjectionFreshness,
    RagRecallPort,
    TemporalFactGraphPort,
    VectorRecallPort,
)
from memory_server.config import DeployProfile, Settings
from memory_server.main import create_app


def build_test_client() -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    return TestClient(app)


def test_health_returns_ok() -> None:
    response = build_test_client().get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "memory-platform",
        "deploy_profile": "test",
    }


def test_root_health_alias_supports_hackinterview_canary() -> None:
    response = build_test_client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities_return_noop_adapters() -> None:
    response = build_test_client().get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["service_name"] == "memory-platform"
    assert body["deploy_profile"] == "test"
    assert body["policy_mode"] == "active_context"
    assert set(body["adapters"]) == {"qdrant", "graphiti", "embeddings", "cognee"}
    assert body["adapters"]["qdrant"]["enabled"] is False
    assert body["adapters"]["graphiti"]["enabled"] is False
    assert body["adapters"]["embeddings"]["enabled"] is False
    assert body["adapters"]["cognee"]["enabled"] is False
    capability_pairs = {
        (item["adapter_name"], item["capability"]) for item in body["capabilities"]
    }
    assert capability_pairs == {
        ("qdrant", "vector_recall"),
        ("qdrant", "projection_forget"),
        ("graphiti", "temporal_fact_graph"),
        ("graphiti", "fact_projection"),
        ("graphiti", "projection_forget"),
        ("embeddings", "engine_health"),
        ("cognee", "document_memory"),
        ("cognee", "rag_recall"),
    }
    assert all(item["status"] == "disabled" for item in body["capabilities"])
    assert all(item["healthy"] is False for item in body["capabilities"])
    assert "bearer" not in response.text.lower()
    assert "api_key" not in response.text.lower()
    assert "secret" not in response.text.lower()
    assert body["limits"]["max_context_tokens"] == 1800
    assert body["supports_legacy_hackinterview_routes"] is False


def test_legacy_hackinterview_routes_are_opt_in() -> None:
    client = build_test_client()
    capabilities = client.get("/v1/capabilities")
    legacy_context = client.post(
        "/api/v1/interview-memory/context",
        json={
            "session_id": "disabled-legacy",
            "current_request": {"id": "req-1", "label": "request", "text": "hello"},
        },
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["supports_legacy_hackinterview_routes"] is False
    assert legacy_context.status_code == 404


def test_legacy_hackinterview_route_flag_enables_compatibility_routes(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'legacy-routes.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_hackinterview_enabled=True,
        )
    )
    with TestClient(app) as client:
        capabilities = client.get("/v1/capabilities")
        legacy_context = client.post(
            "/api/v1/interview-memory/context",
            json={
                "session_id": "enabled-legacy",
                "current_request": {"id": "req-1", "label": "request", "text": "hello"},
            },
        )

    assert capabilities.status_code == 200
    assert capabilities.json()["supports_legacy_hackinterview_routes"] is True
    assert legacy_context.status_code != 404


def test_capability_descriptor_contract_defaults_are_safe() -> None:
    descriptor = CapabilityDescriptor(
        capability=MemoryCapability.TEMPORAL_FACT_GRAPH,
        adapter_name="graphiti",
        mode=CapabilityMode.PRIMARY,
        status=CapabilityStatus.OK,
        enabled=True,
        supports_scope_filter=True,
        supports_source_refs=True,
        supports_update=True,
        supports_delete=True,
    )

    assert descriptor.projection_freshness == ProjectionFreshness.NOT_APPLICABLE
    assert descriptor.external_ai_allowed is False
    assert descriptor.metadata == {}


def test_capability_recall_contract_validates_scope_and_score() -> None:
    scope = MemoryScopeFilter(space_id="space-1", profile_ids=("profile-1",))
    query = CapabilityRecallQuery(
        scope=scope,
        query="architecture decision",
        limit=5,
        consistency_mode=ConsistencyMode.REQUIRE_FRESH_PROJECTION,
        min_score=0.75,
    )
    candidate = CapabilityRecallCandidate(
        item_id="fact-1",
        item_type="fact",
        text="Use Memory Core as canonical source of truth.",
        score=0.91,
        source_refs=(SourceRef(source_type="manual", source_id="note-1"),),
        capability=MemoryCapability.FACT_PROJECTION,
        adapter_name="postgres",
    )

    assert query.consistency_mode == ConsistencyMode.REQUIRE_FRESH_PROJECTION
    assert candidate.source_refs[0].source_id == "note-1"


def test_capability_ports_are_role_specific_protocols() -> None:
    assert "ingest_document" in DocumentMemoryPort.__dict__
    assert "recall" in RagRecallPort.__dict__
    assert "upsert_fact" in TemporalFactGraphPort.__dict__
    assert "upsert_fact_projection" in FactProjectionPort.__dict__
    assert "recall_vectors" in VectorRecallPort.__dict__


def test_engine_health_snapshot_uses_capability_descriptors() -> None:
    descriptor = CapabilityDescriptor(
        capability=MemoryCapability.RAG_RECALL,
        adapter_name="cognee",
        mode=CapabilityMode.SECONDARY,
        status=CapabilityStatus.DISABLED,
        enabled=False,
        supports_scope_filter=True,
        supports_source_refs=True,
    )
    snapshot = EngineHealthSnapshot(
        adapter_name="cognee",
        status=CapabilityStatus.DISABLED,
        capabilities=(descriptor,),
    )

    assert snapshot.capabilities[0].capability == MemoryCapability.RAG_RECALL


def test_unexpected_exception_maps_to_safe_internal_error() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-raw-secret")
    async def raise_raw_secret() -> None:
        raise RuntimeError("RAW_INTERNAL_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-raw-secret")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "memory.internal",
            "message": "Internal error",
            "retryable": True,
        }
    }
    assert "RAW_INTERNAL_SECRET_MARKER" not in response.text


def test_invariant_error_maps_to_safe_internal_error() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-invariant-secret")
    async def raise_invariant_secret() -> None:
        raise MemoryInvariantError("RAW_INVARIANT_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-invariant-secret")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "memory.internal",
            "message": "Internal error",
            "retryable": True,
        }
    }
    assert "RAW_INVARIANT_SECRET_MARKER" not in response.text


def test_infrastructure_error_maps_to_safe_provider_unavailable() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    @app.get("/raise-provider-secret")
    async def raise_provider_secret() -> None:
        raise MemoryInfrastructureError("RAW_PROVIDER_SECRET_MARKER must not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/raise-provider-secret")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "memory.provider_unavailable",
            "message": "Provider unavailable",
            "retryable": True,
        }
    }
    assert "RAW_PROVIDER_SECRET_MARKER" not in response.text
