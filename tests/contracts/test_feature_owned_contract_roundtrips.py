from __future__ import annotations

import json

from infinity_context_contracts.features import (
    context_building,
    document_ingestion,
    memory_facts,
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
from infinity_context_contracts.features.memory_facts import (
    MemoryFactSourceRefDto,
    RememberFactRequestDto,
    UpdateFactRequestDto,
)
from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
    MemoryScopeActorDto,
    MemoryScopeDescriptorDto,
    MemoryScopeOwnerDto,
    ScopeIdentityDto,
    TransferMemoryScopeOwnershipRequestDto,
    TransferMemoryScopeOwnershipResultDto,
)


def test_feature_package_public_exports_include_owned_contract_modules() -> None:
    assert context_building.__name__.endswith(".context_building")
    assert document_ingestion.__name__.endswith(".document_ingestion")
    assert memory_facts.__name__.endswith(".memory_facts")
    assert memory_scopes.__name__.endswith(".memory_scopes")


def test_context_building_dtos_roundtrip_to_plain_json_payloads() -> None:
    budget = ContextBudgetDto(max_context_tokens=2048, max_items=8)
    evidence = ContextEvidenceDto(
        source_type="document",
        source_id="doc_1",
        document_id="doc_1",
        chunk_id="chunk_1",
        quote_preview="Evidence stays evidence.",
        char_start=4,
        char_end=26,
        page_number=3,
        time_start_ms=100,
        time_end_ms=250,
        bbox=(1.0, 2.0, 30.0, 40.0),
        occurred_at="2026-07-05T00:00:00+00:00",
        score=0.82,
    )
    item = ContextItemDto(
        id="ctx_1",
        text="Evidence stays evidence.",
        kind="document_chunk",
        evidence=(evidence,),
        metadata={"labels": ("canonical", "prompt")},
    )
    request = BuildContextRequestDto(
        query="What is rendered?",
        space_id="space_1",
        memory_scope_ids=("scope_1", "scope_2"),
        budget=budget,
        token_budget=2048,
        max_facts=6,
        max_chunks=9,
        max_evidence_items=8,
        consistency_mode="best_effort",
        max_conflicting_suggestions=2,
        include_superseded=True,
        category="architecture",
        tags_any=("postgres",),
        tags_all=("canonical",),
        tags_none=("deprecated",),
        include_kinds=("document_chunk",),
        include_diagnostics=True,
    )
    result = BuildContextResultDto(items=(item,), budget=budget, diagnostics={"ok": True})

    assert _json_roundtrip(request.to_dict()) == request.to_dict()
    assert request.to_dict()["memory_scope_ids"] == ["scope_1", "scope_2"]
    assert request.to_dict()["token_budget"] == 2048
    assert request.to_dict()["tags_any"] == ["postgres"]
    assert _json_roundtrip(result.to_dict()) == result.to_dict()
    assert result.to_dict()["data"]["items"][0]["evidence"][0]["bbox"] == [
        1.0,
        2.0,
        30.0,
        40.0,
    ]


def test_document_ingestion_dtos_roundtrip_to_plain_json_payloads() -> None:
    source = DocumentSourceDto(
        source_type="file",
        source_external_id="notes/architecture.md",
        source_uri="file:///notes/architecture.md",
        classification="internal",
    )
    document = MemoryDocumentDto(
        identity=DocumentIdentityDto(
            id="doc_1",
            space_id="space_1",
            memory_scope_id="scope_1",
        ),
        title="Architecture",
        source=source,
        source_uri=source.source_uri,
        classification=source.classification,
    )
    chunk = DocumentChunkDto(
        id="chunk_1",
        document_id="doc_1",
        chunk_index=0,
        text="Postgres owns canonical lifecycle.",
    )
    request = IngestDocumentRequestDto(
        text="Postgres owns canonical lifecycle.",
        title="Architecture",
        source_type=source.source_type,
        source_external_id=source.source_external_id,
        source_uri=source.source_uri,
        classification=source.classification,
    )
    result = IngestDocumentResultDto(document=document, chunks=(chunk,))

    assert _json_roundtrip(source.to_dict()) == source.to_dict()
    assert _json_roundtrip(request.to_dict()) == request.to_dict()
    assert _json_roundtrip(result.to_dict()) == result.to_dict()


def test_memory_fact_request_dtos_roundtrip_to_plain_json_payloads() -> None:
    source_ref = MemoryFactSourceRefDto(
        source_type="manual",
        source_id="note_1",
        quote_preview="Fact evidence remains evidence.",
    )
    remember_request = RememberFactRequestDto(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        text="Postgres owns canonical memory fact lifecycle.",
        kind="architecture_decision",
        source_refs=(source_ref,),
        classification="internal",
        category="architecture",
        tags=("postgres", "canonical"),
        ttl_policy="durable",
    )
    update_request = UpdateFactRequestDto(
        expected_version=2,
        text="Postgres remains canonical memory fact lifecycle.",
        reason="tighten wording",
        source_refs=(source_ref,),
    )

    assert _json_roundtrip(remember_request.to_dict()) == remember_request.to_dict()
    assert _json_roundtrip(update_request.to_dict()) == update_request.to_dict()


def test_memory_scope_owner_actor_and_transfer_contracts_roundtrip() -> None:
    owner = MemoryScopeOwnerDto(principal_id="user_1")
    actor = MemoryScopeActorDto(
        principal_id="admin_1",
        capabilities=("memory_scope.transfer",),
    )
    new_owner = MemoryScopeOwnerDto(principal_id="team_1", principal_kind="team")
    scope = MemoryScopeDescriptorDto(
        identity=ScopeIdentityDto(
            id="scope_1",
            space_id="space_1",
            external_ref="default",
        ),
        name="Default",
        owner=new_owner,
    )
    create_request = CreateMemoryScopeRequestDto(
        external_ref="default",
        name="Default",
        owner=owner,
        space_id="space_1",
    )
    transfer_request = TransferMemoryScopeOwnershipRequestDto(
        space_id="space_1",
        memory_scope_id="scope_1",
        new_owner=new_owner,
        initiated_by=actor,
        expected_current_owner=owner,
    )
    transfer_result = TransferMemoryScopeOwnershipResultDto(
        scope=scope,
        previous_owner=owner,
    )

    assert _json_roundtrip(create_request.to_dict()) == create_request.to_dict()
    assert _json_roundtrip(transfer_request.to_dict()) == transfer_request.to_dict()
    assert _json_roundtrip(transfer_result.to_dict()) == transfer_result.to_dict()


def test_feature_modules_export_all_public_dtos() -> None:
    assert {
        "BuildContextRequestDto",
        "BuildContextResultDto",
        "ContextBudgetDto",
        "ContextEvidenceDto",
        "ContextItemDto",
    } <= set(context_building.__all__)
    assert {
        "DocumentChunkDto",
        "DocumentIdentityDto",
        "DocumentSourceDto",
        "IngestDocumentRequestDto",
        "IngestDocumentResultDto",
        "MemoryDocumentDto",
    } <= set(document_ingestion.__all__)
    assert {
        "MemoryFactSourceRefDto",
        "RememberFactRequestDto",
        "UpdateFactRequestDto",
    } <= set(memory_facts.__all__)
    assert {
        "MemoryScopeActorDto",
        "MemoryScopeOwnerDto",
        "TransferMemoryScopeOwnershipRequestDto",
        "TransferMemoryScopeOwnershipResultDto",
    } <= set(memory_scopes.__all__)


def _json_roundtrip(payload: object) -> object:
    return json.loads(json.dumps(payload, sort_keys=True))
