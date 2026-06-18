from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from memo_stack_core.domain.entities import SourceRef
from memo_stack_server.api.public_payload import safe_public_metadata
from memo_stack_server.api.v1.anchors import anchor_to_response
from memo_stack_server.api.v1.context import context_item_to_response
from memo_stack_server.api.v1.context_links import (
    context_link_suggestion_to_response,
    context_link_to_response,
)
from memo_stack_server.api.v1.documents import chunk_to_response
from memo_stack_server.api.v1.facts import fact_relation_to_response, fact_to_response


def test_safe_public_metadata_redacts_nested_sensitive_values() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"

    metadata = safe_public_metadata(
        {
            "api_key": raw_secret,
            "debug": f"Authorization: Bearer {raw_secret}",
            raw_secret: "secret key must not leak",
            "edit_events": [
                {
                    "source": f"Bearer {raw_secret}",
                    "changed_fields": ["reason"],
                    "previous": {"reason": f"old {raw_secret}", "token": raw_secret},
                }
            ],
            "review_events": [
                {
                    "event_type": "context_link_suggestion_reviewed",
                    "suggestion_id": "ctxlinksug_1",
                    "source_type": "capture",
                    "source_id": "capture_1",
                    "target_type": "fact",
                    "target_id": "fact_1",
                    "reason": f"approved after checking Bearer {raw_secret}",
                    "authorization": f"Bearer {raw_secret}",
                }
            ],
            "numbers": [1, f"password={raw_secret}"],
        }
    )
    rendered = json.dumps(metadata, sort_keys=True)

    assert "api_key" not in metadata
    assert raw_secret not in metadata
    assert raw_secret not in rendered
    assert "[redacted]" in rendered
    assert metadata["edit_events"][0]["changed_fields"] == ["reason"]
    assert metadata["review_events"][0]["event_type"] == ("context_link_suggestion_reviewed")
    assert metadata["review_events"][0]["suggestion_id"] == "ctxlinksug_1"
    assert "authorization" not in metadata["review_events"][0]
    assert metadata["numbers"][0] == 1


def test_browser_serializers_redact_metadata_and_quote_previews() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    enum = SimpleNamespace

    chunk = chunk_to_response(
        SimpleNamespace(
            id="chunk_1",
            document_id="doc_1",
            episode_id=None,
            source_type="document",
            source_external_id="doc.md",
            text="safe chunk text",
            kind=enum(value="text"),
            sequence=1,
            char_start=0,
            char_end=15,
            status=enum(value="active"),
            classification="internal",
            metadata={
                "debug": f"Bearer {raw_secret}",
                "source_refs": [{"quote_preview": f"Bearer {raw_secret}"}],
            },
        )
    )
    anchor = anchor_to_response(
        SimpleNamespace(
            id="anchor_1",
            space_id="space_1",
            memory_scope_id="scope_1",
            kind=enum(value="person"),
            normalized_key="alex",
            label="Alex",
            aliases=(),
            description=None,
            status=enum(value="active"),
            confidence=enum(value="high"),
            evidence_refs=[
                SimpleNamespace(
                    source_type="manual",
                    source_id="anchor-note",
                    chunk_id=None,
                    char_start=None,
                    char_end=None,
                    quote_preview=f"Bearer {raw_secret}",
                )
            ],
            observed_at=now,
            valid_from=None,
            valid_to=None,
            metadata={"debug": f"Bearer {raw_secret}", "token": raw_secret},
            created_at=now,
            updated_at=now,
        )
    )
    link = context_link_to_response(
        SimpleNamespace(
            id="link_1",
            space_id="space_1",
            memory_scope_id="scope_1",
            source_type="chunk",
            source_id="chunk_1",
            target_type="anchor",
            target_id="anchor_1",
            relation_type="mentions",
            confidence=0.9,
            reason="safe reason",
            status=enum(value="active"),
            metadata={"edit_events": [{"source": f"Bearer {raw_secret}"}]},
            created_at=now,
            updated_at=now,
        )
    )
    context_item = context_item_to_response(
        SimpleNamespace(
            item_id="chunk_1",
            item_type="chunk",
            diagnostics={},
            text="safe chunk text",
            score=1.0,
            source_refs=[
                SimpleNamespace(
                    source_type="chunk",
                    source_id="chunk_1",
                    chunk_id=None,
                    char_start=0,
                    char_end=15,
                    quote_preview=f"Bearer {raw_secret}",
                )
            ],
            is_instruction=False,
        )
    )

    rendered = json.dumps(
        {
            "anchor": anchor,
            "chunk": chunk,
            "context_item": context_item,
            "link": link,
        },
        sort_keys=True,
    )

    assert raw_secret not in rendered
    assert "[redacted]" in rendered
    assert "token" not in anchor["metadata"]
    assert "[redacted]" in anchor["evidence_refs"][0]["quote_preview"]
    assert "[redacted]" in chunk["source_refs"][0]["quote_preview"]
    assert "[redacted]" in context_item["source_refs"][0]["quote_preview"]


def test_context_link_suggestion_review_audit_is_bounded_and_redacted() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    enum = SimpleNamespace

    response = context_link_suggestion_to_response(
        SimpleNamespace(
            id="ctxlinksug_1",
            space_id="space_1",
            memory_scope_id="scope_1",
            source_type="capture",
            source_id="capture_1",
            target_type="fact",
            target_id="fact_1",
            relation_type="supports",
            confidence="high",
            reason=f"candidate reason with Bearer {raw_secret}",
            score=96.0,
            status=enum(value="approved"),
            metadata={
                "review_events": [
                    {
                        "event_type": "context_link_suggestion_reviewed",
                        "suggestion_id": f"ctxlinksug_{index}",
                        "source_type": "capture",
                        "source_id": f"capture_{index}",
                        "target_type": "fact",
                        "target_id": f"fact_{index}",
                        "relation_type": "supports",
                        "action": "approve",
                        "previous_status": "pending",
                        "new_status": "approved",
                        "reviewed_at": now.isoformat(),
                        "policy_version": "context-link-policy-v1",
                        "reason": f"approved with Bearer {raw_secret}",
                        "authorization": f"Bearer {raw_secret}",
                    }
                    for index in range(12)
                ],
                "api_key": raw_secret,
            },
            created_at=now,
            updated_at=now,
            reviewed_at=now,
            review_reason=f"reviewed with Bearer {raw_secret}",
        )
    )

    rendered = json.dumps(response, sort_keys=True)

    assert response["review_audit"]["event_count"] == 12
    assert response["review_audit"]["truncated"] is True
    assert len(response["review_audit"]["events"]) == 10
    assert response["review_audit"]["events"][0]["suggestion_id"] == "ctxlinksug_2"
    assert "authorization" not in response["review_audit"]["events"][0]
    assert "api_key" not in response["metadata"]
    assert raw_secret not in rendered
    assert "[redacted]" in rendered


def test_anchor_response_defaults_legacy_lifecycle_fields() -> None:
    created_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    enum = SimpleNamespace

    response = anchor_to_response(
        SimpleNamespace(
            id="anchor_legacy_openai",
            space_id="space_1",
            memory_scope_id="scope_1",
            kind=enum(value="organization"),
            normalized_key="openai",
            label="OpenAI",
            aliases=("Open AI",),
            description=None,
            status=enum(value="active"),
            created_at=created_at,
            updated_at=created_at,
        )
    )

    assert response["confidence"] == "medium"
    assert response["evidence_refs"] == []
    assert response["observed_at"] == created_at.isoformat()
    assert response["valid_from"] is None
    assert response["valid_to"] is None
    assert response["metadata"] == {}


def test_fact_response_exposes_multimodal_source_refs() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    enum = SimpleNamespace

    response = fact_to_response(
        SimpleNamespace(
            id="fact_multimodal",
            space_id="space_1",
            memory_scope_id="scope_1",
            thread_id=None,
            text="Screenshot says Alex approved launch.",
            kind=enum(value="note"),
            status=enum(value="active"),
            version=1,
            confidence=enum(value="high"),
            trust_level=enum(value="medium"),
            classification="internal",
            category=None,
            tags=(),
            ttl_policy=None,
            expires_at=None,
            source_refs=(
                SourceRef(
                    source_type="asset_extraction",
                    source_id="extract_1",
                    chunk_id="chunk_1",
                    page_number=2,
                    time_start_ms=1000,
                    time_end_ms=1500,
                    bbox=(0.0, 1.0, 120.0, 40.0),
                ),
            ),
            created_at=now,
            updated_at=now,
        )
    )

    ref = response["source_refs"][0]
    assert ref["page_number"] == 2
    assert ref["time_start_ms"] == 1000
    assert ref["time_end_ms"] == 1500
    assert ref["bbox"] == [0.0, 1.0, 120.0, 40.0]


def test_fact_relation_response_defaults_legacy_temporal_fields_and_redacts_reason() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    created_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    response = fact_relation_to_response(
        SimpleNamespace(
            id="relation_legacy_supports",
            space_id="space_1",
            memory_scope_id="scope_1",
            source_fact_id="fact_source",
            target_fact_id="fact_target",
            relation_type="supports",
            reason=f"legacy relation checked with Bearer {raw_secret}",
            status="active",
            created_at=created_at,
            updated_at=created_at,
        )
    )

    rendered = json.dumps(response, sort_keys=True)
    assert response["observed_at"] == created_at.isoformat()
    assert response["valid_from"] is None
    assert response["valid_to"] is None
    assert response["relation_type"] == "supports"
    assert response["status"] == "active"
    assert raw_secret not in rendered
    assert "[redacted]" in response["reason"]


def test_context_item_response_bounds_source_refs_with_truncation_diagnostics() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"

    response = context_item_to_response(
        SimpleNamespace(
            item_id="chunk_many_refs",
            item_type="chunk",
            diagnostics={"retrieval_source": "keyword_chunks"},
            text="safe chunk text",
            score=1.0,
            source_refs=[
                SimpleNamespace(
                    source_type="chunk",
                    source_id=f"chunk_{index}",
                    chunk_id=f"chunk_{index}",
                    char_start=index,
                    char_end=index + 1,
                    quote_preview=f"quote with Bearer {raw_secret}",
                )
                for index in range(25)
            ],
            is_instruction=False,
        )
    )

    rendered = json.dumps(response, sort_keys=True)

    assert len(response["source_refs"]) == 20
    assert response["source_refs"][0]["source_id"] == "chunk_0"
    assert response["source_refs"][-1]["source_id"] == "chunk_19"
    assert response["diagnostics"]["source_refs_total"] == 25
    assert response["diagnostics"]["source_refs_returned"] == 20
    assert response["diagnostics"]["source_refs_truncated"] is True
    assert raw_secret not in rendered
    assert "[redacted]" in rendered
