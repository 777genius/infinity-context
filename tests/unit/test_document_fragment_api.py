import asyncio
from datetime import datetime
from types import SimpleNamespace

from fastapi import Response
from infinity_context_core.application import (
    DocumentChunksQueryResult,
    IngestDocumentCommand,
    IngestDocumentResult,
    ScopeResult,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocument,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)
from infinity_context_mcp.domain.models import MemoryDocumentIngestResponse
from infinity_context_server.api.v1 import documents as documents_api
from infinity_context_server.config import MemoryPolicyMode


def test_document_ingest_returns_fragment_summary_and_typed_chunks() -> None:
    container = _FakeDocumentApiContainer()

    created = asyncio.run(
        documents_api.ingest_document(
            documents_api.IngestDocumentRequest(
                title="ADR-0007 Memory architecture",
                text="\n".join(
                    (
                        "# ADR-0007",
                        "## Decision",
                        "- Use FastAPI for the public API.",
                        "## Risks",
                        "- Do not run Graphiti projections in the request path.",
                        "## Plan",
                        "1. Keep canonical facts in Postgres.",
                        "## References",
                        "- ADR-0004",
                    )
                ),
                source_type="document",
                source_external_id="adr-0007",
            ),
            container=container,
            response=Response(),
        )
    )
    document_id = created["data"]["id"]
    chunks = asyncio.run(
        documents_api.list_document_chunks(
            document_id,
            container=container,
        )
    )

    assert _documents_post_status_code() == 201
    assert created["data"]["chunks"] == 4
    assert created["data"]["fragment_summary"] == {
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
    assert [chunk["kind"] for chunk in chunks["data"]] == [
        "document_claim",
        "document_risk",
        "document_plan_item",
        "document_reference",
    ]
    assert [chunk["metadata"]["node_kind"] for chunk in chunks["data"]] == [
        "claim",
        "risk",
        "plan_item",
        "reference",
    ]


def test_document_ingest_preserves_multimodal_source_refs() -> None:
    container = _FakeDocumentApiContainer()

    created = asyncio.run(
        documents_api.ingest_document(
            documents_api.IngestDocumentRequest(
                title="Multimodal external transcript",
                text=(
                    "Project Atlas screenshot OCR and transcript segment confirm the "
                    "invoice review timeline."
                ),
                source_type="asset_extraction",
                source_external_id="extract-atlas-review",
                source_refs=[
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
            ),
            container=container,
            response=Response(),
        )
    )
    document_id = created["data"]["id"]
    chunks = asyncio.run(
        documents_api.list_document_chunks(
            document_id,
            container=container,
        )
    )

    assert _documents_post_status_code() == 201
    refs = chunks["data"][0]["source_refs"]
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


class _FakeDocumentApiContainer:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            policy_mode=MemoryPolicyMode.ACTIVE_CONTEXT,
            outbox_backpressure_pending_threshold=0,
            default_space_slug="client-app",
            default_memory_scope_external_ref="default",
        )
        self.state = SimpleNamespace(document=None, chunks=())
        self.ensure_scope = _FakeEnsureScope()
        self.ingest_document = _FakeIngestDocument(self.state)
        self.list_document_chunks = _FakeListDocumentChunks(self.state)


class _FakeEnsureScope:
    async def execute(self, _command: object) -> ScopeResult:
        return ScopeResult(
            space_id=SpaceId("space_client_app"),
            memory_scope_id=MemoryScopeId("memory_scope_default"),
        )


class _FakeIngestDocument:
    def __init__(self, state: SimpleNamespace) -> None:
        self._state = state
        self.commands: list[IngestDocumentCommand] = []

    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        self.commands.append(command)
        document = _document_from_command(command)
        chunks = _chunks_from_command(command, document)
        self._state.document = document
        self._state.chunks = chunks
        return IngestDocumentResult(
            document=document,
            chunks=chunks,
            duplicate_chunks=0,
            indexing_status="queued",
        )


class _FakeListDocumentChunks:
    def __init__(self, state: SimpleNamespace) -> None:
        self._state = state

    async def execute(self, _query: object) -> DocumentChunksQueryResult:
        return DocumentChunksQueryResult(
            document=self._state.document,
            chunks=self._state.chunks,
        )


def _document_from_command(command: IngestDocumentCommand) -> MemoryDocument:
    return MemoryDocument.create(
        document_id=MemoryDocumentId("doc_1"),
        space_id=command.space_id,
        memory_scope_id=command.memory_scope_id,
        thread_id=command.thread_id,
        title=command.title,
        source_type=command.source_type,
        source_external_id=command.source_external_id,
        content_hash="hash_document",
        classification=command.classification,
        now=datetime(2026, 1, 2, 3, 4, 5),
    )


def _chunks_from_command(
    command: IngestDocumentCommand,
    document: MemoryDocument,
) -> tuple[MemoryChunk, ...]:
    if command.source_external_id == "adr-0007":
        return (
            _chunk(command, document, sequence=0, kind=MemoryChunkKind.DOCUMENT_CLAIM),
            _chunk(command, document, sequence=1, kind=MemoryChunkKind.DOCUMENT_RISK),
            _chunk(command, document, sequence=2, kind=MemoryChunkKind.DOCUMENT_PLAN_ITEM),
            _chunk(command, document, sequence=3, kind=MemoryChunkKind.DOCUMENT_REFERENCE),
        )
    return (
        _chunk(
            command,
            document,
            sequence=0,
            kind=MemoryChunkKind.DOCUMENT_CLAIM,
            metadata=dict(command.chunk_metadata or {}),
        ),
    )


def _chunk(
    command: IngestDocumentCommand,
    document: MemoryDocument,
    *,
    sequence: int,
    kind: MemoryChunkKind,
    metadata: dict[str, object] | None = None,
) -> MemoryChunk:
    metadata = dict(metadata or {})
    metadata.setdefault("node_kind", _node_kind(kind))
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(f"chunk_{sequence + 1}"),
        space_id=command.space_id,
        memory_scope_id=command.memory_scope_id,
        thread_id=command.thread_id,
        document_id=document.id,
        source_type=command.source_type,
        source_external_id=command.source_external_id,
        source_hash="hash_source",
        kind=kind,
        text=command.text,
        normalized_text=command.text.lower(),
        sequence=sequence,
        char_start=0,
        char_end=len(command.text),
        token_estimate=8,
        metadata=metadata,
        classification=command.classification,
        now=datetime(2026, 1, 2, 3, 4, 5),
    )


def _node_kind(kind: MemoryChunkKind) -> str:
    return {
        MemoryChunkKind.DOCUMENT_CLAIM: "claim",
        MemoryChunkKind.DOCUMENT_RISK: "risk",
        MemoryChunkKind.DOCUMENT_PLAN_ITEM: "plan_item",
        MemoryChunkKind.DOCUMENT_REFERENCE: "reference",
    }[kind]


def _documents_post_status_code() -> int:
    for route in documents_api.router.routes:
        if route.path == "/documents" and "POST" in route.methods:
            return route.status_code
    raise AssertionError("documents POST route was not registered")
