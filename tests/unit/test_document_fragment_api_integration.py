from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_mcp.domain.models import MemoryDocumentIngestResponse
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


def test_document_ingest_returns_fragment_summary_and_typed_chunks(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "title": "ADR-0007 Memory architecture",
                "text": "\n".join(
                    [
                        "# ADR-0007",
                        "## Decision",
                        "- Use FastAPI for the public API.",
                        "## Risks",
                        "- Do not run Graphiti projections in the request path.",
                        "## Plan",
                        "1. Keep canonical facts in Postgres.",
                        "## References",
                        "- ADR-0004",
                    ]
                ),
                "source_type": "document",
                "source_external_id": "adr-0007",
            },
            headers=auth_headers(),
        )
        document_id = created.json()["data"]["id"]
        chunks = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        )

    assert created.status_code == 201
    assert created.json()["data"]["chunks"] == 4
    assert created.json()["data"]["fragment_summary"] == {
        "fragment_count": 4,
        "node_counts": {
            "claim": 1,
            "risk": 1,
            "plan_item": 1,
            "reference": 1,
        },
        "node_map": {
            "claim": [0],
            "risk": [1],
            "plan_item": [2],
            "reference": [3],
        },
    }
    assert chunks.status_code == 200
    assert [chunk["kind"] for chunk in chunks.json()["data"]] == [
        "document_claim",
        "document_risk",
        "document_plan_item",
        "document_reference",
    ]
    assert [chunk["metadata"]["node_kind"] for chunk in chunks.json()["data"]] == [
        "claim",
        "risk",
        "plan_item",
        "reference",
    ]


def test_document_ingest_preserves_multimodal_source_refs(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/v1/documents",
            json={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "title": "Multimodal external transcript",
                "text": (
                    "Project Atlas screenshot OCR and transcript segment confirm the "
                    "invoice review timeline."
                ),
                "source_type": "asset_extraction",
                "source_external_id": "extract-atlas-review",
                "source_refs": [
                    {
                        "source_type": "asset_extraction",
                        "source_id": "extract-atlas-review",
                        "quote_preview": "OCR region says Project Atlas invoice review.",
                        "page_number": 2,
                        "time_start_ms": 1200,
                        "time_end_ms": 5400,
                        "bbox": [12.0, 32.0, 300.0, 88.0],
                    }
                ],
            },
            headers=auth_headers(),
        )
        document_id = created.json()["data"]["id"]
        chunks = client.get(
            f"/v1/documents/{document_id}/chunks",
            headers=auth_headers(),
        )

    assert created.status_code == 201, created.text
    assert chunks.status_code == 200, chunks.text
    refs = chunks.json()["data"][0]["source_refs"]
    assert refs[0]["source_type"] == "asset_extraction"
    assert refs[0]["source_id"] == "extract-atlas-review"
    assert refs[0]["page_number"] == 2
    assert refs[0]["time_start_ms"] == 1200
    assert refs[0]["time_end_ms"] == 5400
    assert refs[0]["bbox"] == [12.0, 32.0, 300.0, 88.0]


def test_mcp_document_ingest_response_preserves_fragment_summary() -> None:
    response = MemoryDocumentIngestResponse.model_validate(
        {
            "ok": True,
            "message": "Document ingested.",
            "data": {
                "id": "doc_1",
                "chunks": 2,
                "fragment_summary": {
                    "fragment_count": 2,
                    "node_counts": {"claim": 1, "risk": 1},
                    "node_map": {"claim": [0], "risk": [1]},
                },
            },
            "diagnostics": {"trace_id": "test"},
        }
    )

    assert response.data is not None
    assert response.data.fragment_summary.node_counts == {"claim": 1, "risk": 1}
