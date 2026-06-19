import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import MemoryAnchorRow
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.main import create_app
from sqlalchemy.ext.asyncio import AsyncSession


def make_client(tmp_path: Path, **overrides: Any) -> TestClient:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            capture_mode=CaptureMode.SUGGEST,
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            asset_storage_dir=str(tmp_path / "assets"),
            **overrides,
        )
    )
    return TestClient(app)


def auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-token"}
    if extra:
        headers.update(extra)
    return headers


def overwrite_anchor_aliases(client: TestClient, anchor_id: str, aliases: list[str]) -> None:
    async def run() -> None:
        container = client.app.state.container
        async with AsyncSession(container.engine) as session:
            row = await session.get(MemoryAnchorRow, anchor_id)
            assert row is not None
            row.aliases_json = aliases
            await session.commit()

    asyncio.run(run())


def evidence_ref_identity(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": ref["source_type"],
        "source_id": ref["source_id"],
        "chunk_id": ref["chunk_id"],
        "char_start": ref["char_start"],
        "char_end": ref["char_end"],
        "quote_preview": ref["quote_preview"],
    }


def insert_legacy_anchor_row(client: TestClient, *, anchor_id: str, created_at: str) -> None:
    created = datetime.fromisoformat(created_at)

    async def run() -> None:
        container = client.app.state.container
        async with AsyncSession(container.engine) as session:
            session.add(
                MemoryAnchorRow(
                    id=anchor_id,
                    space_id="space_client_app",
                    memory_scope_id="memory_scope_default",
                    kind="organization",
                    normalized_key="legacy-openai",
                    label="Legacy OpenAI",
                    aliases_json=[],
                    description=None,
                    status="active",
                    confidence="medium",
                    evidence_refs_json=[],
                    observed_at=None,
                    valid_from=None,
                    valid_to=None,
                    metadata_json={},
                    created_at=created,
                    updated_at=created,
                )
            )
            await session.commit()

    asyncio.run(run())


def test_anchor_public_api_defaults_legacy_lifecycle_fields(tmp_path: Path) -> None:
    created_at = "2026-06-01T10:00:00+00:00"
    with make_client(tmp_path) as client:
        insert_legacy_anchor_row(
            client,
            anchor_id="anchor_legacy_openai_api",
            created_at=created_at,
        )
        listed = client.get(
            "/v1/anchors",
            params={
                "space_id": "space_client_app",
                "memory_scope_id": "memory_scope_default",
                "kind": "organization",
            },
            headers=auth_headers(),
        )

    assert listed.status_code == 200, listed.text
    anchors = listed.json()["data"]
    anchor = next(item for item in anchors if item["id"] == "anchor_legacy_openai_api")
    assert anchor["confidence"] == "medium"
    assert anchor["evidence_refs"] == []
    assert anchor["observed_at"] == created_at
    assert anchor["valid_from"] is None
    assert anchor["valid_to"] is None
    assert anchor["created_at"] == created_at
    assert anchor["updated_at"] == created_at


def test_manual_event_anchor_preserves_explicit_structured_metadata(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "manual-event-metadata",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-manual-event-metadata",
                "text": "Alex discussed Project Atlas billing on the call one hour ago.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        response = client.post(
            "/v1/anchors",
            json={
                "space_slug": "manual-event-metadata",
                "memory_scope_external_ref": "default",
                "kind": "event",
                "label": "Atlas billing call",
                "aliases": ["Project Atlas billing review"],
                "description": "Reviewer-confirmed event anchor.",
                "confidence": "high",
                "metadata": {
                    "anchor_family": "event",
                    "event_type": "call",
                    "event_type_canonical": "call",
                    "event_participant_label": "Alex",
                    "event_participant_relation": "with",
                    "event_participant_canonical_key": "alex",
                    "project_canonical_key": "atlas",
                    "event_temporal_phrase": "one hour ago",
                    "event_temporal_hint_code": "relative_recent",
                    "event_temporal_quantity": "1",
                    "event_temporal_unit": "hour",
                    "event_identity_terms": [
                        "alex",
                        "project atlas",
                        "billing",
                        "call",
                    ],
                },
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200, response.text
    metadata = response.json()["data"]["metadata"]
    assert metadata["event_type"] == "call"
    assert metadata["event_type_canonical"] == "call"
    assert metadata["event_participant_label"] == "Alex"
    assert metadata["event_temporal_phrase"] == "one hour ago"
    assert metadata["creation_source"] == "manual"
    assert metadata["resolver_version"] == "anchor-lifecycle-v2"


def test_anchor_backfill_merge_and_split_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-anchor-lifecycle",
                "text": "Alex shared Project Atlas notes from meeting last week.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "text": "Алекс confirmed Project Atlas priorities after the call yesterday.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "fact-alex"}],
            },
            headers=auth_headers({"Idempotency-Key": "fact-alex"}),
        )
        assert fact.status_code == 201, fact.text

        manual_anchor = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": ["Project Atlas"],
                "description": "Manual project anchor created by reviewer.",
                "confidence": "high",
                "evidence_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "manual-anchor-atlas",
                        "quote_preview": "Reviewer confirmed Atlas is the canonical project.",
                    }
                ],
                "observed_at": "2026-01-02T03:04:05+00:00",
                "valid_from": "2026-01-01T00:00:00+00:00",
                "valid_to": "2026-12-31T23:59:59+00:00",
            },
            headers=auth_headers(),
        )
        assert manual_anchor.status_code == 200, manual_anchor.text
        manual_anchor_data = manual_anchor.json()["data"]
        assert manual_anchor_data["kind"] == "project"
        assert manual_anchor_data["normalized_key"] == "atlas"
        assert "Project Atlas" in manual_anchor_data["aliases"]
        assert manual_anchor_data["confidence"] == "high"
        assert [
            evidence_ref_identity(ref) for ref in manual_anchor_data["evidence_refs"]
        ] == [
            {
                "source_type": "manual",
                "source_id": "manual-anchor-atlas",
                "chunk_id": None,
                "char_start": None,
                "char_end": None,
                "quote_preview": "Reviewer confirmed Atlas is the canonical project.",
            }
        ]
        assert manual_anchor_data["observed_at"] == "2026-01-02T03:04:05+00:00"
        assert manual_anchor_data["valid_from"] == "2026-01-01T00:00:00+00:00"
        assert manual_anchor_data["valid_to"] == "2026-12-31T23:59:59+00:00"
        assert manual_anchor_data["metadata"]["creation_source"] == "manual"

        manual_anchor_duplicate = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": ["Atlas roadmap"],
                "description": "Updated manual project anchor.",
            },
            headers=auth_headers(),
        )
        assert manual_anchor_duplicate.status_code == 200, manual_anchor_duplicate.text
        duplicate_data = manual_anchor_duplicate.json()["data"]
        assert duplicate_data["id"] == manual_anchor_data["id"]
        assert "Atlas roadmap" in duplicate_data["aliases"]
        assert duplicate_data["description"] == "Updated manual project anchor."
        assert duplicate_data["confidence"] == "high"
        assert duplicate_data["evidence_refs"]
        assert duplicate_data["observed_at"] == "2026-01-02T03:04:05+00:00"
        assert duplicate_data["valid_from"] == "2026-01-01T00:00:00+00:00"
        assert duplicate_data["valid_to"] == "2026-12-31T23:59:59+00:00"

        edited_anchor = client.patch(
            f"/v1/anchors/{manual_anchor_data['id']}",
            json={
                "label": "Atlas Roadmap",
                "aliases": ["Project Atlas", "Atlas delivery"],
                "description": "Edited manual project anchor.",
                "confidence": "medium",
                "evidence_refs": [
                    {
                        "source_type": "document",
                        "source_id": "atlas-roadmap-doc",
                        "chunk_id": "chunk-1",
                    }
                ],
                "observed_at": "2026-01-03T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        assert edited_anchor.status_code == 200, edited_anchor.text
        edited_data = edited_anchor.json()["data"]
        assert edited_data["id"] == manual_anchor_data["id"]
        assert edited_data["normalized_key"] == "atlas roadmap"
        assert "Atlas delivery" in edited_data["aliases"]
        assert edited_data["description"] == "Edited manual project anchor."
        assert edited_data["confidence"] == "high"
        assert {ref["source_id"] for ref in edited_data["evidence_refs"]} == {
            "manual-anchor-atlas",
            "atlas-roadmap-doc",
        }
        assert edited_data["observed_at"] == "2026-01-03T00:00:00+00:00"
        assert edited_data["metadata"]["last_edit_source"] == "manual"

        deleted_anchor = client.request(
            "DELETE",
            f"/v1/anchors/{manual_anchor_data['id']}",
            json={"reason": "obsolete manual project anchor"},
            headers=auth_headers(),
        )
        assert deleted_anchor.status_code == 200, deleted_anchor.text
        deleted_anchor_data = deleted_anchor.json()["data"]
        assert deleted_anchor_data["status"] == "deleted"
        assert deleted_anchor_data["metadata"]["delete_reason"] == "obsolete manual project anchor"

        document = client.post(
            "/v1/documents",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "atlas-thread",
                "title": "Atlas review notes",
                "text": "Project Atlas review mentions Alex and Qdrant document memory.",
                "source_type": "document",
                "source_external_id": "atlas-review-doc",
            },
            headers=auth_headers({"Idempotency-Key": "atlas-review-doc"}),
        )
        assert document.status_code == 201, document.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text
        backfill_data = backfill.json()["data"]
        assert backfill_data["created"] >= 4
        assert {item["source_type"] for item in backfill_data["sources"]} == {
            "capture",
            "fact",
            "chunk",
        }

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        active_anchors = anchors.json()["data"]
        keys = {(item["kind"], item["normalized_key"]) for item in active_anchors}
        assert ("person", "alex") in keys
        assert ("person", "алекс") in keys
        assert ("project", "atlas") in keys
        assert ("project", "atlas roadmap") not in keys
        assert ("event", "meeting last week") in keys
        alex_anchor = next(item for item in active_anchors if item["normalized_key"] == "alex")
        assert alex_anchor["confidence"] in {"high", "medium"}
        assert any(
            ref["source_type"] in {"capture", "fact"} for ref in alex_anchor["evidence_refs"]
        )

        merge_suggestions = client.get(
            "/v1/anchors/merge-suggestions",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "kind": "person",
            },
            headers=auth_headers(),
        )
        assert merge_suggestions.status_code == 200, merge_suggestions.text
        candidates = merge_suggestions.json()["data"]["candidates"]
        alex_candidate = next(
            candidate
            for candidate in candidates
            if {
                candidate["source_anchor"]["normalized_key"],
                candidate["target_anchor"]["normalized_key"],
            }
            == {"alex", "алекс"}
        )
        assert alex_candidate["confidence"] in {"high", "medium"}
        assert alex_candidate["score"] >= 78

        merged = client.post(
            f"/v1/anchors/{alex_candidate['source_anchor']['id']}/merge",
            json={
                "target_anchor_id": alex_candidate["target_anchor"]["id"],
                "reason": "same person confirmed by reviewer",
            },
            headers=auth_headers(),
        )
        assert merged.status_code == 200, merged.text
        merged_anchor = merged.json()["data"]
        assert {
            "Alex",
            "Алекс",
        }.issubset(set(merged_anchor["aliases"]))
        assert merged_anchor["metadata"]["merged_anchor_ids"]
        merge_event = merged_anchor["metadata"]["merge_events"][-1]
        assert merge_event["source_anchor_id"] == alex_candidate["source_anchor"]["id"]
        assert merge_event["reason"] == "same person confirmed by reviewer"
        assert merge_event["merged_at"]
        assert merged_anchor["evidence_refs"]

        deleted_source = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "status": "deleted",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert deleted_source.status_code == 200, deleted_source.text
        deleted = deleted_source.json()["data"]
        assert any(
            item["id"] == alex_candidate["source_anchor"]["id"]
            and item["metadata"]["merged_into_anchor_id"] == alex_candidate["target_anchor"]["id"]
            for item in deleted
        )

        split = client.post(
            f"/v1/anchors/{merged_anchor['id']}/split",
            json={
                "alias": "Алекс",
                "new_label": "Алексей",
                "reason": "reviewer split alias into a different person",
            },
            headers=auth_headers(),
        )
        assert split.status_code == 200, split.text
        split_anchor = split.json()["data"]
        assert split_anchor["normalized_key"] == "алексей"
        assert split_anchor["metadata"]["split_from_anchor_id"] == merged_anchor["id"]

        active_after_split = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-lifecycle",
                "memory_scope_external_ref": "default",
                "status": "active",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        by_id = {item["id"]: item for item in active_after_split.json()["data"]}
        parent_after_split = by_id[merged_anchor["id"]]
        assert "Алекс" not in parent_after_split["aliases"]
        split_event = parent_after_split["metadata"]["split_events"][-1]
        assert split_event["alias"] == "Алекс"
        assert split_event["reason"] == "reviewer split alias into a different person"
        assert split_event["split_at"]


def test_anchor_backfill_collapses_russian_person_case_variants(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-aleksom",
                "text": "Час назад я переписывался с Алексом по Project Atlas.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        fact = client.post(
            "/v1/facts",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "text": "Алекс подтвердил Project Atlas после переписки.",
                "kind": "note",
                "source_refs": [{"source_type": "manual", "source_id": "fact-alex"}],
            },
            headers=auth_headers({"Idempotency-Key": "fact-alex-case-variant"}),
        )
        assert fact.status_code == 201, fact.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "person",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        person_anchors = anchors.json()["data"]
        assert len(person_anchors) == 1
        assert person_anchors[0]["normalized_key"] == "алекс"
        assert person_anchors[0]["label"] == "Алекс"
        assert {"Алекс", "Алексом"}.issubset(set(person_anchors[0]["aliases"]))
        assert person_anchors[0]["metadata"]["canonical_key"] == "aleks"


def test_anchor_backfill_collapses_cross_script_project_identity(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        latin_capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-cross-script-project",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-project-atlas-latin",
                "text": "Project Atlas keeps Qdrant document retrieval notes.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert latin_capture.status_code == 201, latin_capture.text

        cyrillic_capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-cross-script-project",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-project-atlas-cyrillic",
                "text": "В проекте Атлас хранится заметка про документы.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert cyrillic_capture.status_code == 201, cyrillic_capture.text

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-cross-script-project",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-cross-script-project",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        atlas_anchors = [
            item
            for item in anchors.json()["data"]
            if item["metadata"].get("canonical_key") == "atlas"
        ]

        assert len(atlas_anchors) == 1
        assert atlas_anchors[0]["normalized_key"] in {"atlas", "атлас"}
        assert {"Atlas", "Атлас"}.issubset(set(atlas_anchors[0]["aliases"]))
        assert {
            ref["source_id"] for ref in atlas_anchors[0]["evidence_refs"]
        } == {
            latin_capture.json()["data"]["id"],
            cyrillic_capture.json()["data"]["id"],
        }


def test_anchor_backfill_skips_legacy_alias_conflict_without_mutating_anchor(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-backfill-legacy-alias-conflict",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-project-atlas-conflict",
                "text": "Project Atlas",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text
        capture_id = capture.json()["data"]["id"]

        canonical = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-backfill-legacy-alias-conflict",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Atlas",
                "aliases": ["Project Atlas"],
                "evidence_refs": [
                    {"source_type": "manual", "source_id": "canonical-atlas-review"}
                ],
            },
            headers=auth_headers(),
        )
        assert canonical.status_code == 200, canonical.text

        legacy_holder = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-backfill-legacy-alias-conflict",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Legacy Holder",
                "aliases": ["Legacy Alias"],
            },
            headers=auth_headers(),
        )
        assert legacy_holder.status_code == 200, legacy_holder.text
        overwrite_anchor_aliases(
            client,
            legacy_holder.json()["data"]["id"],
            ["Legacy Holder", "Atlas"],
        )

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-backfill-legacy-alias-conflict",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text
        backfill_data = backfill.json()["data"]

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-backfill-legacy-alias-conflict",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text

    assert backfill_data["created"] == 0
    assert backfill_data["updated"] == 0
    assert backfill_data["diagnostics"]["skipped_count"] == 1
    assert backfill_data["diagnostics"]["skipped_conflict_count"] == 1
    capture_summary = next(
        item for item in backfill_data["sources"] if item["source_type"] == "capture"
    )
    assert capture_summary["observed"] == 1
    assert capture_summary["skipped_conflicts"] == 1
    anchors_by_id = {item["id"]: item for item in anchors.json()["data"]}
    canonical_after = anchors_by_id[canonical.json()["data"]["id"]]
    assert {ref["source_id"] for ref in canonical_after["evidence_refs"]} == {
        "canonical-atlas-review"
    }
    assert capture_id not in {
        ref["source_id"] for ref in canonical_after["evidence_refs"]
    }


def test_project_merge_suggestions_skip_prefix_variant_projects(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "project-merge-prefix-guard",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "project-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "project-merge-prefix-seed",
                "text": "Seed project merge prefix guard scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        atlas = client.post(
            "/v1/anchors",
            json={
                "space_slug": "project-merge-prefix-guard",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Project Atlas",
            },
            headers=auth_headers(),
        )
        assert atlas.status_code == 200, atlas.text

        atlas_mobile = client.post(
            "/v1/anchors",
            json={
                "space_slug": "project-merge-prefix-guard",
                "memory_scope_external_ref": "default",
                "kind": "project",
                "label": "Project Atlas Mobile",
            },
            headers=auth_headers(),
        )
        assert atlas_mobile.status_code == 200, atlas_mobile.text

        suggestions = client.get(
            "/v1/anchors/merge-suggestions",
            params={
                "space_slug": "project-merge-prefix-guard",
                "memory_scope_external_ref": "default",
                "kind": "project",
            },
            headers=auth_headers(),
        )
        assert suggestions.status_code == 200, suggestions.text

    anchor_ids = {
        atlas.json()["data"]["id"],
        atlas_mobile.json()["data"]["id"],
    }
    suggested_pairs = {
        frozenset(
            {
                candidate["source_anchor"]["id"],
                candidate["target_anchor"]["id"],
            }
        )
        for candidate in suggestions.json()["data"]["candidates"]
    }
    assert frozenset(anchor_ids) not in suggested_pairs


def test_organization_anchor_alias_conflicts_and_split_preserve_lineage(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "org-anchor-conflict-seed",
                "text": "Seed organization anchor conflict scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        openai = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "OpenAI",
                "aliases": ["Open AI"],
                "evidence_refs": [{"source_type": "manual", "source_id": "openai-review"}],
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        assert openai.status_code == 200, openai.text

        duplicate_openai_alias = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Open AI",
            },
            headers=auth_headers(),
        )

        github = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "GitHub",
                "aliases": ["GH"],
            },
            headers=auth_headers(),
        )
        assert github.status_code == 200, github.text

        github_alias_conflict = client.patch(
            f"/v1/anchors/{github.json()['data']['id']}",
            json={"aliases": ["Open AI"]},
            headers=auth_headers(),
        )

        acme_parent = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme"],
                "evidence_refs": [{"source_type": "manual", "source_id": "acme-group"}],
                "valid_from": "2026-02-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        assert acme_parent.status_code == 200, acme_parent.text

        acme_existing = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Research",
                "aliases": ["Acme Labs"],
                "evidence_refs": [{"source_type": "manual", "source_id": "acme-research"}],
            },
            headers=auth_headers(),
        )
        assert acme_existing.status_code == 200, acme_existing.text

        split = client.post(
            f"/v1/anchors/{acme_parent.json()['data']['id']}/split",
            json={
                "alias": "Acme",
                "new_label": "Acme Research",
                "reason": "reviewer separated Acme alias into the research org",
            },
            headers=auth_headers(),
        )

        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "organization-anchor-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    assert duplicate_openai_alias.status_code == 409, duplicate_openai_alias.text
    assert github_alias_conflict.status_code == 409, github_alias_conflict.text
    assert split.status_code == 200, split.text
    split_anchor = split.json()["data"]
    assert split_anchor["id"] == acme_existing.json()["data"]["id"]
    assert split_anchor["metadata"]["split_from_anchor_id"] == acme_parent.json()["data"]["id"]
    assert split_anchor["valid_from"] == "2026-02-01T00:00:00+00:00"
    assert {ref["source_id"] for ref in split_anchor["evidence_refs"]} == {
        "acme-group",
        "acme-research",
    }
    active_by_id = {item["id"]: item for item in active.json()["data"]}
    assert "Acme" not in active_by_id[acme_parent.json()["data"]["id"]]["aliases"]


def test_organization_anchor_compact_alias_conflicts_reject_brand_variants(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "organization-compact-conflicts",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "org-compact-conflict-seed",
                "text": "Seed organization compact conflict scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        openai = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-compact-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "OpenAI",
            },
            headers=auth_headers(),
        )
        assert openai.status_code == 200, openai.text

        spaced_openai = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-compact-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Open AI",
            },
            headers=auth_headers(),
        )

        github = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-compact-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "GitHub",
            },
            headers=auth_headers(),
        )
        assert github.status_code == 200, github.text

        docs_hub = client.post(
            "/v1/anchors",
            json={
                "space_slug": "organization-compact-conflicts",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Docs Hub",
            },
            headers=auth_headers(),
        )
        assert docs_hub.status_code == 200, docs_hub.text

        spaced_github_alias = client.patch(
            f"/v1/anchors/{docs_hub.json()['data']['id']}",
            json={"aliases": ["Git Hub"]},
            headers=auth_headers(),
        )

    assert spaced_openai.status_code == 409, spaced_openai.text
    assert spaced_github_alias.status_code == 409, spaced_github_alias.text


def test_anchor_split_rejects_empty_normalized_label_without_mutating_alias(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-split-invalid-key",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "anchor-split-invalid-key-seed",
                "text": "Seed invalid split scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        acme_parent = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-invalid-key",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme"],
                "evidence_refs": [{"source_type": "manual", "source_id": "acme-group"}],
            },
            headers=auth_headers(),
        )
        assert acme_parent.status_code == 200, acme_parent.text

        invalid_split = client.post(
            f"/v1/anchors/{acme_parent.json()['data']['id']}/split",
            json={
                "alias": "Acme",
                "new_label": "!!!",
                "reason": "reject split labels without canonical identity",
            },
            headers=auth_headers(),
        )

        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-split-invalid-key",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    assert invalid_split.status_code == 400, invalid_split.text
    assert invalid_split.json()["error"]["code"] == "memory.validation"
    active_by_id = {item["id"]: item for item in active.json()["data"]}
    parent = active_by_id[acme_parent.json()["data"]["id"]]
    assert "Acme" in parent["aliases"]
    assert all(item["normalized_key"] for item in active.json()["data"])


def test_anchor_split_to_new_anchor_preserves_provenance_and_temporal_fields(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-split-provenance",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "anchor-split-provenance-seed",
                "text": "Seed split provenance scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        parent = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-provenance",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme Labs"],
                "confidence": "high",
                "evidence_refs": [
                    {
                        "source_type": "manual",
                        "source_id": "acme-group-review",
                        "quote_preview": (
                            "Reviewer confirmed Acme Labs was only an alias candidate."
                        ),
                    }
                ],
                "observed_at": "2026-02-03T04:05:06+00:00",
                "valid_from": "2026-02-01T00:00:00+00:00",
                "valid_to": "2026-08-01T00:00:00+00:00",
            },
            headers=auth_headers(),
        )
        assert parent.status_code == 200, parent.text

        split = client.post(
            f"/v1/anchors/{parent.json()['data']['id']}/split",
            json={
                "alias": "Acme Labs",
                "new_label": "Acme Labs",
                "reason": "reviewer promoted alias into a separate organization",
            },
            headers=auth_headers(),
        )
        assert split.status_code == 200, split.text

        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-split-provenance",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    split_anchor = split.json()["data"]
    assert split_anchor["normalized_key"] == "acme labs"
    assert split_anchor["confidence"] == "high"
    assert split_anchor["observed_at"] == "2026-02-03T04:05:06+00:00"
    assert split_anchor["valid_from"] == "2026-02-01T00:00:00+00:00"
    assert split_anchor["valid_to"] == "2026-08-01T00:00:00+00:00"
    assert split_anchor["metadata"]["split_from_anchor_id"] == parent.json()["data"]["id"]
    assert split_anchor["metadata"]["split_reason"] == (
        "reviewer promoted alias into a separate organization"
    )
    assert [evidence_ref_identity(ref) for ref in split_anchor["evidence_refs"]] == [
        {
            "source_type": "manual",
            "source_id": "acme-group-review",
            "chunk_id": None,
            "char_start": None,
            "char_end": None,
            "quote_preview": "Reviewer confirmed Acme Labs was only an alias candidate.",
        }
    ]
    active_by_id = {item["id"]: item for item in active.json()["data"]}
    assert "Acme Labs" not in active_by_id[parent.json()["data"]["id"]]["aliases"]


def test_anchor_merge_rejects_legacy_alias_conflict_with_third_anchor(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-merge-legacy-conflict",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "anchor-merge-conflict-seed",
                "text": "Seed merge conflict scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        target = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-merge-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme Group Canonical"],
            },
            headers=auth_headers(),
        )
        source = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-merge-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Legacy",
                "aliases": ["Acme"],
            },
            headers=auth_headers(),
        )
        third = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-merge-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Research",
                "aliases": ["Research Labs"],
            },
            headers=auth_headers(),
        )
        assert target.status_code == 200, target.text
        assert source.status_code == 200, source.text
        assert third.status_code == 200, third.text
        overwrite_anchor_aliases(
            client,
            third.json()["data"]["id"],
            ["Acme Research", "Acme"],
        )

        merge = client.post(
            f"/v1/anchors/{source.json()['data']['id']}/merge",
            json={
                "target_anchor_id": target.json()["data"]["id"],
                "reason": "reviewer attempted legacy merge",
            },
            headers=auth_headers(),
        )
        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-merge-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    assert merge.status_code == 409, merge.text
    active_by_id = {item["id"]: item for item in active.json()["data"]}
    assert source.json()["data"]["id"] in active_by_id
    assert "Acme" not in active_by_id[target.json()["data"]["id"]]["aliases"]


def test_anchor_split_to_existing_rejects_legacy_alias_conflict_with_third_anchor(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-split-existing-legacy-conflict",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "anchor-split-existing-conflict-seed",
                "text": "Seed split existing conflict scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        parent = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-existing-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme"],
            },
            headers=auth_headers(),
        )
        target = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-existing-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Research",
            },
            headers=auth_headers(),
        )
        third = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-existing-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Legacy Holder",
                "aliases": ["Legacy Alias"],
            },
            headers=auth_headers(),
        )
        assert parent.status_code == 200, parent.text
        assert target.status_code == 200, target.text
        assert third.status_code == 200, third.text
        overwrite_anchor_aliases(
            client,
            third.json()["data"]["id"],
            ["Legacy Holder", "Acme"],
        )

        split = client.post(
            f"/v1/anchors/{parent.json()['data']['id']}/split",
            json={
                "alias": "Acme",
                "new_label": "Acme Research",
                "reason": "reviewer attempted legacy split into existing anchor",
            },
            headers=auth_headers(),
        )
        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-split-existing-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    assert split.status_code == 409, split.text
    active_by_id = {item["id"]: item for item in active.json()["data"]}
    assert "Acme" in active_by_id[parent.json()["data"]["id"]]["aliases"]
    assert "Acme" not in active_by_id[target.json()["data"]["id"]]["aliases"]


def test_anchor_split_to_new_rejects_legacy_alias_conflict_with_third_anchor(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        seed_scope = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-split-new-legacy-conflict",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "org-review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "anchor-split-new-conflict-seed",
                "text": "Seed split new conflict scope.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert seed_scope.status_code == 201, seed_scope.text

        parent = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-new-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Acme Group",
                "aliases": ["Acme"],
            },
            headers=auth_headers(),
        )
        third = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-split-new-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "label": "Legacy Holder",
                "aliases": ["Legacy Alias"],
            },
            headers=auth_headers(),
        )
        assert parent.status_code == 200, parent.text
        assert third.status_code == 200, third.text
        overwrite_anchor_aliases(
            client,
            third.json()["data"]["id"],
            ["Legacy Holder", "Acme"],
        )

        split = client.post(
            f"/v1/anchors/{parent.json()['data']['id']}/split",
            json={
                "alias": "Acme",
                "new_label": "Acme Labs",
                "reason": "reviewer attempted legacy split into new anchor",
            },
            headers=auth_headers(),
        )
        active = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-split-new-legacy-conflict",
                "memory_scope_external_ref": "default",
                "kind": "organization",
                "limit": 100,
            },
            headers=auth_headers(),
        )

    assert split.status_code == 409, split.text
    active_items = active.json()["data"]
    active_by_id = {item["id"]: item for item in active_items}
    assert "Acme" in active_by_id[parent.json()["data"]["id"]]["aliases"]
    assert all(item["normalized_key"] != "acme labs" for item in active_items)


def test_anchor_backfill_preserves_manual_event_label_for_case_variants(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        capture = client.post(
            "/v1/captures",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "review",
                "source_agent": "memo-frontend",
                "source_kind": "manual",
                "event_type": "QuickCapture",
                "actor_role": "user",
                "source_event_id": "capture-maria-event-variant",
                "text": "Созвон с Мария вчера подтвердил Project Atlas.",
                "source_authority": "user_statement",
            },
            headers=auth_headers(),
        )
        assert capture.status_code == 201, capture.text

        manual_anchor = client.post(
            "/v1/anchors",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "event",
                "label": "Созвон с Марией вчера",
                "aliases": ["Вчерашний созвон с Марией"],
                "description": "Reviewer-confirmed event anchor.",
            },
            headers=auth_headers(),
        )
        assert manual_anchor.status_code == 200, manual_anchor.text
        manual_anchor_data = manual_anchor.json()["data"]
        assert manual_anchor_data["metadata"]["canonical_key"] == "sozvon s mariya vchera"

        backfill = client.post(
            "/v1/anchors/backfill",
            json={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "limit_per_source": 20,
            },
            headers=auth_headers(),
        )
        assert backfill.status_code == 200, backfill.text

        anchors = client.get(
            "/v1/anchors",
            params={
                "space_slug": "anchor-event-case-variants",
                "memory_scope_external_ref": "default",
                "kind": "event",
                "limit": 100,
            },
            headers=auth_headers(),
        )
        assert anchors.status_code == 200, anchors.text
        event_anchors = anchors.json()["data"]
        participant_events = [
            item
            for item in event_anchors
            if item["metadata"]["canonical_key"] == "sozvon s mariya vchera"
        ]
        assert len(participant_events) == 1
        event_anchor = participant_events[0]
        assert event_anchor["id"] == manual_anchor_data["id"]
        assert event_anchor["label"] == "Созвон с Марией вчера"
        assert event_anchor["normalized_key"] == "созвон с марией вчера"
        assert {
            "Созвон с Марией вчера",
            "Созвон с Мария вчера",
        }.issubset(set(event_anchor["aliases"]))
        assert any(item["normalized_key"] == "созвон вчера" for item in event_anchors)
