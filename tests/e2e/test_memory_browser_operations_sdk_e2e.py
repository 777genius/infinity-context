from __future__ import annotations

from pathlib import Path

from memo_stack_sdk import MemoStackClient
from memo_stack_server_harness import run_memo_stack_server


def test_memory_browser_and_operations_console_sdk_e2e(tmp_path: Path) -> None:
    with run_memo_stack_server(
        tmp_path,
        database_name="memory-browser-operations-sdk.db",
        extra_env={"MEMORY_CAPTURE_MODE": "suggest"},
    ) as server:
        client = MemoStackClient(base_url=server.base_url, token=server.token)
        fact = client.remember_fact(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            text="Alex confirmed Project Atlas file memory must preserve screenshots.",
            kind="note",
            source_refs=[{"source_type": "manual", "source_id": "browser-ops-fact"}],
            tags=["alex", "atlas", "screenshots"],
            idempotency_key="browser-ops-sdk-fact",
        )
        document = client.ingest_document(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            title="Project Atlas screenshot notes",
            text="Alex Project Atlas screenshot evidence belongs in the memory browser.",
            source_type="document",
            source_external_id="browser-ops-sdk-document",
            idempotency_key="browser-ops-sdk-document",
        )
        episode = client.ingest_episode(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            source_type="transcript",
            source_external_id="browser-ops-sdk-episode",
            text="Alex call episode confirms screenshot memory review.",
            speaker="user",
            idempotency_key="browser-ops-sdk-episode",
        )
        asset = client.upload_asset(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            filename="atlas-note.txt",
            content=b"Alex Project Atlas screenshot evidence",
            content_type="text/plain",
            extract=True,
        )
        extraction_id = asset["data"]["extraction"]["id"]
        capture = client.create_capture(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            source_agent="memo-frontend",
            source_kind="manual",
            event_type="QuickCapture",
            actor_role="user",
            source_event_id="browser-ops-sdk-capture",
            text="Screenshot from Alex belongs to Project Atlas file memory.",
            source_authority="user_statement",
            evidence_refs=[{"source_type": "asset", "source_id": asset["data"]["id"]}],
        )
        suggestions = client.suggest_context_links(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            thread_external_ref="alex-call",
            source_type="capture",
            source_id=capture["data"]["id"],
            text="Alex Project Atlas screenshot file memory",
            persist=True,
            limit=10,
        )
        fact_candidate = next(
            item
            for item in suggestions["data"]["candidates"]
            if item["target_type"] == "fact" and item["target_id"] == fact["data"]["id"]
        )

        before_review = client.get_operations_console(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            limit=20,
        )
        reviewed = client.review_context_link_suggestion(
            fact_candidate["suggestion_id"],
            action="approve",
            reason="sdk e2e user accepted browser link",
            relation_type="supports",
            confidence="high",
            link_reason="capture references the same person, project and screenshot evidence",
        )
        client.backfill_anchors(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            limit_per_source=30,
        )
        browser = client.get_memory_browser(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            limit=100,
            fact_status="active",
            episode_status="active",
            document_status="active",
            link_status="active",
            suggestion_status="approved",
        )
        after_review = client.get_operations_console(
            space_slug="browser-ops-sdk-e2e",
            memory_scope_external_ref="project-atlas",
            limit=20,
        )

    assert before_review["data"]["link_suggestion_status_counts"]["pending"] >= 1
    assert before_review["data"]["diagnostics"]["link_suggestion_pending_count"] >= 1
    assert before_review["data"]["extraction_jobs"][0]["id"] == extraction_id

    assert reviewed["data"]["suggestion"]["status"] == "approved"
    assert reviewed["data"]["link"]["target_id"] == fact["data"]["id"]
    assert reviewed["data"]["link"]["relation_type"] == "supports"
    assert reviewed["data"]["link"]["confidence"] == "high"

    data = browser["data"]
    assert data["memory_scope"]["external_ref"] == "project-atlas"
    assert {item["id"] for item in data["facts"]} == {fact["data"]["id"]}
    assert {item["id"] for item in data["episodes"]} == {episode["data"]["episode_id"]}
    assert {item["id"] for item in data["documents"]} == {document["data"]["id"]}
    assert any(item["document_id"] == document["data"]["id"] for item in data["chunks"])
    assert any(item["episode_id"] == episode["data"]["episode_id"] for item in data["chunks"])
    assert {item["id"] for item in data["extraction_jobs"]} == {extraction_id}
    assert {item["external_ref"] for item in data["threads"]} == {"alex-call"}
    assert {item["id"] for item in data["captures"]} == {capture["data"]["id"]}
    assert {item["id"] for item in data["assets"]} == {asset["data"]["id"]}
    assert {item["id"] for item in data["context_links"]} == {reviewed["data"]["link"]["id"]}
    assert {item["id"] for item in data["context_link_suggestions"]} == {
        fact_candidate["suggestion_id"]
    }
    assert any(item["label"] == "Alex" for item in data["anchors"])
    assert any(item["label"] == "Atlas" for item in data["anchors"])
    assert data["stats"]["facts"] == 1
    assert data["stats"]["episodes"] == 1
    assert data["stats"]["documents"] == 1
    assert data["stats"]["chunks"] == 2
    assert data["stats"]["extraction_jobs"] == 1
    assert data["stats"]["active_context_links"] == 1
    assert data["stats"]["pending_context_link_suggestions"] == 0
    assert data["diagnostics"]["browser_version"] == "memory-browser-v1"

    assert after_review["data"]["link_suggestion_status_counts"]["approved"] >= 1
    assert after_review["data"]["diagnostics"]["link_suggestion_reviewed_count"] >= 1
