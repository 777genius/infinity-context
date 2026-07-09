import asyncio
import json

from fastapi.exceptions import RequestValidationError
from infinity_context_server.api.errors import request_validation_error_handler
from infinity_context_server.api.v1 import (
    context as context_api,
)
from infinity_context_server.api.v1 import (
    digest as digest_api,
)
from infinity_context_server.api.v1 import (
    documents as documents_api,
)
from infinity_context_server.api.v1 import (
    episodes as episodes_api,
)
from infinity_context_server.api.v1 import (
    facts as facts_api,
)
from infinity_context_server.api.v1 import (
    spaces_memory_scopes as spaces_memory_scopes_api,
)
from infinity_context_server.api.v1 import (
    thread_memory as thread_memory_api,
)
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.features.memory_scopes import public as memory_scopes_feature
from infinity_context_server.main import create_app
from pydantic import ValidationError


def build_test_app() -> object:
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )


def test_openapi_contains_stable_v1_fields() -> None:
    body = build_test_app().openapi()

    assert body["info"] == {"title": "Infinity Context", "version": "0.1.0"}
    paths = body["paths"]
    assert "/v1/facts" in paths
    assert "/v1/facts/{fact_id}" in paths
    assert "/v1/facts/{fact_id}/related" in paths
    assert "/v1/facts/{fact_id}/relations" in paths
    assert "/v1/facts/relations/{relation_id}" in paths
    assert "/v1/documents" in paths
    assert "/v1/context" in paths
    assert "/v1/search" in paths
    assert "/v1/digest" in paths
    assert "/v1/operations-console" in paths
    assert "/v1/memory-browser" in paths
    assert "/v1/export/graph.json" in paths
    assert "/v1/export/memory_scope-snapshot/preview" in paths
    assert "/v1/context-link-suggestions/review-batch" in paths
    context_link_query_params = {
        item["name"] for item in paths["/v1/context-links"]["get"]["parameters"]
    }
    context_link_suggestion_query_params = {
        item["name"] for item in paths["/v1/context-link-suggestions"]["get"]["parameters"]
    }
    assert {"status", "statuses", "limit"}.issubset(context_link_query_params)
    assert {"status", "statuses", "limit"}.issubset(
        context_link_suggestion_query_params
    )

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
    assert set(schemas["DigestRequest"]["required"]) == {"topic"}
    assert "memory_scope_external_refs" in schemas["ContextRequest"]["properties"]
    assert "memory_scope_external_refs" in schemas["DigestRequest"]["properties"]
    assert "consistency_mode" in schemas["ContextRequest"]["properties"]
    assert "classification" in schemas["RememberFactRequest"]["properties"]
    assert "classification" in schemas["IngestDocumentRequest"]["properties"]
    assert "source_refs" in schemas["IngestDocumentRequest"]["properties"]
    for schema_name in (
        "ContextRequest",
        "DigestRequest",
        "IngestDocumentRequest",
        "IngestEpisodeRequest",
        "RememberFactRequest",
        "UpdateFactRequest",
        "LinkFactRequest",
        "CreateSpaceRequest",
        "CreateMemoryScopeRequest",
        "ThreadMemoryScopeRequest",
        "CreateCaptureRequest",
        "CreateSuggestionRequest",
        "ImportMemoryScopeSnapshotRequest",
        "PreviewMemoryScopeSnapshotRequest",
    ):
        assert schemas[schema_name]["additionalProperties"] is False


def test_v1_request_models_reject_unknown_fields() -> None:
    cases = (
        (
            "/v1/context",
            context_api.ContextRequest,
            {"query": "hello", "unexpected": "raw"},
        ),
        (
            "/v1/digest",
            digest_api.DigestRequest,
            {"topic": "hello", "unexpected": "raw"},
        ),
        (
            "/v1/documents",
            documents_api.IngestDocumentRequest,
            {
                "title": "Doc",
                "text": "Body",
                "source_external_id": "doc-1",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/episodes",
            episodes_api.IngestEpisodeRequest,
            {
                "space_id": "space",
                "memory_scope_id": "memory_scope",
                "thread_id": "thread",
                "source_external_id": "episode-1",
                "text": "hello",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/facts",
            facts_api.RememberFactRequest,
            {
                "space_id": "space",
                "memory_scope_id": "memory_scope",
                "text": "Fact",
                "source_refs": [{"source_type": "manual", "source_id": "ref-1"}],
                "unexpected": "raw",
            },
        ),
        (
            "/v1/facts/fact_1/relations",
            facts_api.LinkFactRequest,
            {
                "target_fact_id": "fact_2",
                "relation_type": "supports",
                "reason": "strict relation request",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/spaces",
            spaces_memory_scopes_api.CreateSpaceRequest,
            {"slug": "strict-space", "name": "Strict Space", "unexpected": "raw"},
        ),
        (
            "/v1/thread-memory/status",
            thread_memory_api.ThreadMemoryScopeRequest,
            {
                "space_id": "space",
                "memory_scope_id": "memory_scope",
                "thread_id": "thread",
                "unexpected": "raw",
            },
        ),
        (
            "/v1/export/memory_scope-snapshot/preview",
            memory_scopes_feature.PreviewMemoryScopeSnapshotRequest,
            {
                "space_slug": "space",
                "memory_scope_external_ref": "memory_scope",
                "snapshot": {"schema_version": 1},
                "unexpected": "raw",
            },
        ),
    )

    for path, request_model, payload in cases:
        try:
            request_model.model_validate(payload)
        except ValidationError as exc:
            errors = exc.errors()
        else:
            raise AssertionError(f"{path} accepted an unexpected field")

        assert any(
            error["loc"] == ("unexpected",)
            and error["type"] == "extra_forbidden"
            for error in errors
        ), path

    async def validate_error_response() -> object:
        return await request_validation_error_handler(None, RequestValidationError([]))

    response = asyncio.run(validate_error_response())

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "memory.validation"


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
    body = app.openapi()

    paths = body["paths"]
    assert "/api/v1/interview-memory/context" in paths
    schemas = body["components"]["schemas"]
    assert set(schemas["LegacyContextRequest"]["required"]) == {
        "session_id",
        "current_request",
    }
