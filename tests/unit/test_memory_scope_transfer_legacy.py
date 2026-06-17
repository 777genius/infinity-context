from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from memo_stack_server.memory_scope_transfer_records import anchor_from_json, anchor_to_json
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
