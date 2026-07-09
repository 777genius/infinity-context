from __future__ import annotations

import json

from infinity_context_contracts.features import memory_facts
from infinity_context_contracts.features.memory_facts import (
    FEATURE_ID,
    ForgetFactPathParamsDto,
    ForgetFactResultDto,
    MemoryFactIdentityDto,
    MemoryFactReadDto,
    MemoryFactSourceRefDto,
    MemoryFactVisibilityDto,
    RememberFactRequestDto,
    RememberFactResultDto,
    UpdateFactRequestDto,
    UpdateFactResultDto,
)


def test_memory_facts_feature_module_is_publicly_importable() -> None:
    assert memory_facts.FEATURE_ID == "memory_facts"
    assert FEATURE_ID == "memory_facts"
    assert "MemoryFactReadDto" in memory_facts.__all__


def test_memory_fact_read_contract_serializes_to_current_public_shape() -> None:
    fact = MemoryFactReadDto(
        identity=MemoryFactIdentityDto(
            id="fact_1",
            space_id="space_client_app",
            memory_scope_id="memory_scope_default",
            thread_id="thread_1",
        ),
        text="Postgres is canonical truth.",
        kind="architecture_decision",
        visibility=MemoryFactVisibilityDto(
            status="active",
            version=2,
            confidence="high",
            trust_level="medium",
            classification="internal",
            ttl_policy="keep",
            expires_at=None,
        ),
        category="architecture",
        tags=("canonical", "postgres"),
        source_refs=(
            MemoryFactSourceRefDto(
                source_type="manual",
                source_id="manual_1",
                chunk_id="chunk_1",
                char_start=4,
                char_end=28,
                quote_preview="Postgres canonical truth",
                page_number=2,
                time_start_ms=1000,
                time_end_ms=1500,
                bbox=(0, 1, 120, 40),
            ),
        ),
        created_at="2026-07-05T00:00:00+00:00",
        updated_at="2026-07-05T00:01:00+00:00",
        indexing_status="queued",
    )

    payload = fact.to_dict()

    assert payload == {
        "id": "fact_1",
        "space_id": "space_client_app",
        "memory_scope_id": "memory_scope_default",
        "thread_id": "thread_1",
        "text": "Postgres is canonical truth.",
        "kind": "architecture_decision",
        "status": "active",
        "version": 2,
        "confidence": "high",
        "trust_level": "medium",
        "classification": "internal",
        "ttl_policy": "keep",
        "expires_at": None,
        "category": "architecture",
        "tags": ["canonical", "postgres"],
        "source_refs": [
            {
                "source_type": "manual",
                "source_id": "manual_1",
                "chunk_id": "chunk_1",
                "char_start": 4,
                "char_end": 28,
                "quote_preview": "Postgres canonical truth",
                "page_number": 2,
                "time_start_ms": 1000,
                "time_end_ms": 1500,
                "bbox": [0, 1, 120, 40],
            }
        ],
        "created_at": "2026-07-05T00:00:00+00:00",
        "updated_at": "2026-07-05T00:01:00+00:00",
        "indexing_status": "queued",
    }
    json.dumps(payload, sort_keys=True)


def test_memory_fact_mutation_contracts_serialize_to_plain_json_dicts() -> None:
    source_ref = MemoryFactSourceRefDto(source_type="manual", source_id="manual_1")
    fact = MemoryFactReadDto(
        identity=MemoryFactIdentityDto(
            id="fact_1",
            space_id="space_client_app",
            memory_scope_id="memory_scope_default",
        ),
        text="Remembered fact.",
        source_refs=(source_ref,),
    )

    remember = RememberFactRequestDto(
        space_slug="agents",
        memory_scope_external_ref="backend-team",
        text="Remembered fact.",
        kind="note",
        source_refs=(source_ref,),
        tags=("manual",),
    )
    update = UpdateFactRequestDto(
        expected_version=1,
        text="Updated fact.",
        reason="corrected wording",
        source_refs=({"source_type": "manual", "source_id": "manual_2"},),
    )
    forget_path = ForgetFactPathParamsDto(fact_id="fact_1")

    assert remember.to_dict()["source_refs"] == [
        {
            "source_type": "manual",
            "source_id": "manual_1",
            "chunk_id": None,
            "char_start": None,
            "char_end": None,
            "quote_preview": None,
            "page_number": None,
            "time_start_ms": None,
            "time_end_ms": None,
            "bbox": None,
        }
    ]
    assert remember.to_dict()["tags"] == ["manual"]
    assert update.to_dict() == {
        "expected_version": 1,
        "text": "Updated fact.",
        "reason": "corrected wording",
        "source_refs": [{"source_type": "manual", "source_id": "manual_2"}],
    }
    assert forget_path.to_path_params() == {"fact_id": "fact_1"}
    assert not hasattr(forget_path, "to_dict")

    for result in (
        RememberFactResultDto(fact=fact),
        UpdateFactResultDto(fact=fact),
        ForgetFactResultDto(fact=fact),
    ):
        payload = result.to_dict()
        assert payload["data"]["id"] == "fact_1"
        json.dumps(payload, sort_keys=True)
