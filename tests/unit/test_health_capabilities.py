from pathlib import Path

from fastapi.testclient import TestClient
from memo_stack_adapters.extraction.transcription.openai_adapter import (
    OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES,
)
from memo_stack_core.domain.entities import SourceRef
from memo_stack_core.domain.errors import MemoryInfrastructureError, MemoryInvariantError
from memo_stack_core.ports import (
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
from memo_stack_server.config import CaptureMode, DeployProfile, MemoryPolicyMode, Settings
from memo_stack_server.main import create_app


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
        "service": "memo-stack",
        "deploy_profile": "test",
    }


def test_root_health_alias_supports_client_canary() -> None:
    response = build_test_client().get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_healthz_alias_supports_frontend_liveness() -> None:
    response = build_test_client().get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities_return_noop_adapters() -> None:
    response = build_test_client().get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["service_name"] == "memo-stack"
    assert body["deploy_profile"] == "test"
    assert body["policy_mode"] == "active_context"
    assert set(body["adapters"]) == {"qdrant", "graphiti", "embeddings", "cognee"}
    assert body["adapters"]["qdrant"]["enabled"] is False
    assert body["adapters"]["graphiti"]["enabled"] is False
    assert body["adapters"]["embeddings"]["enabled"] is False
    assert body["adapters"]["cognee"]["enabled"] is False
    capability_pairs = {(item["adapter_name"], item["capability"]) for item in body["capabilities"]}
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
    assert body["limits"]["max_capture_text_chars"] == 20_000
    assert body["limits"]["max_pending_captures_per_memory_scope"] == 5_000
    assert body["limits"]["max_pending_suggestions_per_memory_scope"] == 500
    assert body["limits"]["max_asset_upload_bytes"] == 25 * 1024 * 1024
    assert body["limits"]["media_analysis_seconds_per_month"] == 10 * 60 * 60
    assert body["plans"]["current"] == "free"
    assert body["plans"]["resources"]["media_analysis_seconds"]["limit_per_month"] == (10 * 60 * 60)
    assert body["extraction"]["enabled"] is True
    assert body["extraction"]["default_profile"] == "standard_local"
    assert body["extraction"]["profiles"] == [
        "standard_local",
        "standard_docling",
        "standard_vision",
        "media_api",
        "media_local_asr",
        "standard_asr",
        "standard_full",
    ]
    profile_states = {
        profile["name"]: profile
        for profile in body["extraction"]["profiles_v2"]
    }
    assert set(profile_states) == set(body["extraction"]["profiles"])
    assert profile_states["standard_local"]["status"] == "ok"
    assert profile_states["standard_local"]["enabled"] is True
    assert profile_states["standard_local"]["external_provider_egress"] is False
    assert profile_states["standard_vision"]["requires_explicit_external_ai"] is True
    assert profile_states["standard_vision"]["memory_promotion"] == "review_required"
    assert profile_states["standard_vision"]["source_text_policy"] == "untrusted_evidence"
    assert profile_states["standard_vision"]["artifact_payloads_bounded"] is True
    assert profile_states["standard_asr"]["deprecated"] is True
    assert body["extraction"]["providers"]["openai_vision"]["status"] in {
        "blocked",
        "unavailable",
    }
    assert body["extraction"]["providers"]["transcription_api"]["status"] in {
        "blocked",
        "unavailable",
    }
    assert body["extraction"]["policy"] == {
        "schema_version": 2,
        "external_ai_allowed": False,
        "external_ai_requires_explicit_profile": True,
        "local_asr_default": False,
        "memory_promotion": "review_required",
        "source_text_policy": "untrusted_evidence",
        "provider_payloads_bounded": True,
        "sensitive_data_in_diagnostics": False,
        "canonical_store": "postgres",
        "derived_indexes": ["qdrant", "graphiti"],
    }
    assert isinstance(body["extraction"]["optional_extras"]["docling"]["installed"], bool)
    assert isinstance(body["extraction"]["optional_extras"]["vision"]["installed"], bool)
    assert body["extraction"]["optional_extras"]["vision"]["configured"] is False
    assert body["extraction"]["optional_extras"]["vision"]["model"] == "gpt-4.1-mini"
    assert body["extraction"]["optional_extras"]["vision"]["detail"] == "high"
    assert isinstance(body["extraction"]["optional_extras"]["transcription_api"]["installed"], bool)
    assert body["extraction"]["optional_extras"]["transcription_api"]["configured"] is False
    assert body["extraction"]["optional_extras"]["transcription_api"]["provider"] == "openai"
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["model"]
        == "gpt-4o-mini-transcribe"
    )
    assert (
        body["extraction"]["optional_extras"]["transcription_api"]["max_provider_upload_bytes"]
        == OPENAI_TRANSCRIPTION_MAX_UPLOAD_BYTES
    )
    assert isinstance(
        body["extraction"]["optional_extras"]["transcription_local"]["installed"], bool
    )
    assert body["extraction"]["optional_extras"]["transcription_local"]["model"] == "base"
    assert body["extraction"]["optional_extras"]["transcription_local"]["default"] is False
    assert body["extraction"]["optional_extras"]["asr"]["deprecated"] is True
    assert body["extraction"]["optional_extras"]["asr"]["replacement_profiles"] == [
        "media_api",
        "media_local_asr",
    ]
    assert body["extraction"]["limits"]["max_media_seconds"] == 600
    assert body["captures"]["max_pending_per_memory_scope"] == 5_000
    assert body["captures"]["ingress_limit_code"] == "memory.capture.ingress_limited"
    assert body["supports_legacy_client_routes"] is False


def test_capabilities_expose_configured_external_media_extraction(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'media-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="media_api",
            extraction_external_ai_enabled=True,
            max_asset_upload_bytes=77_777,
            extraction_max_bytes=123_456,
            extraction_max_pages=7,
            extraction_max_media_seconds=42,
            extraction_max_output_chars=10_000,
            extraction_max_tables=3,
            extraction_ocr_enabled=False,
            extraction_vision_model="gpt-4.1-mini",
            extraction_vision_detail="low",
            transcription_provider="openai",
            transcription_openai_model="gpt-4o-transcribe",
            transcription_openai_max_upload_bytes=12_345,
            openai_api_key="sk-capabilities-secret",
            plan_media_analysis_seconds_per_month=3_600,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    extraction = body["extraction"]
    assert extraction["default_profile"] == "media_api"
    assert extraction["external_provider_egress"] is True
    assert extraction["optional_extras"]["vision"]["configured"] is True
    assert extraction["optional_extras"]["vision"]["model"] == "gpt-4.1-mini"
    assert extraction["optional_extras"]["vision"]["detail"] == "low"
    assert extraction["optional_extras"]["transcription_api"]["configured"] is True
    assert extraction["optional_extras"]["transcription_api"]["provider"] == "openai"
    assert extraction["optional_extras"]["transcription_api"]["model"] == "gpt-4o-transcribe"
    assert extraction["optional_extras"]["transcription_api"]["max_provider_upload_bytes"] == 12_345
    assert extraction["limits"]["max_bytes"] == 123_456
    assert extraction["limits"]["max_pages"] == 7
    assert extraction["limits"]["max_media_seconds"] == 42
    assert extraction["limits"]["max_output_chars"] == 10_000
    assert extraction["limits"]["max_tables"] == 3
    assert extraction["limits"]["ocr_enabled"] is False
    assert extraction["limits"]["max_image_pixels"] == 50_000_000
    assert extraction["limits"]["parser_timeout_seconds"] == 5 * 60
    assert extraction["limits"]["subprocess_timeout_seconds"] == 60
    assert extraction["providers"]["openai_vision"]["enabled"] is True
    assert extraction["providers"]["openai_vision"]["status"] == "ok"
    assert extraction["providers"]["transcription_api"]["enabled"] is True
    assert extraction["providers"]["transcription_api"]["status"] == "ok"
    assert extraction["policy"]["external_ai_allowed"] is True
    profile_states = {profile["name"]: profile for profile in extraction["profiles_v2"]}
    assert profile_states["media_api"]["status"] == "ok"
    assert profile_states["standard_vision"]["status"] == "ok"
    assert body["limits"]["max_asset_upload_bytes"] == 77_777
    assert body["plans"]["resources"]["media_analysis_seconds"]["limit_per_month"] == 3_600
    assert "sk-capabilities-secret" not in response.text


def test_capabilities_keep_transcription_disabled_when_provider_is_disabled(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'disabled-asr-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            extraction_default_profile="media_api",
            extraction_external_ai_enabled=True,
            transcription_provider="disabled",
            openai_api_key="sk-unused-transcription-secret",
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["external_provider_egress"] is True
    assert extraction["optional_extras"]["vision"]["configured"] is True
    assert extraction["optional_extras"]["transcription_api"]["configured"] is False
    assert extraction["optional_extras"]["transcription_api"]["provider"] == "disabled"
    assert extraction["providers"]["transcription_api"]["status"] == "blocked"
    assert extraction["providers"]["transcription_api"]["reason"] == "provider_disabled"
    profile_states = {profile["name"]: profile for profile in extraction["profiles_v2"]}
    assert profile_states["media_api"]["status"] == "blocked"
    assert profile_states["media_api"]["reason"] == "provider_disabled"
    assert "sk-unused-transcription-secret" not in response.text


def test_capabilities_show_capture_disabled_when_policy_is_manual_only(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'manual-capture-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            policy_mode=MemoryPolicyMode.MANUAL_ONLY,
            capture_mode=CaptureMode.SUGGEST,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["policy_mode"] == "manual_only"
    assert response.json()["captures"]["mode"] == "suggest"
    assert response.json()["captures"]["enabled"] is False


def test_capabilities_require_explicit_auto_apply_safe_switch(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'auto-apply-capabilities.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            policy_mode=MemoryPolicyMode.SUGGESTIONS,
            capture_mode=CaptureMode.AUTO_APPLY_SAFE,
            auto_apply_safe_enabled=False,
        )
    )
    with TestClient(app) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["captures"]["mode"] == "auto_apply_safe"
    assert response.json()["captures"]["enabled"] is True
    assert response.json()["captures"]["auto_apply_safe_enabled"] is False


def test_settings_auto_memory_mode_alias_wins_over_capture_mode(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_CAPTURE_MODE", "retrieve_only")
    monkeypatch.setenv("MEMORY_AUTO_MEMORY_MODE", "suggest")

    settings = Settings(
        _env_file=None,
        deploy_profile=DeployProfile.TEST,
        qdrant_enabled=False,
        graphiti_enabled=False,
        embeddings_enabled=False,
    )

    assert settings.capture_mode == CaptureMode.SUGGEST


def test_legacy_client_routes_are_opt_in() -> None:
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
    assert capabilities.json()["supports_legacy_client_routes"] is False
    assert legacy_context.status_code == 404


def test_legacy_client_route_flag_enables_compatibility_routes(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'legacy-routes.db'}",
            auto_create_schema=True,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
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
    assert capabilities.json()["supports_legacy_client_routes"] is True
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
    scope = MemoryScopeFilter(space_id="space-1", memory_scope_ids=("memory_scope-1",))
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
        text="Use Memo Stack Core as canonical source of truth.",
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
