from __future__ import annotations

import ast
import asyncio
from datetime import datetime
from pathlib import Path

import infinity_context_core.features.document_ingestion.public as document_ingestion
import pytest
from infinity_context_contracts.features.document_ingestion import (
    IngestDocumentRequestDto,
)
from infinity_context_core.application.dto import DeduplicationInfo
from infinity_context_core.domain.assets import MemoryAsset, MemoryAssetId
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocument,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)
from infinity_context_core.domain.errors import MemoryQuotaExceededError
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    ExtractionArtifact,
    ExtractionArtifactId,
)
from infinity_context_server.features.document_ingestion import public as server_public

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "document_ingestion"
)
DOCUMENTS_API_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "documents.py"
)
ASSETS_API_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "assets.py"
)


class RecordingPrepareDocumentIngestion:
    def __init__(self) -> None:
        self.commands: list[document_ingestion.IngestDocumentCommand] = []

    async def execute(
        self,
        command: document_ingestion.IngestDocumentCommand,
    ) -> document_ingestion.PreparedDocumentIngestion:
        self.commands.append(command)
        return await document_ingestion.PrepareDocumentIngestionHandler().execute(command)


class RecordingIngestDocument:
    def __init__(self) -> None:
        self.commands: list[document_ingestion.IngestDocumentCommand] = []

    async def execute(
        self,
        command: document_ingestion.IngestDocumentCommand,
    ) -> document_ingestion.IngestDocumentResult:
        self.commands.append(command)
        draft = document_ingestion.SourceDocumentDraft.create(
            scope=command.scope,
            title=command.title,
            origin=command.origin,
            text=command.text,
            classification=command.classification,
        )
        document = document_ingestion.SourceDocument.from_draft(
            document_id="doc_1",
            draft=draft,
            now=datetime(2026, 1, 2, 3, 4, 5),
        )
        chunk_draft = document_ingestion.ChunkingPolicy().plan_chunks(
            draft.content.text
        )[0]
        chunk = document_ingestion.DocumentChunk.from_draft(
            chunk_id="chunk_1",
            document_id=document.identity.document_id,
            scope=command.scope,
            draft=chunk_draft,
        )
        return document_ingestion.IngestDocumentResult(
            document=document,
            chunks=(chunk,),
            indexing_status="queued",
        )


def test_document_ingestion_server_feature_public_surface_composes_router() -> None:
    recorder = RecordingIngestDocument()
    use_cases = document_ingestion.DocumentIngestionUseCases(
        prepare_document_ingestion=RecordingPrepareDocumentIngestion(),
        ingest_document=recorder,
    )
    feature = server_public.build_document_ingestion_server_feature(
        use_cases,
        route_prefix="/document-ingestion",
    )

    assert feature.feature_id == "document_ingestion"
    assert server_public.__all__ == (
        "DocumentIngestionServerFeature",
        "FEATURE_ID",
        "IngestDocumentHttpRequest",
        "LegacyDocumentSourceRefRequest",
        "LegacyIngestDocumentRequest",
        "asset_extraction_error_to_response",
        "asset_extraction_to_response",
        "asset_to_response",
        "build_document_ingestion_server_feature",
        "chunk_to_response",
        "create_document_ingestion_router",
        "deduplication_to_response",
        "document_to_response",
        "extraction_artifact_to_response",
        "ingest_document_command_from_contract",
        "ingest_document_result_to_contract",
        "legacy_ingest_document_command_from_request",
    )
    assert server_public.FEATURE_ID == "document_ingestion"
    assert {route.path for route in feature.create_router().routes} == {
        "/document-ingestion/documents"
    }


def test_document_ingestion_mapper_builds_feature_public_application_command() -> None:
    request = IngestDocumentRequestDto(
        text="  Postgres owns canonical document lifecycle.  ",
        title="Architecture Notes",
        source_uri="file:///notes/architecture.md",
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        idempotency_key="ingest_1",
        metadata={
            "classification": "internal",
            "source_external_id": "notes/architecture.md",
            "source_type": "markdown",
        },
    )

    command = server_public.ingest_document_command_from_contract(request)

    assert isinstance(command, document_ingestion.IngestDocumentCommand)
    assert command.scope.space_id == "space_1"
    assert command.scope.memory_scope_id == "scope_1"
    assert command.scope.thread_id == "thread_1"
    assert command.title == "Architecture Notes"
    assert command.text == "  Postgres owns canonical document lifecycle.  "
    assert command.origin == document_ingestion.SourceDocumentOrigin(
        source_type="markdown",
        source_external_id="notes/architecture.md",
        uri="file:///notes/architecture.md",
    )
    assert command.classification == "internal"
    assert command.idempotency_key == "ingest_1"


def test_document_ingestion_mapper_requires_resolved_scope_ids() -> None:
    request = IngestDocumentRequestDto(
        text="Postgres owns canonical document lifecycle.",
        title="Architecture Notes",
        source_uri="file:///notes/architecture.md",
        space_slug="client-app",
        memory_scope_external_ref="default",
        metadata={
            "source_external_id": "notes/architecture.md",
        },
    )

    with pytest.raises(ValueError, match="space_id is required"):
        server_public.ingest_document_command_from_contract(request)


def test_document_ingestion_mapper_builds_legacy_documents_command() -> None:
    class LegacyCommand:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    request = server_public.LegacyIngestDocumentRequest(
        title="  Architecture Notes  ",
        text="Postgres owns canonical document lifecycle.",
        source_type="markdown",
        source_external_id="notes/architecture.md",
        classification="internal",
        source_refs=[
            server_public.LegacyDocumentSourceRefRequest(
                source_type="asset_extraction",
                source_id="extract-atlas-review",
                quote_preview="OCR region says Project Atlas invoice review.",
                page_number=2,
                time_start_ms=1200,
                time_end_ms=5400,
                bbox=(12.0, 32.0, 300.0, 88.0),
            )
        ],
    )

    command = server_public.legacy_ingest_document_command_from_request(
        request,
        command_factory=LegacyCommand,
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        idempotency_key="ingest_1",
    )

    assert command.kwargs == {
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "thread_id": "thread_1",
        "title": "Architecture Notes",
        "text": "Postgres owns canonical document lifecycle.",
        "source_type": "markdown",
        "source_external_id": "notes/architecture.md",
        "idempotency_key": "ingest_1",
        "classification": "internal",
        "chunk_metadata": {
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
            "source_ref_count": 1,
        },
    }


def test_document_ingestion_route_maps_http_contract_to_feature_use_case() -> None:
    recorder = RecordingIngestDocument()
    use_cases = document_ingestion.DocumentIngestionUseCases(
        prepare_document_ingestion=RecordingPrepareDocumentIngestion(),
        ingest_document=recorder,
    )
    router = server_public.create_document_ingestion_router(use_cases)
    route = next(route for route in router.routes if route.path == "/documents")

    body = asyncio.run(
        route.endpoint(
            server_public.IngestDocumentHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                title="Architecture Notes",
                text="Postgres owns canonical document lifecycle.",
                source_type="markdown",
                source_external_id="notes/architecture.md",
                source_uri="file:///notes/architecture.md",
                classification="internal",
                idempotency_key="ingest_1",
            )
        )
    )

    assert len(recorder.commands) == 1
    assert recorder.commands[0].scope.memory_scope_id == "scope_1"
    assert recorder.commands[0].origin.source_external_id == "notes/architecture.md"

    document = body["data"]["document"]
    assert document["id"] == "doc_1"
    assert document["space_id"] == "space_1"
    assert document["memory_scope_id"] == "scope_1"
    assert document["thread_id"] == "thread_1"
    assert document["title"] == "Architecture Notes"
    assert document["source_uri"] == "file:///notes/architecture.md"
    assert document["status"] == "active"
    assert document["created_at"] == "2026-01-02T03:04:05"
    assert document["metadata"] == {
        "classification": "internal",
        "source_external_id": "notes/architecture.md",
        "source_type": "markdown",
    }
    assert body["data"]["created"] is True
    assert body["data"]["indexing_status"] == "queued"

    chunk = body["data"]["chunks"][0]
    assert chunk["id"] == "chunk_1"
    assert chunk["document_id"] == "doc_1"
    assert chunk["chunk_index"] == 0
    assert chunk["text"] == "Postgres owns canonical document lifecycle."
    assert chunk["char_start"] == 0
    assert chunk["char_end"] == 43
    assert chunk["token_count"] > 0
    assert chunk["metadata"]["kind"] == "document_text"
    assert chunk["metadata"]["status"] == "active"


def test_document_ingestion_public_seam_maps_legacy_document_api_responses() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5)
    document = MemoryDocument.create(
        document_id=MemoryDocumentId("doc_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        thread_id=ThreadId("thread_1"),
        title="Architecture Notes",
        source_type="markdown",
        source_external_id="notes/architecture.md",
        content_hash="hash_document",
        classification="internal",
        now=now,
    )
    chunks = (
        MemoryChunk.create(
            chunk_id=MemoryChunkId("chunk_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            thread_id=ThreadId("thread_1"),
            document_id=MemoryDocumentId("doc_1"),
            source_type="markdown",
            source_external_id="notes/architecture.md",
            source_hash="hash_source",
            kind=MemoryChunkKind.DOCUMENT_CLAIM,
            text="Postgres owns canonical document lifecycle.",
            normalized_text="postgres owns canonical document lifecycle.",
            sequence=0,
            char_start=0,
            char_end=43,
            token_estimate=6,
            metadata={
                "node_kind": "claim",
                "source_refs": [
                    {
                        "source_type": "asset_extraction",
                        "source_id": "extract-atlas-review",
                        "quote_preview": "OCR region says Project Atlas invoice review.",
                        "api_key": "sk-" + "secret-key-that-should-not-leak",
                    }
                ],
            },
            classification="internal",
            now=now,
        ),
        MemoryChunk.create(
            chunk_id=MemoryChunkId("chunk_2"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            thread_id=ThreadId("thread_1"),
            document_id=MemoryDocumentId("doc_1"),
            source_type="markdown",
            source_external_id="notes/architecture.md",
            source_hash="hash_source",
            kind=MemoryChunkKind.DOCUMENT_RISK,
            text="Request-path graph projections are too slow.",
            normalized_text="request-path graph projections are too slow.",
            sequence=1,
            char_start=44,
            char_end=88,
            token_estimate=7,
            metadata={"node_kind": "risk"},
            classification="internal",
            now=now,
        ),
    )

    body = server_public.document_to_response(
        document,
        chunks=2,
        chunk_items=chunks,
        duplicate_chunks=1,
        indexing_status="queued",
        deleted_chunks=3,
        deleted_facts=4,
    )
    chunk = server_public.chunk_to_response(chunks[0])

    assert body == {
        "id": "doc_1",
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "thread_id": "thread_1",
        "title": "Architecture Notes",
        "source_type": "markdown",
        "source_external_id": "notes/architecture.md",
        "content_hash": "hash_document",
        "classification": "internal",
        "status": "active",
        "created_at": "2026-01-02T03:04:05",
        "updated_at": "2026-01-02T03:04:05",
        "chunks": 2,
        "fragment_summary": {
            "fragment_count": 2,
            "node_counts": {"claim": 1, "risk": 1},
            "node_map": {"claim": [0], "risk": [1]},
        },
        "duplicate_chunks": 1,
        "indexing_status": "queued",
        "deleted_chunks": 3,
        "deleted_facts": 4,
    }
    assert chunk["id"] == "chunk_1"
    assert chunk["document_id"] == "doc_1"
    assert chunk["episode_id"] is None
    assert chunk["kind"] == "document_claim"
    assert chunk["sequence"] == 0
    assert chunk["status"] == "active"
    assert chunk["classification"] == "internal"
    assert chunk["source_refs"] == [
        {
            "source_type": "asset_extraction",
            "source_id": "extract-atlas-review",
            "quote_preview": "OCR region says Project Atlas invoice review.",
        }
    ]
    assert "api_key" not in chunk["metadata"]["source_refs"][0]


def test_document_ingestion_public_seam_maps_asset_api_responses() -> None:
    raw_secret = "sk-redacted1234"
    now = datetime(2026, 1, 2, 3, 4, 5)
    asset = MemoryAsset.create(
        asset_id=MemoryAssetId("asset_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        thread_id=ThreadId("thread_1"),
        filename="receipt.png",
        content_type="image/png",
        byte_size=1234,
        sha256_hex="a" * 64,
        storage_backend="local",
        storage_key="assets/receipt.png",
        classification="internal",
        metadata={"label": "receipt"},
        now=now,
    )
    deduplication = DeduplicationInfo(
        duplicate=True,
        status="scope_blob_reused",
        reason_code="exact_sha256",
        scope="memory_scope",
        reason_codes=("exact_sha256", "same_memory_scope"),
        duplicate_of_asset_id="asset_source",
        storage_key_reused=True,
        blob_written=False,
    )
    job = (
        AssetExtractionJob.create(
            job_id=AssetExtractionJobId("extract_1"),
            asset_id=MemoryAssetId("asset_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("scope_1"),
            thread_id=ThreadId("thread_1"),
            parser_profile="standard_local",
            parser_config_hash="hash",
            source_sha256_hex="a" * 64,
            metadata={
                "usage_plan_tier": "free",
                "usage_media_analysis_seconds_requested": "12",
                "usage_reconciled": "true",
            },
            now=now,
        )
        .mark_failed(
            now=now,
            code="asset_extraction.provider_failed",
            message=f"provider failed with {raw_secret}",
            metadata={
                "processing_stage": f"provider {raw_secret}",
                "progress_message": f"provider token {raw_secret}",
                "debug_message": f"Bearer {raw_secret}",
            },
        )
    )
    artifact = ExtractionArtifact.create(
        artifact_id=ExtractionArtifactId("artifact_1"),
        job_id=AssetExtractionJobId("extract_1"),
        asset_id=MemoryAssetId("asset_1"),
        artifact_type="markdown",
        storage_backend="local",
        storage_key="assets/extractions/extract_1/extracted.md",
        sha256_hex="b" * 64,
        byte_size=42,
        metadata={"filename": "extracted.md", "api_key": raw_secret},
        now=now,
    )
    quota_error = MemoryQuotaExceededError(
        f"quota blocked by provider token {raw_secret}"
    )

    asset_response = server_public.asset_to_response(asset)
    deduplication_response = server_public.deduplication_to_response(deduplication)
    extraction_response = server_public.asset_extraction_to_response(job, now=now)
    artifact_response = server_public.extraction_artifact_to_response(artifact)
    error_response = server_public.asset_extraction_error_to_response(quota_error)

    assert asset_response == {
        "id": "asset_1",
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "thread_id": "thread_1",
        "filename": "receipt.png",
        "content_type": "image/png",
        "byte_size": 1234,
        "sha256_hex": "a" * 64,
        "storage_backend": "local",
        "status": "stored",
        "classification": "internal",
        "metadata": {"label": "receipt"},
        "created_at": "2026-01-02T03:04:05",
        "updated_at": "2026-01-02T03:04:05",
    }
    assert deduplication_response == {
        "duplicate": True,
        "status": "scope_blob_reused",
        "reason_code": "exact_sha256",
        "scope": "memory_scope",
        "reason_codes": ["exact_sha256", "same_memory_scope"],
        "duplicate_of_asset_id": "asset_source",
        "storage_key_reused": True,
        "blob_written": False,
    }
    assert raw_secret not in extraction_response["safe_error_message"]
    assert raw_secret not in extraction_response["metadata"]["debug_message"]
    assert extraction_response["progress"] == {
        "stage": "failed",
        "percent": 100,
        "message": "Extraction failed",
        "terminal": True,
    }
    assert extraction_response["execution"]["retry_actionable"] is True
    assert extraction_response["usage"]["media_analysis_seconds_requested"] == 12
    assert extraction_response["usage"]["reconciled"] is True
    assert artifact_response == {
        "id": "artifact_1",
        "job_id": "extract_1",
        "asset_id": "asset_1",
        "artifact_type": "markdown",
        "storage_backend": "local",
        "download_path": "/v1/extraction-artifacts/artifact_1/download",
        "sha256_hex": "b" * 64,
        "byte_size": 42,
        "metadata": {"filename": "extracted.md"},
        "created_at": "2026-01-02T03:04:05",
    }
    assert error_response == {
        "code": "memory.quota_exceeded",
        "message": "quota blocked by provider token [redacted]",
        "retryable": False,
    }


def test_document_ingestion_server_slice_uses_only_public_feature_boundaries() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "infinity_context_adapters",
        "infinity_context_core.application",
        "infinity_context_core.domain",
        "infinity_context_core.ports",
        "infinity_context_server.api.v1.documents",
        "infinity_context_server.composition",
        "graphiti",
        "openai",
        "qdrant_client",
        "sqlalchemy",
    )

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            rel = path.relative_to(REPO_ROOT)
            if imported.startswith(
                "infinity_context_core.features."
            ) and not imported.endswith(".public"):
                violations.append(f"{rel}: imports {imported}")
            if (
                imported == "infinity_context_core"
                or imported in forbidden_prefixes
                or any(imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
            ):
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_legacy_documents_api_delegates_ingest_mapping_to_public_server_seam() -> None:
    source = DOCUMENTS_API_PATH.read_text(encoding="utf-8")
    imports = _imports(DOCUMENTS_API_PATH)

    assert (
        "from infinity_context_server.features.document_ingestion import "
        "public as document_ingestion_server"
    ) in source
    assert "class IngestDocumentRequest(" in source
    assert "document_ingestion_server.LegacyIngestDocumentRequest" in source
    assert "document_ingestion_server.legacy_ingest_document_command_from_request(" in source
    assert "document_ingestion_server.document_to_response(" in source
    assert "document_ingestion_server.chunk_to_response(" in source
    assert "def document_to_response(" not in source
    assert "def chunk_to_response(" not in source
    assert "def _document_chunk_metadata(" not in source
    assert "def _document_ingestion_feature_request(" not in source
    assert "def _legacy_ingest_document_command(" not in source
    assert "SourceRefRequest" not in source
    assert "document_fragment_summary_from_nodes" not in source
    assert "safe_public_metadata" not in source
    assert "infinity_context_core.features.document_ingestion" not in source
    assert "infinity_context_server.features.document_ingestion." not in source

    violations: list[str] = []
    for imported in imports:
        if imported.startswith("infinity_context_core.features.document_ingestion"):
            violations.append(f"imports {imported}")
        if imported.startswith(
            "infinity_context_server.features.document_ingestion."
        ) and imported != "infinity_context_server.features.document_ingestion.public":
            violations.append(f"imports {imported}")

    assert violations == []


def test_assets_api_delegates_response_mapping_to_public_server_seam() -> None:
    source = ASSETS_API_PATH.read_text(encoding="utf-8")
    imports = _imports(ASSETS_API_PATH)

    assert (
        "from infinity_context_server.features.document_ingestion import "
        "public as document_ingestion_server"
    ) in source
    assert "document_ingestion_server.asset_to_response(" in source
    assert "document_ingestion_server.deduplication_to_response(" in source
    assert "document_ingestion_server.asset_extraction_to_response(" in source
    assert "document_ingestion_server.extraction_artifact_to_response(" in source
    assert "document_ingestion_server.asset_extraction_error_to_response(" in source
    assert "def asset_to_response(" not in source
    assert "def deduplication_to_response(" not in source
    assert "def asset_extraction_to_response(" not in source
    assert "def extraction_artifact_to_response(" not in source
    assert "def _extraction_execution(" not in source
    assert "def _extraction_progress(" not in source
    assert "def _extraction_usage(" not in source
    assert "safe_public_metadata" not in source
    assert "safe_public_text" not in source
    assert "infinity_context_server.features.document_ingestion." not in source

    violations: list[str] = []
    for imported in imports:
        if imported.startswith(
            "infinity_context_server.features.document_ingestion."
        ) and imported != "infinity_context_server.features.document_ingestion.public":
            violations.append(f"imports {imported}")

    assert violations == []


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
