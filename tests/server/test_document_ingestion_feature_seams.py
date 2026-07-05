from __future__ import annotations

import ast
import asyncio
from datetime import datetime
from pathlib import Path

from infinity_context_contracts.features.document_ingestion import (
    IngestDocumentRequestDto,
)
import infinity_context_core.features.document_ingestion.public as document_ingestion
from infinity_context_server.features.document_ingestion import public as server_public
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "document_ingestion"
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
        "build_document_ingestion_server_feature",
        "create_document_ingestion_router",
        "ingest_document_command_from_contract",
        "ingest_document_result_to_contract",
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
            if imported.startswith("infinity_context_core.features."):
                if not imported.endswith(".public"):
                    violations.append(f"{rel}: imports {imported}")
            if imported == "infinity_context_core" or any(
                imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes
            ):
                violations.append(f"{rel}: imports {imported}")
            elif imported in forbidden_prefixes:
                violations.append(f"{rel}: imports {imported}")

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
