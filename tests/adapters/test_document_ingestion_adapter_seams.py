"""Import and placeholder checks for document_ingestion adapter seams."""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    ChunkingPolicy,
    DocumentChunk,
    DocumentIngestionScope,
    SourceDocument,
    SourceDocumentDraft,
    SourceDocumentOrigin,
    content_hash_for_text,
)


def test_document_ingestion_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.document_ingestion")

    assert module.FEATURE_ID == FEATURE_ID == "document_ingestion"
    assert module.PostgresSourceDocumentStore.feature_id == FEATURE_ID
    assert module.PostgresDocumentChunkStore.feature_id == FEATURE_ID
    assert module.PostgresDocumentIngestionStore.feature_id == FEATURE_ID
    assert module.QdrantDocumentChunkIndex.feature_id == FEATURE_ID
    assert module.DocumentExtractionIngestionAdapter.feature_id == FEATURE_ID


def test_document_ingestion_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in ("sqlalchemy", "qdrant_client", "docling", "openai", "graphiti"):
        sys.modules.pop(module_name, None)

    importlib.import_module("infinity_context_adapters.features.document_ingestion")

    assert "sqlalchemy" not in sys.modules
    assert "qdrant_client" not in sys.modules
    assert "docling" not in sys.modules
    assert "openai" not in sys.modules
    assert "graphiti" not in sys.modules


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
