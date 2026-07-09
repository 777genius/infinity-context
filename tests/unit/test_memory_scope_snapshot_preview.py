from __future__ import annotations

from infinity_context_core.memory_scope_snapshot_preview import (
    build_memory_scope_snapshot_import_preview,
)


def test_memory_scope_snapshot_import_preview_reports_skip_and_supersede() -> None:
    payload = {
        "schema_version": 9,
        "threads": [
            {"id": "thread_keep", "external_ref": "thread-keep"},
            {"id": "thread_conflict", "external_ref": "thread-conflict"},
        ],
        "facts": [{"id": "fact_keep"}, {"id": "fact_conflict"}],
        "documents": [{"id": "doc_conflict"}],
        "episodes": [{"id": "episode_keep", "thread_id": "thread_keep"}],
        "chunks": [
            {"id": "chunk_keep", "document_id": "doc_conflict"},
            {"id": "chunk_episode_keep", "episode_id": "episode_keep"},
            {"id": "chunk_orphan", "document_id": "missing_doc"},
        ],
        "assets": [
            {"id": "asset_keep", "status": "stored"},
            {"id": "asset_missing_blob", "status": "stored"},
        ],
        "asset_blobs": [{"asset_id": "asset_keep"}],
        "asset_extraction_jobs": [
            {"id": "job_keep", "asset_id": "asset_keep"},
            {"id": "job_asset_skip", "asset_id": "asset_missing_blob"},
        ],
        "extraction_artifacts": [
            {"id": "artifact_keep", "job_id": "job_keep", "asset_id": "asset_keep"},
            {"id": "artifact_missing_blob", "job_id": "job_keep", "asset_id": "asset_keep"},
            {
                "id": "artifact_job_skip",
                "job_id": "job_asset_skip",
                "asset_id": "asset_missing_blob",
            },
        ],
        "extraction_artifact_blobs": [{"artifact_id": "artifact_keep"}],
        "captures": [{"id": "capture_keep"}, {"id": "capture_conflict"}],
        "anchors": [
            {"id": "anchor_keep", "kind": "person", "normalized_key": "alex"},
            {"id": "anchor_conflict", "kind": "project", "normalized_key": "atlas"},
        ],
        "context_links": [
            {
                "id": "context_link_keep",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "anchor",
                "target_id": "anchor_keep",
                "relation_type": "mentions",
            },
            {
                "id": "context_link_asset_keep",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "asset",
                "target_id": "asset_keep",
                "relation_type": "mentions",
            },
            {
                "id": "context_link_job_keep",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "asset_extraction",
                "target_id": "job_keep",
                "relation_type": "created",
            },
            {
                "id": "context_link_artifact_keep",
                "source_type": "asset_extraction",
                "source_id": "job_keep",
                "target_type": "extraction_artifact",
                "target_id": "artifact_keep",
                "relation_type": "created",
            },
            {
                "id": "context_link_anchor_skip",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "anchor",
                "target_id": "anchor_conflict",
                "relation_type": "mentions",
            },
            {
                "id": "context_link_asset_skip",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "asset",
                "target_id": "asset_missing_blob",
                "relation_type": "mentions",
            },
            {
                "id": "context_link_thread_keep",
                "source_type": "thread",
                "source_id": "thread_keep",
                "target_type": "anchor",
                "target_id": "anchor_keep",
                "relation_type": "mentions",
            },
            {
                "id": "context_link_thread_missing_skip",
                "source_type": "thread",
                "source_id": "thread_missing",
                "target_type": "anchor",
                "target_id": "anchor_keep",
                "relation_type": "mentions",
            },
        ],
        "context_link_suggestions": [
            {
                "id": "context_link_suggestion_keep",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "anchor",
                "target_id": "anchor_keep",
                "relation_type": "related_to",
                "status": "pending",
            },
            {
                "id": "context_link_suggestion_thread_keep",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "thread",
                "target_id": "thread_keep",
                "relation_type": "related_to",
                "status": "pending",
            },
            {
                "id": "context_link_suggestion_conflict",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "anchor",
                "target_id": "anchor_keep",
                "relation_type": "related_to",
                "status": "pending",
            },
            {
                "id": "context_link_suggestion_anchor_skip",
                "source_type": "capture",
                "source_id": "capture_keep",
                "target_type": "anchor",
                "target_id": "anchor_conflict",
                "relation_type": "related_to",
                "status": "pending",
            },
        ],
        "relations": [
            {
                "id": "relation_keep",
                "source_fact_id": "fact_keep",
                "target_fact_id": "fact_conflict",
                "relation_type": "supports",
            }
        ],
        "source_refs": [
            {"fact_id": "fact_keep", "chunk_id": "chunk_keep"},
            {"fact_id": "fact_keep", "chunk_id": "chunk_episode_keep"},
            {"fact_id": "fact_conflict", "chunk_id": "chunk_orphan"},
        ],
    }

    skip_preview = build_memory_scope_snapshot_import_preview(
        payload=payload,
        merge_strategy="skip_existing",
        conflict_ids={
            "fact_conflict",
            "doc_conflict",
            "capture_conflict",
            "anchor_conflict",
            "thread_conflict",
            "context_link_suggestion_conflict",
        },
    )
    supersede_preview = build_memory_scope_snapshot_import_preview(
        payload=payload,
        merge_strategy="supersede_matching_facts",
        conflict_ids={"fact_conflict"},
    )

    assert skip_preview["snapshot_counts"] == {
        "threads": 2,
        "facts": 2,
        "documents": 1,
        "episodes": 1,
        "chunks": 3,
        "assets": 2,
        "asset_blobs": 1,
        "asset_extraction_jobs": 2,
        "extraction_artifacts": 3,
        "extraction_artifact_blobs": 1,
        "captures": 2,
        "anchors": 2,
        "context_links": 8,
        "context_link_suggestions": 4,
        "relations": 1,
        "source_refs": 3,
    }
    assert skip_preview["conflicts"]["facts"] == ["fact_conflict"]
    assert skip_preview["conflicts"]["documents"] == ["doc_conflict"]
    assert skip_preview["conflicts"]["captures"] == ["capture_conflict"]
    assert skip_preview["conflicts"]["anchors"] == ["anchor_conflict"]
    assert skip_preview["conflicts"]["threads"] == ["thread_conflict"]
    assert skip_preview["conflicts"]["context_link_suggestions"] == [
        "context_link_suggestion_conflict"
    ]
    assert skip_preview["would_skip"] == {
        "threads": 1,
        "facts": 1,
        "documents": 1,
        "episodes": 0,
        "chunks": 2,
        "assets": 1,
        "asset_extraction_jobs": 1,
        "extraction_artifacts": 2,
        "captures": 1,
        "anchors": 1,
        "context_links": 3,
        "context_link_suggestions": 2,
        "relations": 1,
        "source_refs": 2,
    }
    assert skip_preview["would_import"] == {
        "threads": 1,
        "facts": 1,
        "documents": 0,
        "episodes": 1,
        "chunks": 1,
        "assets": 1,
        "asset_extraction_jobs": 1,
        "extraction_artifacts": 1,
        "captures": 1,
        "anchors": 1,
        "context_links": 5,
        "context_link_suggestions": 2,
        "relations": 0,
        "source_refs": 1,
    }
    assert "some_chunks_will_be_skipped" in skip_preview["warnings"]
    assert "some_assets_will_be_skipped" in skip_preview["warnings"]
    assert "some_asset_extraction_jobs_will_be_skipped" in skip_preview["warnings"]
    assert "some_extraction_artifacts_will_be_skipped" in skip_preview["warnings"]
    assert "some_relations_will_be_skipped" in skip_preview["warnings"]
    assert "some_context_links_will_be_skipped" in skip_preview["warnings"]
    assert "some_context_link_suggestions_will_be_skipped" in skip_preview["warnings"]
    assert "some_threads_will_be_skipped" in skip_preview["warnings"]
    assert supersede_preview["would_supersede"] == {
        "facts": 1,
        "fact_ids": ["fact_conflict"],
    }
    assert supersede_preview["would_import"]["relations"] == 1


def test_memory_scope_snapshot_import_preview_reports_legacy_defaults() -> None:
    payload = {
        "schema_version": 7,
        "facts": [{"id": "fact_source"}, {"id": "fact_target"}],
        "anchors": [
            {
                "id": "anchor_legacy_alex",
                "kind": "person",
                "normalized_key": "alex",
                "label": "Alex bearer-token should not leak",
            },
            {
                "id": "anchor_current_acme",
                "kind": "organization",
                "normalized_key": "acme",
                "label": "Acme",
                "confidence": "medium",
                "evidence_refs": [],
                "observed_at": "2026-06-18T10:00:00+00:00",
                "valid_from": None,
                "valid_to": None,
            },
        ],
        "relations": [
            {
                "id": "relation_legacy",
                "source_fact_id": "fact_source",
                "target_fact_id": "fact_target",
                "relation_type": "supports",
            },
            {
                "id": "relation_current",
                "source_fact_id": "fact_target",
                "target_fact_id": "fact_source",
                "relation_type": "related_to",
                "observed_at": "2026-06-18T10:00:00+00:00",
                "valid_from": None,
                "valid_to": None,
            },
        ],
    }

    preview = build_memory_scope_snapshot_import_preview(
        payload=payload,
        merge_strategy="skip_existing",
        conflict_ids=set(),
    )

    assert preview["diagnostics"] == {
        "migration_defaults_applied": {
            "anchor_confidence": 1,
            "anchor_evidence_refs": 1,
            "anchor_observed_at": 1,
            "anchor_valid_from": 1,
            "anchor_valid_to": 1,
            "relation_observed_at": 1,
            "relation_valid_from": 1,
            "relation_valid_to": 1,
        },
        "migration_defaults_applied_count": 8,
    }
    assert preview["warnings"] == [
        "migration_defaults_applied.anchor_confidence",
        "migration_defaults_applied.anchor_evidence_refs",
        "migration_defaults_applied.anchor_observed_at",
        "migration_defaults_applied.anchor_valid_from",
        "migration_defaults_applied.anchor_valid_to",
        "migration_defaults_applied.relation_observed_at",
        "migration_defaults_applied.relation_valid_from",
        "migration_defaults_applied.relation_valid_to",
    ]
    assert "bearer-token" not in repr(preview["diagnostics"])
    assert "bearer-token" not in repr(preview["warnings"])


def test_memory_scope_snapshot_import_preview_warns_on_redacted_blocking_conflict() -> None:
    preview = build_memory_scope_snapshot_import_preview(
        payload={"redacted": True, "facts": [{"id": "fact_1"}]},
        merge_strategy="fail_on_conflict",
        conflict_ids={"fact_1"},
    )

    assert preview["conflict_count"] == 1
    assert preview["would_skip"]["facts"] == 0
    assert preview["warnings"] == [
        "redacted_snapshot_cannot_be_applied",
        "conflicts_block_import",
    ]
