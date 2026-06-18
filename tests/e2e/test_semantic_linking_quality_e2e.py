from __future__ import annotations

from pathlib import Path

import httpx
from memo_stack_server_harness import run_memo_stack_server


def test_semantic_linking_quality_golden_cases_e2e(tmp_path: Path) -> None:
    with (
        run_memo_stack_server(
            tmp_path,
            database_name="semantic-linking-quality.db",
            extra_env={"MEMORY_CAPTURE_MODE": "suggest"},
        ) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=20,
        ) as client,
    ):
        target_fact = _remember_fact(
            client,
            text=(
                "Alex and Project Atlas onboarding pricing summary from an hour ago. "
                "The action item is invoice threshold approval."
            ),
            source_id="atlas-pricing",
        )
        distractor_fact = _remember_fact(
            client,
            text=(
                "Alex and Project Aurora branding notes from last week. "
                "The topic is logo color and launch copy."
            ),
            source_id="aurora-branding",
        )
        source_capture = _capture(
            client,
            source_event_id="atlas-pricing-capture",
            text=(
                "Screenshot note from Alex an hour ago about Project Atlas onboarding "
                "pricing and invoice threshold approval."
            ),
            thread_external_ref="quality-review",
        )

        suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quality-review",
                "source_type": "capture",
                "source_id": source_capture["id"],
                "text": "Alex hour ago Project Atlas onboarding pricing invoice threshold",
                "persist": True,
                "limit": 8,
            },
        )
        assert suggestions.status_code == 200, suggestions.text
        candidates = suggestions.json()["data"]["candidates"]
        fact_candidates = [item for item in candidates if item["target_type"] == "fact"]
        assert fact_candidates[0]["target_id"] == target_fact["id"]
        assert fact_candidates[0]["score"] > _candidate_score(
            fact_candidates,
            distractor_fact["id"],
        )
        assert fact_candidates[0]["suggestion_id"]
        assert "text_match" in fact_candidates[0]["metadata"]["reason_codes"]
        assert {"alex", "atlas", "pricing"}.issubset(
            set(fact_candidates[0]["metadata"]["matched_terms"])
        )
        anchor_labels = {
            (item["metadata"].get("anchor_kind"), item["metadata"].get("normalized_key"))
            for item in candidates
            if item["target_type"] == "anchor"
        }
        assert ("person", "alex") in anchor_labels
        assert ("project", "atlas") in anchor_labels

        same_name_capture = _capture(
            client,
            source_event_id="same-name-anchor-capture",
            text="Alex wrote that Project Alex is a separate workspace.",
            thread_external_ref="quality-review",
        )
        same_name_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quality-review",
                "source_type": "capture",
                "source_id": same_name_capture["id"],
                "text": "Alex wrote that Project Alex is a separate workspace",
                "persist": True,
                "limit": 8,
            },
        )
        assert same_name_suggestions.status_code == 200, same_name_suggestions.text
        same_name_anchor_labels = {
            (item["metadata"].get("anchor_kind"), item["metadata"].get("normalized_key"))
            for item in same_name_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "anchor"
        }
        assert ("person", "alex") in same_name_anchor_labels
        assert ("project", "alex") in same_name_anchor_labels

        approved = client.post(
            f"/v1/context-link-suggestions/{fact_candidates[0]['suggestion_id']}/review",
            json={"action": "approve", "reason": "quality golden accepted top target"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["link"]["target_id"] == target_fact["id"]

        call_fact = _remember_fact(
            client,
            text=(
                "Alex Project Atlas call from last week covered migration rollback "
                "window ownership and production risk handoff."
            ),
            source_id="atlas-migration-call",
        )
        chat_distractor_fact = _remember_fact(
            client,
            text=(
                "Alex Project Atlas chat from an hour ago covered billing dashboard "
                "copy and button icons."
            ),
            source_id="atlas-billing-chat",
        )
        call_capture = _capture(
            client,
            source_event_id="atlas-migration-call-capture",
            text=(
                "Please link this note to the Alex Project Atlas call last week "
                "about migration rollback window and production risk handoff."
            ),
            thread_external_ref="quality-review",
        )

        event_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "quality-review",
                "source_type": "capture",
                "source_id": call_capture["id"],
                "text": (
                    "Alex Project Atlas call last week migration rollback production risk handoff"
                ),
                "persist": True,
                "limit": 8,
            },
        )
        assert event_suggestions.status_code == 200, event_suggestions.text
        event_fact_candidates = [
            item
            for item in event_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "fact"
        ]
        assert event_fact_candidates[0]["target_id"] == call_fact["id"]
        assert event_fact_candidates[0]["score"] > _candidate_score(
            event_fact_candidates,
            chat_distractor_fact["id"],
        )

        document = _ingest_document(
            client,
            title="Project Atlas onboarding pricing SOP",
            text=(
                "Project Atlas onboarding pricing SOP. Screenshots showing invoice "
                "threshold approval should be attached to this document evidence "
                "before the finance handoff."
            ),
            source_external_id="atlas-pricing-sop",
        )
        document_capture = _capture(
            client,
            source_event_id="atlas-pricing-sop-screenshot",
            text=(
                "Screenshot from the Project Atlas onboarding pricing SOP showing "
                "invoice threshold approval before finance handoff."
            ),
            thread_external_ref="document-review",
        )
        document_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality",
                "memory_scope_external_ref": "default",
                "thread_external_ref": "document-review",
                "source_type": "capture",
                "source_id": document_capture["id"],
                "text": (
                    "Project Atlas onboarding pricing SOP invoice threshold "
                    "approval finance handoff"
                ),
                "persist": True,
                "limit": 8,
            },
        )
        assert document_suggestions.status_code == 200, document_suggestions.text
        document_candidates = [
            item
            for item in document_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "document"
        ]
        chunk_candidates = [
            item
            for item in document_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "chunk"
        ]
        assert document_candidates[0]["target_id"] == document["id"]
        assert chunk_candidates[0]["metadata"]["document_id"] == document["id"]
        assert "text_match" in chunk_candidates[0]["metadata"]["reason_codes"]

        unrelated_capture = _capture(
            client,
            source_event_id="unrelated-capture",
            text="lowercase grocery reminder about bananas milk and receipts",
        )
        unrelated = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": unrelated_capture["id"],
                "text": "lowercase grocery reminder bananas milk receipts",
                "persist": True,
                "limit": 8,
            },
        )
        assert unrelated.status_code == 200, unrelated.text
        assert unrelated.json()["data"]["candidates"] == []

        rejected_fact = _remember_fact(
            client,
            text=(
                "Project Atlas screenshot evidence mentions Alex and a rejected "
                "vendor onboarding checklist."
            ),
            source_id="atlas-rejected-screenshot-link",
        )
        rejected_capture = _capture(
            client,
            source_event_id="atlas-rejected-screenshot-capture",
            text=(
                "Save Alex Project Atlas screenshot evidence for rejected vendor "
                "onboarding checklist review."
            ),
            thread_external_ref="quality-review",
        )
        rejected_payload = {
            "space_slug": "semantic-linking-quality",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "quality-review",
            "source_type": "capture",
            "source_id": rejected_capture["id"],
            "text": "Alex Project Atlas screenshot evidence rejected vendor onboarding checklist",
            "persist": True,
            "limit": 8,
        }
        rejected_suggestions = client.post("/v1/link-suggestions", json=rejected_payload)
        assert rejected_suggestions.status_code == 200, rejected_suggestions.text
        rejected_candidate = next(
            item
            for item in rejected_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "fact" and item["target_id"] == rejected_fact["id"]
        )
        rejected_review = client.post(
            f"/v1/context-link-suggestions/{rejected_candidate['suggestion_id']}/review",
            json={"action": "reject", "reason": "quality golden rejected duplicate link"},
        )
        assert rejected_review.status_code == 200, rejected_review.text

        repeated_rejected_suggestions = client.post(
            "/v1/link-suggestions",
            json=rejected_payload,
        )
        assert repeated_rejected_suggestions.status_code == 200
        repeated_rejected_data = repeated_rejected_suggestions.json()["data"]
        assert all(
            item["target_id"] != rejected_fact["id"]
            for item in repeated_rejected_data["candidates"]
            if item["target_type"] == "fact"
        )
        assert repeated_rejected_data["diagnostics"]["skipped_reviewed_suggestion_count"] >= 1
        assert (
            repeated_rejected_data["diagnostics"]["skipped_reviewed_suggestion_status_counts"][
                "rejected"
            ]
            >= 1
        )

        cross_scope_fact = _remember_fact(
            client,
            space_slug="semantic-linking-quality-private",
            text=(
                "Project Zephyr private renewal memo names Casey as owner for "
                "the vendor risk exception."
            ),
            source_id="zephyr-private-renewal",
        )
        cross_scope_capture = _capture(
            client,
            space_slug="semantic-linking-quality-query",
            source_event_id="zephyr-cross-scope-capture",
            text=(
                "Project Zephyr private renewal memo names Casey as owner for "
                "the vendor risk exception."
            ),
        )
        cross_scope_suggestions = client.post(
            "/v1/link-suggestions",
            json={
                "space_slug": "semantic-linking-quality-query",
                "memory_scope_external_ref": "default",
                "source_type": "capture",
                "source_id": cross_scope_capture["id"],
                "text": "Project Zephyr private renewal Casey vendor risk exception",
                "persist": True,
                "limit": 8,
            },
        )
        assert cross_scope_suggestions.status_code == 200, cross_scope_suggestions.text
        cross_scope_fact_candidates = [
            item
            for item in cross_scope_suggestions.json()["data"]["candidates"]
            if item["target_type"] == "fact"
        ]
        assert cross_scope_fact
        assert cross_scope_fact_candidates == []


def _remember_fact(
    client: httpx.Client,
    *,
    text: str,
    source_id: str,
    space_slug: str = "semantic-linking-quality",
) -> dict[str, object]:
    response = client.post(
        "/v1/facts",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "thread_external_ref": "quality-review",
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
        headers={"Idempotency-Key": f"{space_slug}-{source_id}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _capture(
    client: httpx.Client,
    *,
    source_event_id: str,
    text: str,
    thread_external_ref: str | None = None,
    space_slug: str = "semantic-linking-quality",
) -> dict[str, object]:
    response = client.post(
        "/v1/captures",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "thread_external_ref": thread_external_ref,
            "source_agent": "memo-frontend",
            "source_kind": "manual",
            "event_type": "QuickCapture",
            "actor_role": "user",
            "source_event_id": source_event_id,
            "text": text,
            "source_authority": "user_statement",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _ingest_document(
    client: httpx.Client,
    *,
    title: str,
    text: str,
    source_external_id: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/documents",
        json={
            "space_slug": "semantic-linking-quality",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "document-review",
            "title": title,
            "text": text,
            "source_type": "document",
            "source_external_id": source_external_id,
            "classification": "internal",
        },
        headers={"Idempotency-Key": f"semantic-linking-quality-{source_external_id}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _candidate_score(candidates: list[dict[str, object]], target_id: str) -> float:
    candidate = next(item for item in candidates if item["target_id"] == target_id)
    return float(candidate["score"])
