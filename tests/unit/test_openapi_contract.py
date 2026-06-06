from fastapi.testclient import TestClient
from memo_stack_server.config import DeployProfile, Settings
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


def test_openapi_contains_stable_v1_fields() -> None:
    body = build_test_client().get("/openapi.json").json()

    assert body["info"] == {"title": "Memo Stack", "version": "0.1.0"}
    paths = body["paths"]
    assert "/v1/facts" in paths
    assert "/v1/facts/{fact_id}" in paths
    assert "/v1/documents" in paths
    assert "/v1/context" in paths
    assert "/v1/search" in paths

    schemas = body["components"]["schemas"]
    assert set(schemas["RememberFactRequest"]["required"]) == {"text", "source_refs"}
    assert set(schemas["UpdateFactRequest"]["required"]) == {
        "expected_version",
        "text",
        "reason",
        "source_refs",
    }
    assert set(schemas["IngestDocumentRequest"]["required"]) == {
        "title",
        "text",
        "source_external_id",
    }
    assert set(schemas["ContextRequest"]["required"]) == {"query"}
    assert "profile_external_refs" in schemas["ContextRequest"]["properties"]
    assert "consistency_mode" in schemas["ContextRequest"]["properties"]
    assert "classification" in schemas["RememberFactRequest"]["properties"]
    assert "classification" in schemas["IngestDocumentRequest"]["properties"]
    for schema_name in (
        "ContextRequest",
        "IngestDocumentRequest",
        "IngestEpisodeRequest",
        "RememberFactRequest",
        "UpdateFactRequest",
        "CreateSpaceRequest",
        "CreateProfileRequest",
        "ThreadMemoryScopeRequest",
        "CreateCaptureRequest",
        "CreateSuggestionRequest",
    ):
        assert schemas[schema_name]["additionalProperties"] is False


def test_v1_request_models_reject_unknown_fields() -> None:
    client = build_test_client()
    cases = (
        (
            "/v1/context",
            {"query": "hello", "unexpected": "raw"},
        ),
        (
            "/v1/documents",
            {
                "title": "Doc",
                "text": "Body",
                "source_external_id": "doc-1",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/episodes",
            {
                "space_id": "space",
                "profile_id": "profile",
                "thread_id": "thread",
                "source_external_id": "episode-1",
                "text": "hello",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/facts",
            {
                "space_id": "space",
                "profile_id": "profile",
                "text": "Fact",
                "source_refs": [{"source_type": "manual", "source_id": "ref-1"}],
                "unexpected": "raw",
            },
        ),
        (
            "/v1/spaces",
            {"slug": "strict-space", "name": "Strict Space", "unexpected": "raw"},
        ),
        (
            "/v1/thread-memory/status",
            {
                "space_id": "space",
                "profile_id": "profile",
                "thread_id": "thread",
                "unexpected": "raw",
            },
        ),
    )

    for path, payload in cases:
        response = client.post(path, json=payload)

        assert response.status_code == 400, path
        assert response.json()["error"]["code"] == "memory.validation", path


def test_openapi_contains_legacy_routes_when_compatibility_adapter_enabled() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    body = TestClient(app).get("/openapi.json").json()

    paths = body["paths"]
    assert "/api/v1/interview-memory/context" in paths
    schemas = body["components"]["schemas"]
    assert set(schemas["LegacyContextRequest"]["required"]) == {
        "session_id",
        "current_request",
    }
