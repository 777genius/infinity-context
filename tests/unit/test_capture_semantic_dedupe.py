import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_core.application import ConsolidateCaptureCommand, ConsolidateCaptureUseCase
from infinity_context_core.domain.entities import Confidence, MemoryKind, SourceRef
from infinity_context_core.ports.auto_memory import (
    CandidateOperation,
    MemoryCandidate,
    SourceProvenance,
)
from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.main import create_app


class StaticExtractor:
    version = "semantic-dedupe-test-extractor-v1"
    prompt_version = "semantic-dedupe-test-prompt-v1"
    requires_external_ai = False

    def __init__(self, candidates: tuple[MemoryCandidate, ...]) -> None:
        self._candidates = candidates

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        return self._candidates


def test_capture_semantic_active_duplicate_creates_merge_review_suggestion(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-semantic-duplicate.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Qdrant owns document vector retrieval.",
            space_slug="capture-semantic-duplicate",
            source_id="semantic-dedupe-existing",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Docs retrieval should use Qdrant vectors.",
            space_slug="capture-semantic-duplicate",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Docs retrieval should use Qdrant vectors.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                        source_id="semantic-dedupe-candidate",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-semantic-duplicate")
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-duplicate",
        )
        suggestion = suggestions.json()["data"][0]
        approved = client.post(
            f"/v1/suggestions/{suggestion['id']}/approve",
            json={"reason": "confirmed duplicate source merge"},
            headers=headers,
        )
        merged_facts = _list_facts(client, headers=headers, space_slug="capture-semantic-duplicate")

    assert existing.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert [item["text"] for item in facts.json()["data"]] == [
        "Qdrant owns document vector retrieval."
    ]
    assert suggestion["operation"] == "review"
    assert suggestion["target_fact_id"] == existing.json()["data"]["id"]
    assert suggestion["review_payload"]["review_kind"] == "duplicate_fact_merge"
    assert suggestion["available_review_actions"] == [
        "approve",
        "reject",
        "expire",
        "resolve_duplicate",
    ]
    assert suggestion["review_resolution_options"][0]["id"] == "merge_source_refs"
    assert suggestion["review_resolution_options"][0]["review_action"] == "resolve_duplicate"
    assert suggestion["review_resolution_options"][1]["id"] == "keep_separate_fact"
    assert suggestion["review_payload"]["default_resolution"] == (
        "merge_or_keep_separate_after_review"
    )
    assert suggestion["review_payload"]["requires_review"] is True
    assert suggestion["review_payload"]["auto_merge_eligible"] is False
    assert suggestion["review_payload"]["review_risk"] == "medium"
    assert suggestion["review_payload"]["recommended_resolution_action"] == "merge_source_refs"
    assert suggestion["review_payload"]["dedupe_match_type"] == "semantic_token_overlap"
    assert "semantic_duplicate" in suggestion["review_payload"]["dedupe_reason_codes"]
    assert approved.status_code == 200, approved.text
    merged_fact = merged_facts.json()["data"][0]
    assert merged_fact["text"] == "Qdrant owns document vector retrieval."
    assert merged_fact["version"] == 2
    assert {ref["source_id"] for ref in merged_fact["source_refs"]} == {
        "semantic-dedupe-existing",
        "semantic-dedupe-candidate",
    }


def test_capture_semantic_russian_duplicate_creates_merge_review_suggestion(
    tmp_path: Path,
) -> None:
    app = _capture_app(
        tmp_path,
        "capture-semantic-russian-duplicate.db",
        CaptureMode.AUTO_APPLY_SAFE,
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Алекс согласовал срок по проекту Атлас 7 дней.",
            space_slug="capture-semantic-russian-duplicate",
            source_id="semantic-russian-existing",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Запомни: От Алекса пришло подтверждение, проект Атлас срок 7 дней.",
            space_slug="capture-semantic-russian-duplicate",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "От Алекса пришло подтверждение, проект Атлас срок 7 дней.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                        source_id="semantic-russian-candidate",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-semantic-russian-duplicate",
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-russian-duplicate",
        )
        suggestion = suggestions.json()["data"][0]
        approved = client.post(
            f"/v1/suggestions/{suggestion['id']}/approve",
            json={"reason": "confirmed russian duplicate source merge"},
            headers=headers,
        )
        merged_facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-semantic-russian-duplicate",
        )

    assert existing.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert [item["text"] for item in facts.json()["data"]] == [
        "Алекс согласовал срок по проекту Атлас 7 дней."
    ]
    assert suggestion["operation"] == "review"
    assert suggestion["target_fact_id"] == existing.json()["data"]["id"]
    assert suggestion["review_payload"]["review_kind"] == "duplicate_fact_merge"
    assert suggestion["review_payload"]["dedupe_match_type"] == "semantic_token_overlap"
    assert "person:aleks" in suggestion["review_payload"]["dedupe_overlap_terms"]
    assert "project:atlas" in suggestion["review_payload"]["dedupe_overlap_terms"]
    assert approved.status_code == 200, approved.text
    merged_fact = merged_facts.json()["data"][0]
    assert merged_fact["version"] == 2
    assert {ref["source_id"] for ref in merged_fact["source_refs"]} == {
        "semantic-russian-existing",
        "semantic-russian-candidate",
    }


def test_capture_semantic_cross_language_call_summary_creates_merge_review_suggestion(
    tmp_path: Path,
) -> None:
    app = _capture_app(
        tmp_path,
        "capture-semantic-cross-language-summary.db",
        CaptureMode.AUTO_APPLY_SAFE,
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Alex owns Atlas document retrieval notes from the call.",
            space_slug="capture-semantic-cross-language-summary",
            source_id="semantic-cross-language-existing",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Запомни: Итоги созвона: Алекс отвечает за поиск документов в Атласе.",
            space_slug="capture-semantic-cross-language-summary",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Итоги созвона: Алекс отвечает за поиск документов в Атласе.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                        source_id="semantic-cross-language-candidate",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-semantic-cross-language-summary",
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-cross-language-summary",
        )
        suggestion = suggestions.json()["data"][0]
        approved = client.post(
            f"/v1/suggestions/{suggestion['id']}/approve",
            json={"reason": "confirmed cross-language summary duplicate"},
            headers=headers,
        )
        merged_facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-semantic-cross-language-summary",
        )

    assert existing.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert [item["text"] for item in facts.json()["data"]] == [
        "Alex owns Atlas document retrieval notes from the call."
    ]
    assert suggestion["operation"] == "review"
    assert suggestion["target_fact_id"] == existing.json()["data"]["id"]
    assert suggestion["review_payload"]["review_kind"] == "duplicate_fact_merge"
    assert suggestion["review_payload"]["dedupe_match_type"] == "semantic_token_overlap"
    assert "event_type:call" in suggestion["review_payload"]["dedupe_overlap_terms"]
    assert "person:aleks" in suggestion["review_payload"]["dedupe_overlap_terms"]
    assert "project:atlas" in suggestion["review_payload"]["dedupe_overlap_terms"]
    assert approved.status_code == 200, approved.text
    merged_fact = merged_facts.json()["data"][0]
    assert merged_fact["version"] == 2
    assert {ref["source_id"] for ref in merged_fact["source_refs"]} == {
        "semantic-cross-language-existing",
        "semantic-cross-language-candidate",
    }


def test_capture_semantic_dedupe_keeps_engine_mismatch_for_review(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "capture-semantic-engine-mismatch.db", CaptureMode.SUGGEST)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        _create_fact(
            client,
            headers=headers,
            text="Postgres owns document vector retrieval.",
            space_slug="capture-semantic-engine-mismatch",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Docs retrieval should use Qdrant vectors.",
            space_slug="capture-semantic-engine-mismatch",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor((_candidate("Docs retrieval should use Qdrant vectors."),)),
            auto_apply_safe_enabled=False,
        )
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-engine-mismatch",
        )

    assert result.created_suggestions == 1
    assert suggestions.json()["data"][0]["candidate_text"] == (
        "Docs retrieval should use Qdrant vectors."
    )


def test_auto_apply_safe_similar_event_with_different_time_is_not_merged(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-semantic-event-time.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Alex call last week covered Project Atlas pricing.",
            space_slug="capture-semantic-event-time",
            source_id="alex-last-week",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Alex call yesterday covered Project Atlas pricing.",
            space_slug="capture-semantic-event-time",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Alex call yesterday covered Project Atlas pricing.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                        source_id="alex-yesterday",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-semantic-event-time")
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-event-time",
        )

    assert existing.status_code == 201
    assert result.auto_applied_facts == 1
    assert result.created_suggestions == 0
    assert suggestions.json()["data"] == []
    fact_texts = {item["text"] for item in facts.json()["data"]}
    assert fact_texts == {
        "Alex call last week covered Project Atlas pricing.",
        "Alex call yesterday covered Project Atlas pricing.",
    }


def test_auto_apply_safe_active_conflict_creates_review_suggestion_not_fact(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-semantic-active-conflict.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Postgres owns document vector retrieval.",
            space_slug="capture-semantic-active-conflict",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Docs retrieval should use Qdrant vectors.",
            space_slug="capture-semantic-active-conflict",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Docs retrieval should use Qdrant vectors.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-semantic-active-conflict")
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-active-conflict",
        )

    assert existing.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert [item["text"] for item in facts.json()["data"]] == [
        "Postgres owns document vector retrieval."
    ]

    suggestion = suggestions.json()["data"][0]
    assert suggestion["candidate_text"] == "Docs retrieval should use Qdrant vectors."
    assert suggestion["review_payload"]["review_kind"] == "conflict_review"
    assert suggestion["review_kind"] == "conflict_review"
    assert suggestion["available_review_actions"] == [
        "approve",
        "reject",
        "expire",
        "resolve_conflict",
    ]
    assert suggestion["review_resolution_options"][1]["id"] == "approve_candidate"
    assert suggestion["review_resolution_options"][1]["effect"] == (
        "create_new_fact_keep_conflicting_fact"
    )
    assert suggestion["review_resolution_options"][3]["review_action"] == "resolve_conflict"
    assert suggestion["review_resolution_options"][3]["availability"] == "available"
    assert suggestion["review_resolution_options"][4]["id"] == "mark_existing_disputed"
    assert suggestion["review_payload"]["conflicting_fact_id"] == existing.json()["data"]["id"]
    assert suggestion["review_payload"]["conflicting_fact_version"] == 1
    assert suggestion["review_payload"]["conflict_match_type"] == "exclusive_anchor_mismatch"
    assert "exclusive_anchor_mismatch" in suggestion["review_payload"]["conflict_reason_codes"]
    assert "document" in suggestion["review_payload"]["conflict_overlap_terms"]
    assert "auto_apply_active_conflict" in suggestion["review_payload"]["rejected_resolver_codes"]


def test_auto_apply_safe_numeric_conflict_creates_review_suggestion_not_fact(
    tmp_path: Path,
) -> None:
    app = _capture_app(
        tmp_path,
        "capture-semantic-numeric-conflict.db",
        CaptureMode.AUTO_APPLY_SAFE,
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Project Atlas keeps billing logs for 7 days.",
            space_slug="capture-semantic-numeric-conflict",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Project Atlas keeps billing logs for 30 days.",
            space_slug="capture-semantic-numeric-conflict",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Project Atlas keeps billing logs for 30 days.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        facts = _list_facts(client, headers=headers, space_slug="capture-semantic-numeric-conflict")
        suggestions = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-semantic-numeric-conflict",
        )

    assert existing.status_code == 201
    assert result.auto_applied_facts == 0
    assert result.created_suggestions == 1
    assert [item["text"] for item in facts.json()["data"]] == [
        "Project Atlas keeps billing logs for 7 days."
    ]

    suggestion = suggestions.json()["data"][0]
    assert suggestion["candidate_text"] == "Project Atlas keeps billing logs for 30 days."
    assert suggestion["review_payload"]["review_kind"] == "conflict_review"
    assert suggestion["review_payload"]["recommended_action"] == "manual_conflict_review"
    assert suggestion["review_resolution_options"][0]["review_action"] == "reject"
    assert suggestion["review_resolution_options"][2]["review_action"] == "expire"
    assert suggestion["review_payload"]["conflicting_fact_id"] == existing.json()["data"]["id"]
    assert suggestion["review_payload"]["conflicting_fact_version"] == 1
    assert suggestion["review_payload"]["conflict_match_type"] == "numeric_value_mismatch"
    assert "numeric_value_mismatch" in suggestion["review_payload"]["conflict_reason_codes"]
    assert "billing" in suggestion["review_payload"]["conflict_overlap_terms"]
    assert "auto_apply_active_conflict" in suggestion["review_payload"]["rejected_resolver_codes"]


def test_conflict_resolution_replace_existing_fact_updates_conflicting_fact(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-conflict-replace.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Project Atlas keeps billing logs for 7 days.",
            space_slug="capture-conflict-replace",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Project Atlas keeps billing logs for 30 days.",
            space_slug="capture-conflict-replace",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Project Atlas keeps billing logs for 30 days.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        suggestion = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-conflict-replace",
        ).json()["data"][0]
        resolved = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-conflict",
            json={
                "action": "replace_existing_fact",
                "reason": "newer capture supersedes the old retention value",
            },
            headers=headers,
        )
        active_facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-conflict-replace",
        )
        pending = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-conflict-replace",
        )
        superseded_facts = _list_facts_with_status(
            client,
            headers=headers,
            space_slug="capture-conflict-replace",
            status_filter="superseded",
        )

    assert existing.status_code == 201
    assert result.created_suggestions == 1
    assert resolved.status_code == 200
    data = resolved.json()["data"]
    assert data["fact"]["id"] != existing.json()["data"]["id"]
    assert data["fact"]["text"] == "Project Atlas keeps billing logs for 30 days."
    assert data["fact"]["version"] == 2
    assert data["fact"]["status"] == "active"
    assert data["suggestion"]["status"] == "approved"
    assert data["suggestion"]["review_payload"]["resolved_conflict_action"] == (
        "replace_existing_fact"
    )
    assert set(data["suggestion"]["review_payload"]["canonical_fact_ids"]) == {
        data["fact"]["id"],
        existing.json()["data"]["id"],
    }
    assert [item["text"] for item in active_facts.json()["data"]] == [
        "Project Atlas keeps billing logs for 30 days."
    ]
    assert pending.json()["data"] == []
    assert [item["id"] for item in superseded_facts.json()["data"]] == [
        existing.json()["data"]["id"]
    ]


def test_conflict_resolution_mark_existing_disputed_removes_default_active_fact(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-conflict-dispute.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Project Atlas keeps billing logs for 7 days.",
            space_slug="capture-conflict-dispute",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Project Atlas keeps billing logs for 30 days.",
            space_slug="capture-conflict-dispute",
        )
        _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Project Atlas keeps billing logs for 30 days.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        suggestion = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-conflict-dispute",
        ).json()["data"][0]
        resolved = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-conflict",
            json={
                "action": "mark_existing_disputed",
                "reason": "both retention values need human verification",
            },
            headers=headers,
        )
        active_facts = _list_facts(
            client,
            headers=headers,
            space_slug="capture-conflict-dispute",
        )
        disputed_facts = _list_facts_with_status(
            client,
            headers=headers,
            space_slug="capture-conflict-dispute",
            status_filter="disputed",
        )

    assert existing.status_code == 201
    assert resolved.status_code == 200
    data = resolved.json()["data"]
    assert data["fact"]["id"] != existing.json()["data"]["id"]
    assert data["fact"]["status"] == "disputed"
    assert data["fact"]["version"] == 2
    assert data["suggestion"]["status"] == "approved"
    assert data["suggestion"]["review_payload"]["resolved_conflict_action"] == (
        "mark_existing_disputed"
    )
    assert active_facts.json()["data"] == []
    assert {item["id"] for item in disputed_facts.json()["data"]} == {
        data["fact"]["id"],
        existing.json()["data"]["id"],
    }


def test_conflict_approve_candidate_keeps_both_facts_active(tmp_path: Path) -> None:
    app = _capture_app(tmp_path, "capture-conflict-keep.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Project Atlas keeps billing logs for 7 days.",
            space_slug="capture-conflict-keep",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Project Atlas keeps billing logs for 30 days.",
            space_slug="capture-conflict-keep",
        )
        _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Project Atlas keeps billing logs for 30 days.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        suggestion = _list_suggestions(
            client, headers=headers, space_slug="capture-conflict-keep"
        ).json()["data"][0]
        resolved = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-conflict",
            json={"action": "approve_candidate", "reason": "retain both reviewed claims"},
            headers=headers,
        )
        active = _list_facts(client, headers=headers, space_slug="capture-conflict-keep").json()[
            "data"
        ]

    assert resolved.status_code == 200, resolved.text
    assert {item["id"] for item in active} == {
        existing.json()["data"]["id"],
        resolved.json()["data"]["fact"]["id"],
    }
    assert {item["status"] for item in active} == {"active"}


def test_temporal_candidate_requires_review_and_preserves_historical_window(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-temporal.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        capture = _create_capture(
            client,
            headers=headers,
            text="MySQL was used from January through June.",
            space_slug="capture-temporal",
        )
        result = _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "MySQL was used from January through June.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                        valid_until=datetime(2026, 7, 1, tzinfo=UTC),
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        suggestion = _list_suggestions(
            client, headers=headers, space_slug="capture-temporal"
        ).json()["data"][0]
        approved = client.post(
            f"/v1/suggestions/{suggestion['id']}/approve",
            json={"reason": "reviewed historical interval"},
            headers=headers,
        )
        fact_id = approved.json()["data"]["fact"]["id"]
        fact = client.get(f"/v1/facts/{fact_id}", headers=headers).json()["data"]

    assert result.auto_applied_facts == 0
    assert (
        "temporal_window_requires_review" in suggestion["review_payload"]["rejected_resolver_codes"]
    )
    assert approved.status_code == 200, approved.text
    assert fact["temporal"]["valid_from"] == "2026-01-01T00:00:00+00:00"
    assert fact["temporal"]["valid_to"] == "2026-07-01T00:00:00+00:00"


def test_conflict_resolution_rejects_stale_conflicting_fact_version(
    tmp_path: Path,
) -> None:
    app = _capture_app(tmp_path, "capture-conflict-stale.db", CaptureMode.AUTO_APPLY_SAFE)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        existing = _create_fact(
            client,
            headers=headers,
            text="Project Atlas keeps billing logs for 7 days.",
            space_slug="capture-conflict-stale",
        )
        capture = _create_capture(
            client,
            headers=headers,
            text="Remember: Project Atlas keeps billing logs for 30 days.",
            space_slug="capture-conflict-stale",
        )
        _consolidate(
            client,
            capture_id=capture.json()["data"]["id"],
            extractor=StaticExtractor(
                (
                    _candidate(
                        "Project Atlas keeps billing logs for 30 days.",
                        confidence=Confidence.HIGH,
                        ttl_policy="durable",
                    ),
                )
            ),
            auto_apply_safe_enabled=True,
        )
        suggestion = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-conflict-stale",
        ).json()["data"][0]
        updated = client.patch(
            f"/v1/facts/{existing.json()['data']['id']}",
            json={
                "expected_version": 1,
                "text": "Project Atlas keeps billing logs for 14 days.",
                "reason": "manual update before conflict review",
                "source_refs": [{"source_type": "manual", "source_id": "stale-update"}],
            },
            headers=headers,
        )
        stale_resolution = client.post(
            f"/v1/suggestions/{suggestion['id']}/resolve-conflict",
            json={
                "action": "replace_existing_fact",
                "reason": "try to apply stale conflict review",
            },
            headers=headers,
        )
        still_pending = _list_suggestions(
            client,
            headers=headers,
            space_slug="capture-conflict-stale",
        )

    assert existing.status_code == 201
    assert updated.status_code == 200
    assert stale_resolution.status_code == 409
    assert still_pending.json()["data"][0]["status"] == "pending"


def _capture_app(tmp_path: Path, database_name: str, capture_mode: CaptureMode):
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / database_name}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            capture_mode=capture_mode,
        )
    )


def _create_fact(
    client: TestClient,
    *,
    headers: dict[str, str],
    text: str,
    space_slug: str,
    source_id: str = "semantic-dedupe-test",
):
    return client.post(
        "/v1/facts",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
        headers=headers,
    )


def _create_capture(
    client: TestClient,
    *,
    headers: dict[str, str],
    text: str,
    space_slug: str,
):
    return client.post(
        "/v1/captures",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "source_agent": "codex",
            "source_kind": "hook",
            "event_type": "UserPromptSubmit",
            "actor_role": "user",
            "source_event_id": text,
            "text": text,
            "trust_level": "high",
            "source_authority": "explicit_user_command",
            "sensitivity": "low",
            "consolidate": True,
        },
        headers=headers,
    )


def _candidate(
    text: str,
    *,
    confidence: Confidence = Confidence.MEDIUM,
    ttl_policy: str = "review",
    source_id: str = "semantic-dedupe-test",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        text=text,
        kind=MemoryKind.NOTE,
        confidence=confidence,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id=source_id,
                quote_preview=text,
            ),
        ),
        safe_reason="semantic dedupe test",
        operation_hint=CandidateOperation.ADD,
        tags=("test",),
        ttl_policy=ttl_policy,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _consolidate(
    client: TestClient,
    *,
    capture_id: str,
    extractor: StaticExtractor,
    auto_apply_safe_enabled: bool,
):
    container = client.app.state.container
    use_case = ConsolidateCaptureUseCase(
        uow_factory=container.uow_factory,
        clock=container.clock,
        ids=container.ids,
        extractor=extractor,
        auto_apply_safe_enabled=auto_apply_safe_enabled,
    )
    return asyncio.run(use_case.execute(ConsolidateCaptureCommand(capture_id=capture_id)))


def _list_facts(client: TestClient, *, headers: dict[str, str], space_slug: str):
    return _list_facts_with_status(
        client,
        headers=headers,
        space_slug=space_slug,
        status_filter="active",
    )


def _list_facts_with_status(
    client: TestClient,
    *,
    headers: dict[str, str],
    space_slug: str,
    status_filter: str,
):
    return client.get(
        "/v1/facts",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": status_filter,
        },
        headers=headers,
    )


def _list_suggestions(client: TestClient, *, headers: dict[str, str], space_slug: str):
    return client.get(
        "/v1/suggestions",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "status": "pending",
        },
        headers=headers,
    )
