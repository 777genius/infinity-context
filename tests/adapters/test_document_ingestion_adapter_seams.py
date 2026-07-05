"""Import and placeholder checks for document_ingestion adapter seams."""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    ChunkingPolicy,
    DocumentChunk,
    DocumentIngestionScope,
    DocumentIngestionValidationError,
    IngestDocumentCommand,
    IngestDocumentHandler,
    SourceDocument,
    SourceDocumentDraft,
    SourceDocumentOrigin,
    content_hash_for_text,
)

FEATURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "infinity_context_adapters"
    / "infinity_context_adapters"
    / "features"
    / "document_ingestion"
)
ALLOWED_CORE_FEATURE_IMPORT = "infinity_context_core.features.document_ingestion.public"
FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "graphiti",
    "graphiti_core",
    "infinity_context_core.features.document_ingestion.application",
    "infinity_context_core.features.document_ingestion.domain",
    "infinity_context_core.features.document_ingestion.ports",
    "openai",
    "qdrant_client",
    "sqlalchemy",
)


def test_document_ingestion_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.document_ingestion")

    assert module.FEATURE_ID == FEATURE_ID == "document_ingestion"
    assert module.DocumentChunkIndexProjection.feature_id == FEATURE_ID
    assert module.InMemorySourceDocumentStore.feature_id == FEATURE_ID
    assert module.InMemoryDocumentChunkStore.feature_id == FEATURE_ID
    assert module.InMemoryDocumentIngestionStore.feature_id == FEATURE_ID
    assert module.PostgresSourceDocumentStore.feature_id == FEATURE_ID
    assert module.PostgresDocumentChunkStore.feature_id == FEATURE_ID
    assert module.PostgresDocumentIngestionStore.feature_id == FEATURE_ID
    assert module.QdrantDocumentChunkIndex.feature_id == FEATURE_ID
    assert module.DocumentExtractionIngestionAdapter.feature_id == FEATURE_ID
    assert module.DocumentIngestionExtractionComponents.feature_id == FEATURE_ID


def test_document_ingestion_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "docling", "openai", "graphiti"):
        sys.modules.pop(module_name, None)

    importlib.import_module("infinity_context_adapters.features.document_ingestion")

    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "docling" not in sys.modules
    assert "openai" not in sys.modules
    assert "graphiti" not in sys.modules


def test_document_ingestion_adapter_imports_only_public_core_feature_api() -> None:
    violations: list[str] = []

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if imported == ALLOWED_CORE_FEATURE_IMPORT:
                continue
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


def test_document_ingestion_extraction_composition_builds_standard_components() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "docling", "openai", "graphiti"):
        sys.modules.pop(module_name, None)

    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion"
    )

    components = module.create_document_ingestion_extraction_components(
        openai_api_key=None,
        vision_model="gpt-4.1-mini",
        vision_detail="high",
        provider_timeout_seconds=60,
        transcription_provider="openai",
        transcription_model="gpt-4o-mini-transcribe",
        transcription_max_upload_bytes=25 * 1024 * 1024,
        asr_model="base",
        asr_device="auto",
        asr_compute_type="default",
    )

    assert components.feature_id == FEATURE_ID
    assert components.adapter_name == "standard_asset_extraction"
    assert hasattr(components.detector, "detect")
    assert hasattr(components.extractor, "extract")
    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "docling" not in sys.modules
    assert "openai" not in sys.modules
    assert "graphiti" not in sys.modules


def test_in_memory_document_store_persists_and_queries_documents_and_chunks() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion"
    )
    document, chunk = _document_and_chunk()
    source_documents = module.create_in_memory_source_document_store()
    chunks = module.create_in_memory_document_chunk_store()
    injected_store = module.create_in_memory_document_ingestion_store(
        source_documents=source_documents,
        chunks=chunks,
    )
    store = module.create_in_memory_document_ingestion_store()

    assert injected_store.source_documents is source_documents
    assert injected_store.chunks is chunks

    saved_document = asyncio.run(store.source_documents.create(document))
    found_document = asyncio.run(
        store.source_documents.find_active_by_content_hash(
            scope=document.identity.scope,
            content_hash=document.content_hash,
        )
    )
    first_upsert = asyncio.run(store.chunks.upsert(chunk))
    duplicate_upsert = asyncio.run(store.chunks.upsert(chunk))

    assert saved_document == document
    assert asyncio.run(store.source_documents.get("doc-1")) == document
    assert found_document == document
    assert first_upsert.chunk == chunk
    assert first_upsert.duplicate is False
    assert duplicate_upsert.chunk == chunk
    assert duplicate_upsert.duplicate is True
    assert asyncio.run(store.chunks.list_for_document("doc-1")) == (chunk,)
    assert asyncio.run(store.chunks.list_for_document("doc-1", limit=0)) == ()


def test_in_memory_document_store_can_drive_core_ingest_handler() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion"
    )
    store = module.create_in_memory_document_ingestion_store()
    handler = IngestDocumentHandler(
        source_documents=store.source_documents,
        chunks=store.chunks,
    )
    command = _ingest_command()

    result = asyncio.run(handler.execute(command))
    duplicate = asyncio.run(handler.execute(command))

    assert result.document.identity.document_id
    assert len(result.chunks) == 1
    assert result.duplicate_chunk_count == 0
    assert result.indexing_status == "pending"
    assert duplicate.document == result.document
    assert duplicate.chunks == result.chunks
    assert duplicate.duplicate_chunk_count == len(result.chunks)
    assert duplicate.indexing_status == "already_indexed_or_pending"


def test_document_chunk_index_projection_maps_public_document_state() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion"
    )
    document, chunk = _document_and_chunk()

    projection = module.DocumentChunkIndexProjection.from_document_chunk(
        document=document,
        chunk=chunk,
    )
    factory_projection = module.document_chunk_index_projection_from_chunk(
        document=document,
        chunk=chunk,
    )
    item = projection.to_index_item()

    assert projection == factory_projection
    assert projection.feature_id == FEATURE_ID
    assert item.chunk_id == chunk.identity.chunk_id
    assert item.document_id == document.identity.document_id
    assert item.scope == chunk.identity.scope
    assert item.origin == document.origin
    assert item.text == chunk.text
    assert item.content_hash == chunk.content_hash
    assert item.sequence == chunk.sequence


def test_document_chunk_index_projection_rejects_cross_document_chunks() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion"
    )
    document, chunk = _document_and_chunk()
    other_document = SourceDocument.from_draft(
        document_id="doc-2",
        draft=SourceDocumentDraft.create(
            scope=document.identity.scope,
            title="Other",
            origin=document.origin,
            text="Other document content.",
        ),
    )

    with pytest.raises(DocumentIngestionValidationError, match="same document"):
        module.DocumentChunkIndexProjection.from_document_chunk(
            document=other_document,
            chunk=chunk,
        )


def test_postgres_document_store_is_explicit_placeholder() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion.postgres_document_store"
    )
    document, chunk = _document_and_chunk()

    with pytest.raises(
        NotImplementedError,
        match="canonical document persistence wiring is deferred",
    ):
        asyncio.run(module.PostgresSourceDocumentStore().create(document))

    with pytest.raises(
        NotImplementedError,
        match="canonical document persistence wiring is deferred",
    ):
        asyncio.run(module.PostgresDocumentChunkStore().upsert(chunk))

    store = module.create_postgres_document_ingestion_store()
    assert store.feature_id == FEATURE_ID
    assert store.source_documents.feature_id == FEATURE_ID
    assert store.chunks.feature_id == FEATURE_ID
    assert module.create_postgres_source_document_store().feature_id == FEATURE_ID
    assert module.create_postgres_document_chunk_store().feature_id == FEATURE_ID


def test_qdrant_chunk_index_is_explicit_placeholder() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion.qdrant_chunk_index"
    )
    document, chunk = _document_and_chunk()
    item = module.DocumentChunkIndexItem(
        chunk_id=chunk.identity.chunk_id,
        document_id=document.identity.document_id,
        scope=document.identity.scope,
        origin=document.origin,
        text=chunk.text,
        content_hash=chunk.content_hash,
        sequence=chunk.sequence,
    )

    with pytest.raises(NotImplementedError, match="derived chunk index wiring is deferred"):
        asyncio.run(module.QdrantDocumentChunkIndex().upsert_chunks((item,)))

    with pytest.raises(NotImplementedError, match="derived chunk index wiring is deferred"):
        asyncio.run(module.create_qdrant_document_chunk_index().delete_chunks(("chunk-1",)))


def test_extraction_seam_builds_ingestion_command_without_provider_runtime() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.document_ingestion.extraction_adapter"
    )
    adapter = module.create_document_extraction_ingestion_adapter()
    extracted = module.ExtractedDocumentText(
        text="  Extracted\r\ntext from a provider.  ",
        source_external_id="asset-1",
        source_type="asset",
        uri="file:///tmp/source.md",
        classification="internal",
        idempotency_key="ingest-asset-1",
    )
    scope = DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")

    command = adapter.build_command(scope=scope, extracted=extracted)

    assert command.scope == scope
    assert command.title == "asset-1"
    assert command.text == "Extracted\ntext from a provider."
    assert command.origin == SourceDocumentOrigin(
        source_type="asset",
        source_external_id="asset-1",
        uri="file:///tmp/source.md",
    )
    assert command.classification == "internal"
    assert command.idempotency_key == "ingest-asset-1"


def _ingest_command() -> IngestDocumentCommand:
    return IngestDocumentCommand(
        scope=DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1"),
        title="Runbook",
        origin=SourceDocumentOrigin(
            source_type="upload",
            source_external_id="runbook.md",
        ),
        text="Postgres owns canonical document lifecycle for ingested text.",
        classification="internal",
    )


def _document_and_chunk() -> tuple[SourceDocument, DocumentChunk]:
    scope = DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    origin = SourceDocumentOrigin(source_type="upload", source_external_id="doc.md")
    draft = SourceDocumentDraft.create(
        scope=scope,
        title="Document",
        origin=origin,
        text="Postgres owns canonical document lifecycle.",
    )
    document = SourceDocument.from_draft(document_id="doc-1", draft=draft)
    chunk_draft = ChunkingPolicy().plan_chunks(draft.content.text)[0]
    chunk = DocumentChunk.from_draft(
        chunk_id="chunk-1",
        document_id=document.identity.document_id,
        scope=scope,
        draft=chunk_draft,
    )

    assert content_hash_for_text(chunk.text) == chunk.content_hash
    return document, chunk


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _matches_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for prefix in prefixes
    )
