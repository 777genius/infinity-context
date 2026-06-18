from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from memo_stack_adapters.postgres.mappers import (
    anchor_row_to_domain,
    fact_relation_row_to_domain,
    fact_row_to_domain,
    source_ref_row_to_domain,
)
from memo_stack_core.domain.entities import Confidence, FactStatus, TrustLevel


def test_anchor_row_to_domain_defaults_missing_lifecycle_fields() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id="anchor_legacy_openai",
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        kind="organization",
        normalized_key="openai",
        label="OpenAI",
        aliases_json=["Open AI"],
        description=None,
        status="active",
        metadata_json={},
        created_at=created_at,
        updated_at=created_at,
    )

    anchor = anchor_row_to_domain(row)

    assert anchor.confidence == Confidence.MEDIUM
    assert anchor.evidence_refs == ()
    assert anchor.observed_at == created_at
    assert anchor.valid_from is None
    assert anchor.valid_to is None


def test_fact_relation_row_to_domain_defaults_missing_temporal_fields() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id="relation_legacy_supports",
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        source_fact_id="fact_source",
        target_fact_id="fact_target",
        relation_type="supports",
        reason="legacy relation",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )

    relation = fact_relation_row_to_domain(row)

    assert relation.observed_at == created_at
    assert relation.valid_from is None
    assert relation.valid_to is None


def test_fact_row_to_domain_defaults_missing_policy_fields() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id="fact_legacy_policy_defaults",
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        kind="note",
        text="Legacy fact without new policy columns.",
        created_at=created_at,
        updated_at=created_at,
    )

    fact = fact_row_to_domain(row, source_refs=[])

    assert fact.thread_id is None
    assert fact.status == FactStatus.ACTIVE
    assert fact.version == 1
    assert fact.confidence == Confidence.MEDIUM
    assert fact.trust_level == TrustLevel.MEDIUM
    assert fact.classification == "internal"
    assert fact.category is None
    assert fact.tags == ()
    assert fact.ttl_policy is None
    assert fact.expires_at is None


def test_source_ref_row_to_domain_preserves_multimodal_fields() -> None:
    row = SimpleNamespace(
        source_type="asset_extraction",
        source_id="extract_1",
        chunk_id="chunk_1",
        char_start=10,
        char_end=40,
        quote_preview="Screenshot text",
        page_number=2,
        time_start_ms=1000,
        time_end_ms=1500,
        bbox_json=[0, 1, 120, 40],
    )

    ref = source_ref_row_to_domain(row)

    assert ref.page_number == 2
    assert ref.time_start_ms == 1000
    assert ref.time_end_ms == 1500
    assert ref.bbox == (0.0, 1.0, 120.0, 40.0)
