from __future__ import annotations

import json

from infinity_context_contracts.features import (
    context_building,
    document_ingestion,
    memory_scopes,
)
from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    BuildContextResultDto,
    ContextBudgetDto,
    ContextEvidenceDto,
    ContextItemDto,
)
from infinity_context_contracts.features.document_ingestion import (
    DocumentChunkDto,
    DocumentIdentityDto,
    DocumentSourceDto,
    IngestDocumentRequestDto,
    IngestDocumentResultDto,
    MemoryDocumentDto,
)
from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
    CreateMemoryScopeResultDto,
    MemoryScopeActorDto,
    MemoryScopeDescriptorDto,
    MemoryScopeOwnerDto,
    ScopeIdentityDto,
    TransferMemoryScopeOwnershipRequestDto,
    TransferMemoryScopeOwnershipResultDto,
    TransferMemoryScopeRequestDto,
    TransferMemoryScopeResultDto,
)


def test_non_memory_feature_mirror_modules_are_publicly_importable() -> None:
    assert context_building.FEATURE_ID == "context_building"
    assert document_ingestion.FEATURE_ID == "document_ingestion"
    assert memory_scopes.FEATURE_ID == "memory_scopes"
    assert "ContextItemDto" in context_building.__all__
    assert "DocumentSourceDto" in document_ingestion.__all__
    assert "MemoryScopeOwnerDto" in memory_scopes.__all__


def test_context_building_contracts_serialize_to_plain_json_dicts() -> None:
    budget = ContextBudgetDto(
        max_context_tokens=1200,
        reserved_response_tokens=300,
        max_items=4,
        strategy="evidence_first",
    )
    evidence = ContextEvidenceDto(
        source_type="document",
        source_id="doc_1",
        document_id="doc_1",
        chunk_id="chunk_1",
        quote_preview="Postgres owns canonical lifecycle.",
        char_start=0,
        char_end=36,
        page_number=2,
        bbox=(0.0, 1.0, 120.0, 40.0),
        score=0.91,
        trust_level="high",
        metadata={"page": 2},
    )
    item = ContextItemDto(
        id="ctx_1",
        text="Postgres owns canonical lifecycle.",
        kind="document_chunk",
        evidence=(evidence,),
        score=0.91,
        token_count=12,
        trust_level="high",
        metadata={"rank": 1},
    )
    request = BuildContextRequestDto(
        query="What owns canonical lifecycle?",
        space_slug="client-app",
        memory_scope_external_refs=("default", "candidate"),
        thread_external_ref="session_1",
        budget=budget,
        token_budget=1200,
        max_facts=4,
        max_chunks=6,
        max_evidence_items=5,
        consistency_mode="canonical_only",
        max_conflicting_suggestions=2,
        include_stale=True,
        category="architecture",
        tags_any=("postgres",),
        tags_all=("canonical",),
        tags_none=("deprecated",),
        include_kinds=("fact", "document_chunk"),
        tags=("architecture",),
        policy_mode="active_context",
        include_diagnostics=True,
    )
    result = BuildContextResultDto(
        items=(item,),
        rendered_context="[1] Postgres owns canonical lifecycle.",
        budget=budget,
        total_tokens=12,
        diagnostics={"dropped_items": 0},
        built_at="2026-07-05T00:00:00+00:00",
    )

    assert request.to_dict() == {
        "query": "What owns canonical lifecycle?",
        "space_id": None,
        "memory_scope_id": None,
        "memory_scope_ids": [],
        "thread_id": None,
        "space_slug": "client-app",
        "memory_scope_external_ref": None,
        "memory_scope_external_refs": ["default", "candidate"],
        "thread_external_ref": "session_1",
        "budget": {
            "max_context_tokens": 1200,
            "reserved_response_tokens": 300,
            "max_items": 4,
            "strategy": "evidence_first",
        },
        "token_budget": 1200,
        "max_facts": 4,
        "max_chunks": 6,
        "max_evidence_items": 5,
        "consistency_mode": "canonical_only",
        "max_conflicting_suggestions": 2,
        "include_superseded": False,
        "include_stale": True,
        "category": "architecture",
        "tags_any": ["postgres"],
        "tags_all": ["canonical"],
        "tags_none": ["deprecated"],
        "include_kinds": ["fact", "document_chunk"],
        "tags": ["architecture"],
        "policy_mode": "active_context",
        "include_diagnostics": True,
        "metadata": {},
    }
    assert result.to_dict()["data"]["items"][0]["evidence"][0] == {
        "source_type": "document",
        "source_id": "doc_1",
        "fact_id": None,
        "document_id": "doc_1",
        "chunk_id": "chunk_1",
        "quote_preview": "Postgres owns canonical lifecycle.",
        "char_start": 0,
        "char_end": 36,
        "page_number": 2,
        "time_start_ms": None,
        "time_end_ms": None,
        "bbox": [0.0, 1.0, 120.0, 40.0],
        "occurred_at": None,
        "score": 0.91,
        "trust_level": "high",
        "metadata": {"page": 2},
    }
    json.dumps(result.to_dict(), sort_keys=True)


def test_document_ingestion_contracts_serialize_to_plain_json_dicts() -> None:
    source = DocumentSourceDto(
        source_type="document",
        source_external_id="architecture-notes",
        source_uri="file:///notes/architecture.md",
        classification="internal",
    )
    document = MemoryDocumentDto(
        identity=DocumentIdentityDto(
            id="doc_1",
            space_id="space_client_app",
            memory_scope_id="memory_scope_default",
            thread_id="thread_1",
        ),
        title="Architecture Notes",
        source=source,
        source_uri="file:///notes/architecture.md",
        classification="internal",
        status="processed",
        content_hash="sha256:abc",
        metadata={"source": "manual"},
    )
    chunk = DocumentChunkDto(
        id="chunk_1",
        document_id="doc_1",
        chunk_index=0,
        text="Postgres is canonical truth.",
        char_start=0,
        char_end=28,
        token_count=5,
        content_hash="sha256:def",
    )
    request = IngestDocumentRequestDto(
        text="Postgres is canonical truth.",
        title="Architecture Notes",
        source_type="document",
        source_external_id="architecture-notes",
        source_uri="file:///notes/architecture.md",
        classification="internal",
        space_slug="client-app",
        memory_scope_external_ref="default",
        idempotency_key="ingest_1",
    )
    result = IngestDocumentResultDto(
        document=document,
        chunks=(chunk,),
        created=True,
        indexing_status="queued",
    )

    assert request.to_dict()["text"] == "Postgres is canonical truth."
    assert request.to_dict()["idempotency_key"] == "ingest_1"
    assert result.to_dict() == {
        "data": {
            "document": {
                "id": "doc_1",
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "thread_id": "thread_1",
                "title": "Architecture Notes",
                "source": {
                    "source_type": "document",
                    "source_external_id": "architecture-notes",
                    "source_uri": "file:///notes/architecture.md",
                    "media_type": "text/plain",
                    "classification": "internal",
                },
                "source_uri": "file:///notes/architecture.md",
                "media_type": "text/plain",
                "classification": "internal",
                "status": "processed",
                "content_hash": "sha256:abc",
                "created_at": None,
                "updated_at": None,
                "metadata": {"source": "manual"},
            },
            "chunks": [
                {
                    "id": "chunk_1",
                    "document_id": "doc_1",
                    "chunk_index": 0,
                    "text": "Postgres is canonical truth.",
                    "char_start": 0,
                    "char_end": 28,
                    "token_count": 5,
                    "content_hash": "sha256:def",
                    "metadata": {},
                }
            ],
            "created": True,
            "indexing_status": "queued",
        }
    }
    json.dumps(result.to_dict(), sort_keys=True)


def test_memory_scope_contracts_serialize_create_and_transfer_shapes() -> None:
    owner = MemoryScopeOwnerDto(principal_id="user_1")
    created_scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="memory_scope_default",
            space_id="space_client_app",
            external_ref="default",
        ),
        name="Default",
        owner=owner,
        description="Default client app memory scope.",
        policy_mode="manual_only",
        metadata={"owner": "client-app"},
    )
    transferred_scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="memory_scope_default",
            space_id="space_agents",
            external_ref="backend-team",
        ),
        name="Default",
        owner=MemoryScopeOwnerDto(principal_id="team_backend", principal_kind="team"),
        policy_mode="active_context",
    )
    create_request = CreateMemoryScopeRequestDto(
        space_slug="client-app",
        external_ref="default",
        name="Default",
        owner=owner,
        description="Default client app memory scope.",
        idempotency_key="scope_1",
    )
    transfer_request = TransferMemoryScopeRequestDto(
        scope_id="memory_scope_default",
        target_space_slug="agents",
        new_external_ref="backend-team",
        reason="move reusable project memory",
    )

    assert create_request.to_dict() == {
        "space_id": None,
        "space_slug": "client-app",
        "external_ref": "default",
        "name": "Default",
        "owner": {"principal_id": "user_1", "principal_kind": "user"},
        "description": "Default client app memory scope.",
        "policy_mode": "manual_only",
        "idempotency_key": "scope_1",
        "metadata": {},
    }
    assert transfer_request.to_dict()["target_space_slug"] == "agents"
    assert CreateMemoryScopeResultDto(scope=created_scope).to_dict()["data"] == {
        "scope": {
            "id": "memory_scope_default",
            "space_id": "space_client_app",
            "external_ref": "default",
            "name": "Default",
            "owner": {"principal_id": "user_1", "principal_kind": "user"},
            "description": "Default client app memory scope.",
            "status": "active",
            "policy_mode": "manual_only",
            "created_at": None,
            "updated_at": None,
            "metadata": {"owner": "client-app"},
        },
        "created": True,
    }
    assert TransferMemoryScopeResultDto(
        scope=transferred_scope,
        previous_space_id="space_client_app",
    ).to_dict()["data"]["previous_space_id"] == "space_client_app"
    json.dumps(CreateMemoryScopeResultDto(scope=created_scope).to_dict(), sort_keys=True)


def test_memory_scope_ownership_transfer_contract_serializes_public_shape() -> None:
    previous_owner = MemoryScopeOwnerDto(principal_id="user_1")
    new_owner = MemoryScopeOwnerDto(principal_id="team_backend", principal_kind="team")
    actor = MemoryScopeActorDto(
        principal_id="admin_1",
        capabilities=("memory_scope.transfer",),
    )
    scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="memory_scope_default",
            space_id="space_client_app",
            external_ref="default",
        ),
        name="Default",
        owner=new_owner,
    )
    request = TransferMemoryScopeOwnershipRequestDto(
        space_id="space_client_app",
        memory_scope_id="memory_scope_default",
        new_owner=new_owner,
        initiated_by=actor,
        expected_current_owner=previous_owner,
        reason="move reusable project memory",
        idempotency_key="transfer_owner_1",
    )
    result = TransferMemoryScopeOwnershipResultDto(
        scope=scope,
        previous_owner=previous_owner,
    )

    assert request.to_dict() == {
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "new_owner": {
            "principal_id": "team_backend",
            "principal_kind": "team",
        },
        "initiated_by": {
            "principal_id": "admin_1",
            "principal_kind": "user",
            "capabilities": ["memory_scope.transfer"],
        },
        "expected_current_owner": {
            "principal_id": "user_1",
            "principal_kind": "user",
        },
        "reason": "move reusable project memory",
        "idempotency_key": "transfer_owner_1",
        "metadata": {},
    }
    assert result.to_dict()["data"]["previous_owner"] == {
        "principal_id": "user_1",
        "principal_kind": "user",
    }
    json.dumps(result.to_dict(), sort_keys=True)
