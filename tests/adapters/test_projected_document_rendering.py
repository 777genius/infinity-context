"""Synthetic canonical ingestion and locator rendering regression; no database/provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_adapters.postgres.locator_profile_mapping import projection_item
from infinity_context_adapters.postgres.models import MemoryChunkRow
from infinity_context_adapters.postgres.projected_document_ingestion import (
    PostgresProjectedDocumentIngestor,
)
from infinity_context_adapters.postgres.retrieval_projection_mapping import (
    typed_retrieval_projection,
)
from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import IngestDocumentCommand
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId


class _RecordingSession:
    def __init__(self) -> None:
        self.rows = []

    def add(self, row) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        pass


def test_projected_ingestion_keeps_source_refs_out_of_canonical_embedding_text() -> None:
    title = "mkevidence1." + base64.urlsafe_b64encode(
        hashlib.sha256(b"synthetic-render-audit").digest()
    ).decode().rstrip("=")
    body = "hello " * 33
    source_refs = [
        {
            "source_type": "transcript",
            "kind": "transcript_segment",
            "time_start_ms": 0,
            "time_end_ms": 1000,
        }
    ]
    metadata = {
        "source_refs": source_refs,
        "source_ref_count": 1,
        "_retrieval_projection_contract": {
            "schema_version": "document-retrieval-projection.v1",
            "locator": "synthetic-locator",
            "source_key": "synthetic-source",
            "projection_generation": "generation-1",
            "sequence_ordinal": 0,
            "actor_keys": [],
            "time_interval": None,
            "relative_time_interval": {"start_ms": 0, "end_ms": 1000},
            "kind": "transcript_segment",
            "category": None,
            "tags": [],
        },
    }
    command = IngestDocumentCommand(
        space_id=SpaceId("synthetic-space"),
        memory_scope_id=MemoryScopeId("synthetic-scope"),
        title=title,
        text=body,
        source_type="transcript",
        source_external_id="synthetic-source",
        classification="internal",
        chunk_metadata=metadata,
    )
    session = _RecordingSession()
    ingestor = PostgresProjectedDocumentIngestor(
        engine=None,
        clock=SimpleNamespace(now=lambda: datetime(2026, 9, 8, tzinfo=UTC)),
        ids=SimpleNamespace(new_id=lambda prefix: f"synthetic-{prefix}"),
    )

    result = asyncio.run(
        ingestor._insert(
            session, command, typed_retrieval_projection(metadata), fragment_document_text(body)[0]
        )
    )

    expected = title.lower() + " " + body.strip()
    chunk = result.chunks[0]
    row = next(row for row in session.rows if isinstance(row, MemoryChunkRow))
    # Database defaults are assigned explicitly in this provider-free row fixture.
    row.retrieval_version = 1
    row.retrieval_commit_watermark = 1
    assert chunk.normalized_text == expected
    assert row.normalized_text == expected
    assert projection_item(row).text == expected
    assert chunk.token_estimate == estimate_tokens(expected)
    assert chunk.metadata == metadata
    assert row.metadata_json == metadata
    assert chunk.metadata["source_refs"] == source_refs
    assert "Retrieval hints:" in document_chunk_retrieval_text(
        text=body, title=title, metadata=metadata
    )
