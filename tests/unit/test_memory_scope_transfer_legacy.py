from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from memo_stack_core.domain.errors import MemoryValidationError
from memo_stack_server.memory_scope_transfer_context import remap_context_link_suggestion
from memo_stack_server.memory_scope_transfer_records import (
    anchor_from_json,
    anchor_to_json,
    source_ref_from_json,
    source_ref_to_json,
)
from memo_stack_server.memory_scope_transfer_relations import relation_from_json, relation_to_json


def test_legacy_snapshot_anchor_defaults_new_lifecycle_fields() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    row = anchor_from_json(
        {
            "id": "anchor_legacy_acme",
            "kind": "organization",
            "normalized_key": "acme",
            "label": "Acme",
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
        },
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        now=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    )

    assert row.confidence == "medium"
    assert row.evidence_refs_json == []
    assert row.observed_at == created_at
    assert row.valid_from is None
    assert row.valid_to is None


def test_snapshot_anchor_evidence_refs_preserve_multimodal_fields() -> None:
    row = anchor_from_json(
        {
            "id": "anchor_multimodal_alex",
            "kind": "person",
            "normalized_key": "alex",
            "label": "Alex",
            "evidence_refs": [
                {
                    "source_type": "asset_extraction",
                    "source_id": "extract_1",
                    "chunk_id": "chunk_1",
                    "quote_preview": "Alex screenshot",
                    "page_number": 2,
                    "time_start_ms": 1000,
                    "time_end_ms": 1500,
                    "bbox": [0, 1, 120, 40],
                }
            ],
        },
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        now=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    )

    ref = row.evidence_refs_json[0]
    assert ref["page_number"] == 2
    assert ref["time_start_ms"] == 1000
    assert ref["time_end_ms"] == 1500
    assert ref["bbox"] == [0.0, 1.0, 120.0, 40.0]


def test_snapshot_source_ref_roundtrip_preserves_multimodal_fields() -> None:
    row = source_ref_from_json(
        {
            "fact_id": "fact_1",
            "fact_version": 1,
            "source_type": "asset_extraction",
            "source_id": "extract_1",
            "chunk_id": "chunk_1",
            "char_start": 10,
            "char_end": 40,
            "quote_preview": "Frame evidence",
            "page_number": 3,
            "time_start_ms": 2000,
            "time_end_ms": 2600,
            "bbox": [10, 20, 300, 180],
        }
    )

    exported = source_ref_to_json(row, redacted=False)

    assert row.page_number == 3
    assert row.time_start_ms == 2000
    assert row.time_end_ms == 2600
    assert row.bbox_json == [10.0, 20.0, 300.0, 180.0]
    assert exported["page_number"] == 3
    assert exported["time_start_ms"] == 2000
    assert exported["time_end_ms"] == 2600
    assert exported["bbox"] == [10.0, 20.0, 300.0, 180.0]


def test_snapshot_anchor_import_rejects_invalid_confidence() -> None:
    try:
        anchor_from_json(
            {
                "id": "anchor_invalid_confidence",
                "kind": "organization",
                "normalized_key": "acme",
                "label": "Acme",
                "confidence": "certain",
            },
            space_id="space_legacy",
            memory_scope_id="scope_legacy",
            now=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        )
    except MemoryValidationError as exc:
        assert "Unsupported anchor confidence" in str(exc)
    else:
        raise AssertionError("Expected invalid anchor confidence to fail")


def test_legacy_anchor_export_uses_created_at_when_observed_at_missing() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    exported = anchor_to_json(
        SimpleNamespace(
            id="anchor_legacy_acme",
            kind="organization",
            normalized_key="acme",
            label="Acme",
            aliases_json=[],
            description=None,
            status="active",
            confidence="medium",
            evidence_refs_json=[],
            observed_at=None,
            valid_from=None,
            valid_to=None,
            metadata_json={},
            created_at=created_at,
            updated_at=created_at,
        )
    )

    assert exported["observed_at"] == created_at.isoformat()
    assert exported["confidence"] == "medium"
    assert exported["evidence_refs"] == []


def test_legacy_snapshot_relation_defaults_temporal_fields() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    row = relation_from_json(
        {
            "id": "relation_legacy_supports",
            "source_fact_id": "fact_source",
            "target_fact_id": "fact_target",
            "relation_type": "supports",
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
        },
        space_id="space_legacy",
        memory_scope_id="scope_legacy",
        now=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
    )

    assert row.observed_at == created_at
    assert row.valid_from is None
    assert row.valid_to is None


def test_legacy_snapshot_context_link_suggestion_remaps_approved_override_metadata() -> None:
    mapped = remap_context_link_suggestion(
        {
            "id": "ctxlinksug_old",
            "source_type": "capture",
            "source_id": "capture_old",
            "target_type": "fact",
            "target_id": "fact_target_old",
            "metadata": {
                "approved_override": True,
                "original_target_type": "fact",
                "original_target_id": "fact_original_old",
                "approved_target_type": "anchor",
                "approved_target_id": "anchor_alex_old",
                "review_events": [
                    {
                        "suggestion_id": "ctxlinksug_old",
                        "action": "approve",
                        "source_type": "capture",
                        "source_id": "capture_old",
                        "target_type": "anchor",
                        "target_id": "anchor_alex_old",
                    },
                    "legacy_raw_event",
                ],
            },
        },
        context_link_suggestion_id_map={"ctxlinksug_old": "ctxlinksug_new"},
        fact_id_map={
            "fact_target_old": "fact_target_new",
            "fact_original_old": "fact_original_new",
        },
        document_id_map={},
        episode_id_map={},
        chunk_id_map={},
        capture_id_map={"capture_old": "capture_new"},
        asset_id_map={},
        anchor_id_map={"anchor_alex_old": "anchor_alex_new"},
        thread_id_map={},
        extraction_job_id_map={},
        extraction_artifact_id_map={},
    )

    assert mapped["id"] == "ctxlinksug_new"
    assert mapped["source_id"] == "capture_new"
    assert mapped["target_id"] == "fact_target_new"
    assert mapped["metadata_json"]["original_target_id"] == "fact_original_new"
    assert mapped["metadata_json"]["approved_target_id"] == "anchor_alex_new"

    review_events = mapped["metadata_json"]["review_events"]
    assert review_events[0]["suggestion_id"] == "ctxlinksug_new"
    assert review_events[0]["source_id"] == "capture_new"
    assert review_events[0]["target_id"] == "anchor_alex_new"
    assert review_events[1] == "legacy_raw_event"


def test_legacy_relation_export_uses_created_at_when_observed_at_missing() -> None:
    created_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    exported = relation_to_json(
        SimpleNamespace(
            id="relation_legacy_supports",
            source_fact_id="fact_source",
            target_fact_id="fact_target",
            relation_type="supports",
            reason="legacy relation",
            status="active",
            observed_at=None,
            valid_from=None,
            valid_to=None,
            created_at=created_at,
            updated_at=created_at,
        )
    )

    assert exported["observed_at"] == created_at.isoformat()
    assert exported["valid_from"] is None
    assert exported["valid_to"] is None


def test_snapshot_anchor_import_rejects_invalid_temporal_window() -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)

    try:
        anchor_from_json(
            {
                "id": "anchor_invalid_window",
                "kind": "organization",
                "normalized_key": "acme",
                "label": "Acme",
                "valid_from": "2026-02-01T00:00:00+00:00",
                "valid_to": "2026-01-01T00:00:00+00:00",
            },
            space_id="space_legacy",
            memory_scope_id="scope_legacy",
            now=now,
        )
    except MemoryValidationError as exc:
        assert "valid_to must be after valid_from" in str(exc)
    else:
        raise AssertionError("Expected invalid anchor temporal window to fail")


def test_snapshot_relation_import_rejects_invalid_temporal_window() -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)

    try:
        relation_from_json(
            {
                "id": "relation_invalid_window",
                "source_fact_id": "fact_source",
                "target_fact_id": "fact_target",
                "relation_type": "supersedes",
                "valid_from": "2026-02-01T00:00:00+00:00",
                "valid_to": "2026-01-01T00:00:00+00:00",
            },
            space_id="space_legacy",
            memory_scope_id="scope_legacy",
            now=now,
        )
    except MemoryValidationError as exc:
        assert "valid_to must be after valid_from" in str(exc)
    else:
        raise AssertionError("Expected invalid relation temporal window to fail")
