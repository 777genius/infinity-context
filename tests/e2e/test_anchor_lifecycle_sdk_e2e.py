from __future__ import annotations

from pathlib import Path

from memo_stack_sdk import MemoStackClient
from memo_stack_server_harness import run_memo_stack_server


def test_anchor_lifecycle_sdk_e2e(tmp_path: Path) -> None:
    with run_memo_stack_server(
        tmp_path,
        database_name="anchor-lifecycle-sdk.db",
        extra_env={"MEMORY_CAPTURE_MODE": "suggest"},
    ) as server:
        client = MemoStackClient(base_url=server.base_url, token=server.token)
        client.create_capture(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            thread_external_ref="review",
            source_agent="memo-frontend",
            source_kind="manual",
            event_type="QuickCapture",
            actor_role="user",
            source_event_id="anchor-sdk-e2e-capture",
            text="Alex shared Project Atlas notes from meeting last week.",
            source_authority="user_statement",
        )
        client.remember_fact(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            thread_external_ref="review",
            text="Алекс confirmed Project Atlas priorities after the call yesterday.",
            kind="note",
            source_refs=[{"source_type": "manual", "source_id": "anchor-sdk-e2e-fact"}],
            idempotency_key="anchor-sdk-e2e-fact",
        )
        manual_anchor = client.create_anchor(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            kind="project",
            label="Atlas",
            aliases=["Project Atlas"],
            description="Manual project anchor created in sdk e2e.",
        )
        manual_anchor_duplicate = client.create_anchor(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            kind="project",
            label="Atlas",
            aliases=["Atlas roadmap"],
            description="Updated manual project anchor in sdk e2e.",
        )
        assert manual_anchor_duplicate["data"]["id"] == manual_anchor["data"]["id"]
        assert "Atlas roadmap" in manual_anchor_duplicate["data"]["aliases"]
        edited_manual_anchor = client.update_anchor(
            manual_anchor["data"]["id"],
            label="Atlas Roadmap",
            aliases=["Project Atlas", "Atlas delivery"],
            description="Edited manual project anchor in sdk e2e.",
        )
        assert edited_manual_anchor["data"]["normalized_key"] == "atlas roadmap"
        assert "Atlas delivery" in edited_manual_anchor["data"]["aliases"]
        deleted_manual_anchor = client.delete_anchor(
            manual_anchor["data"]["id"],
            reason="obsolete manual project anchor in sdk e2e",
        )
        assert deleted_manual_anchor["data"]["status"] == "deleted"

        backfill = client.backfill_anchors(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            limit_per_source=20,
        )
        anchors = client.list_anchors(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            status="active",
            limit=100,
        )
        merge_suggestions = client.list_anchor_merge_suggestions(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            kind="person",
            limit=20,
        )

        keys = {(item["kind"], item["normalized_key"]) for item in anchors["data"]}
        assert backfill["data"]["created"] >= 3
        assert ("person", "alex") in keys
        assert ("person", "алекс") in keys
        assert ("project", "atlas") in keys
        assert ("event", "meeting last week") in keys

        candidate = next(
            item
            for item in merge_suggestions["data"]["candidates"]
            if {
                item["source_anchor"]["normalized_key"],
                item["target_anchor"]["normalized_key"],
            }
            == {"alex", "алекс"}
        )
        merged = client.merge_anchor(
            candidate["source_anchor"]["id"],
            target_anchor_id=candidate["target_anchor"]["id"],
            reason="same person confirmed in sdk e2e",
        )
        assert {"Alex", "Алекс"}.issubset(set(merged["data"]["aliases"]))

        split = client.split_anchor(
            merged["data"]["id"],
            alias="Алекс",
            new_label="Алексей",
            reason="split alias in sdk e2e",
        )
        deleted = client.list_anchors(
            space_slug="anchor-sdk-e2e",
            memory_scope_external_ref="default",
            status="deleted",
            limit=100,
        )
        assert split["data"]["normalized_key"] == "алексей"
        assert any(
            item["id"] == candidate["source_anchor"]["id"]
            and item["metadata"]["merged_into_anchor_id"] == candidate["target_anchor"]["id"]
            for item in deleted["data"]
        )
