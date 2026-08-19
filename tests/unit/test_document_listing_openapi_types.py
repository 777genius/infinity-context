"""Typed OpenAPI contract for document listing pages."""

from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app


def test_document_listing_openapi_has_typed_record_and_page_fields() -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )
    schemas = app.openapi()["components"]["schemas"]
    record = schemas["DocumentRecordResponse"]
    page = schemas["DocumentListResponse"]

    assert set(record["required"]) == {
        "id",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "title",
        "source_type",
        "source_external_id",
        "content_hash",
        "classification",
        "status",
        "created_at",
        "updated_at",
    }
    assert record["additionalProperties"] is False
    assert set(page["required"]) == {"data", "next_cursor"}
    assert page["additionalProperties"] is False
    assert page["properties"]["data"]["items"]["$ref"].endswith("/DocumentRecordResponse")
