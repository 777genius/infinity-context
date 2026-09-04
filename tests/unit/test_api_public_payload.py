from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_core.domain.entities import SourceRef
from infinity_context_server.api.public_payload import safe_public_metadata
from infinity_context_server.api.v1.anchors import anchor_to_response
from infinity_context_server.api.v1.context import (
    _answer_support_to_response,
    _context_diagnostics_to_response,
    _top_evidence_to_response,
    context_item_to_response,
)
from infinity_context_server.api.v1.context_links import (
    context_link_suggestion_to_response,
    context_link_to_response,
)
from infinity_context_server.api.v1.digest import digest_to_response
from infinity_context_server.api.v1.documents import chunk_to_response
from infinity_context_server.api.v1.facts import fact_relation_to_response, fact_to_response
from infinity_context_server.api.v1.suggestions import suggestion_to_response


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
                "_retrieval_projection_contract": {"locator": "internal-contract"},
                "_canonical_retrieval_projection": {"locator": "internal-canonical"},
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
            diagnostics={
                "retrieval_source": "vector_chunks",
                "api_key": raw_secret,
                "debug": f"Authorization: Bearer {raw_secret}",
                "provenance": {"token": raw_secret, "provider": "local-test"},
            },
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
    assert "_retrieval_projection_contract" not in chunk["metadata"]
    assert "_canonical_retrieval_projection" not in chunk["metadata"]
    assert "[redacted]" in context_item["source_refs"][0]["quote_preview"]
    assert "api_key" not in context_item["diagnostics"]
    assert "token" not in context_item["diagnostics"]["provenance"]


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
                        "approved_override": True,
                        "original_target_type": "fact",
                        "original_target_id": f"fact_original_{index}",
                        "approved_target_type": "anchor",
                        "approved_target_id": f"anchor_{index}",
                        "approved_relation_type": "mentions",
                        "approved_link_reason": f"approved link reason Bearer {raw_secret}",
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
    assert response["review_audit"]["events"][0]["approved_override"] is True
    assert response["review_audit"]["events"][0]["approved_target_id"] == "anchor_2"
    assert response["review_audit"]["events"][0]["approved_link_reason"] == "[redacted]"
    assert "authorization" not in response["review_audit"]["events"][0]
    assert "api_key" not in response["metadata"]
    assert raw_secret not in rendered
    assert "[redacted]" in rendered


def test_digest_serializer_redacts_public_topic_markdown_and_diagnostics() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    enum = SimpleNamespace

    response = digest_to_response(
        SimpleNamespace(
            digest_id="dig_1",
            topic=f"Review Bearer {raw_secret}",
            rendered_markdown=f"# Active facts\n\nLeak Authorization: Bearer {raw_secret}",
            sections=[
                SimpleNamespace(
                    title=f"token {raw_secret}",
                    items=[
                        SimpleNamespace(
                            item_id="fact_1",
                            item_type="fact",
                            diagnostics={
                                "retrieval_source": "postgres_facts",
                                "authorization": f"Bearer {raw_secret}",
                            },
                            text="safe fact",
                            score=0.9,
                            source_refs=[
                                SimpleNamespace(
                                    source_type="manual",
                                    source_id="src_1",
                                    chunk_id=None,
                                    char_start=None,
                                    char_end=None,
                                    quote_preview=f"Bearer {raw_secret}",
                                )
                            ],
                            is_instruction=False,
                        )
                    ],
                    truncated=False,
                )
            ],
            source_refs=[
                enum(
                    source_type="manual",
                    source_id="src_1",
                    chunk_id=None,
                    char_start=None,
                    char_end=None,
                    quote_preview=f"Bearer {raw_secret}",
                )
            ],
            token_estimate=64,
            diagnostics={
                "evidence_only": True,
                "api_key": raw_secret,
                "provider_response": f"Bearer {raw_secret}",
            },
        )
    )

    rendered = json.dumps(response, sort_keys=True)

    assert raw_secret not in rendered
    assert "[redacted]" in rendered
    assert "api_key" not in response["diagnostics"]
    assert response["sections"][0]["items"][0]["diagnostics"]["retrieval_source"] == (
        "postgres_facts"
    )


def test_context_diagnostics_preserve_public_evidence_contract_counters() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    diagnostics = {
        **{f"safe_counter_{index}": index for index in range(150)},
        "items_with_evidence_kind": 2,
        "items_with_evidence_modality": 1,
        "api_key": raw_secret,
        "debug": f"Bearer {raw_secret}",
    }

    response = _context_diagnostics_to_response(diagnostics, items=[], top_evidence=[])
    rendered = json.dumps(response, sort_keys=True)

    assert response["items_with_evidence_kind"] == 2
    assert response["items_with_evidence_modality"] == 1
    assert "api_key" not in response
    assert raw_secret not in rendered
    assert "[redacted]" in rendered


def test_answer_support_excludes_review_only_and_stale_items() -> None:
    citation = {
        "citation_id": "chunk:active:citation:1",
        "source_type": "document",
        "source_id": "doc_1",
        "chunk_id": "chunk_1",
        "quote_preview": "Atlas decision evidence",
        "char_range": {"start": 0, "end": 24},
    }
    items = [
        {
            "item_id": "active",
            "item_type": "chunk",
            "score": 0.91,
            "citations": [citation],
            "diagnostics": {
                "retrieval_source": "keyword_chunks",
                "retrieval_sources": ["keyword_chunks"],
            },
        },
        {
            "item_id": "review",
            "item_type": "fact",
            "score": 0.99,
            "citations": [{**citation, "citation_id": "fact:review:citation:1"}],
            "diagnostics": {
                "retrieval_source": "pending_conflict_suggestion",
                "retrieval_sources": ["pending_conflict_suggestion"],
                "review_only": True,
            },
        },
        {
            "item_id": "stale",
            "item_type": "fact",
            "score": 0.98,
            "citations": [{**citation, "citation_id": "fact:stale:citation:1"}],
            "diagnostics": {
                "retrieval_source": "superseded_review",
                "retrieval_sources": ["superseded_review"],
                "stale_reason": "fact_status_superseded",
            },
        },
    ]

    top_evidence = _top_evidence_to_response(items)
    answer_support = _answer_support_to_response(
        items=items,
        top_evidence=top_evidence,
    )
    diagnostics = _context_diagnostics_to_response(
        {},
        items=items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )

    assert [item["item_id"] for item in top_evidence] == ["active"]
    assert answer_support["status"] == "partial"
    assert answer_support["coverage"]["supported_item_ratio"] == 0.3333
    assert answer_support["warnings"] == [
        "low_supported_item_ratio",
        "review_only_items_excluded",
        "stale_items_excluded",
    ]
    assert diagnostics["answer_support_status"] == "partial"
    assert diagnostics["answer_support_items_returned"] == 1
    assert diagnostics["answer_support_cited_count"] == 1
    assert diagnostics["answer_support_precise_location_count"] == 1
    assert diagnostics["answer_support_warnings"] == answer_support["warnings"]


def test_answer_support_reports_evidence_breakdown_for_frontend_review() -> None:
    items = [
        {
            "item_id": "audio_segment",
            "item_type": "extraction_artifact",
            "score": 0.92,
            "citations": [
                {
                    "citation_id": "artifact:audio:citation:1",
                    "source_type": "extraction_artifact",
                    "source_id": "artifact_audio",
                    "chunk_id": "segment_1",
                    "quote_preview": "Alex confirmed Atlas renewal.",
                    "time_range_ms": {"start": 1200, "end": 5400},
                    "evidence_kind": "transcript_segment",
                    "evidence_modality": "audio",
                }
            ],
            "diagnostics": {
                "retrieval_source": "artifact_evidence",
                "retrieval_sources": ["artifact_evidence", "keyword_chunks"],
            },
        },
        {
            "item_id": "image_region",
            "item_type": "extraction_artifact",
            "score": 0.88,
            "citations": [
                {
                    "citation_id": "artifact:image:citation:1",
                    "source_type": "extraction_artifact",
                    "source_id": "artifact_image",
                    "quote_preview": "OCR text says Atlas threshold.",
                    "bbox": [0.0, 0.0, 120.0, 40.0],
                    "evidence_kind": "ocr_region",
                    "evidence_modality": "image",
                }
            ],
            "diagnostics": {"retrieval_source": "artifact_evidence"},
        },
        {
            "item_id": "document_page",
            "item_type": "chunk",
            "score": 0.84,
            "citations": [
                {
                    "citation_id": "chunk:doc:citation:1",
                    "source_type": "document",
                    "source_id": "doc_1",
                    "quote_preview": "Document says Atlas renewal.",
                    "page_number": 2,
                    "evidence_kind": "document_page",
                    "evidence_modality": "document",
                }
            ],
            "diagnostics": {"retrieval_source": "keyword_chunks"},
        },
    ]

    top_evidence = _top_evidence_to_response(items, limit=3)
    answer_support = _answer_support_to_response(
        items=items,
        top_evidence=top_evidence,
        limit=3,
    )
    diagnostics = _context_diagnostics_to_response(
        {},
        items=items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )

    coverage = answer_support["coverage"]
    assert coverage["supported_item_types"] == {"chunk": 1, "extraction_artifact": 2}
    assert coverage["support_source_types"] == {
        "document": 1,
        "extraction_artifact": 2,
    }
    assert coverage["support_evidence_kinds"] == {
        "document_page": 1,
        "ocr_region": 1,
        "transcript_segment": 1,
    }
    assert coverage["support_evidence_modalities"] == {
        "audio": 1,
        "document": 1,
        "image": 1,
    }
    assert coverage["location_support_counts"] == {
        "bbox": 1,
        "char_range": 0,
        "page_number": 1,
        "time_range_ms": 1,
    }
    assert coverage["source_type_count"] == 2
    assert coverage["evidence_kind_count"] == 3
    assert coverage["evidence_modality_count"] == 3
    assert diagnostics["answer_support_source_type_count"] == 2
    assert diagnostics["answer_support_evidence_kind_count"] == 3
    assert diagnostics["answer_support_evidence_modality_count"] == 3


def test_answer_support_reports_missing_critical_query_requirement() -> None:
    citation = {
        "citation_id": "artifact:image:citation:1",
        "source_type": "asset_extraction",
        "source_id": "artifact_image",
        "quote_preview": "OCR text says Atlas owner.",
        "evidence_kind": "ocr_region",
        "evidence_modality": "image",
    }
    items = [
        {
            "item_id": "image_text",
            "item_type": "extraction_artifact",
            "score": 0.94,
            "citations": [citation],
            "diagnostics": {"retrieval_source": "artifact_evidence"},
        }
    ]

    top_evidence = _top_evidence_to_response(items)
    answer_support = _answer_support_to_response(
        items=items,
        top_evidence=top_evidence,
        diagnostics={
            "context_requirement_coverage": {
                "missing_total": 1,
                "missing_evidence_features": ["visual_region"],
            }
        },
    )
    diagnostics = _context_diagnostics_to_response(
        {},
        items=items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )

    assert answer_support["status"] == "missing"
    assert "explicit_requirements_missing" in answer_support["warnings"]
    assert "missing_visual_region_requirement" in answer_support["warnings"]
    assert diagnostics["answer_support_status"] == "missing"
    assert "missing_visual_region_requirement" in diagnostics["answer_support_warnings"]


def test_answer_support_reports_missing_extracted_text_as_critical_requirement() -> None:
    citation = {
        "citation_id": "artifact:image:citation:1",
        "source_type": "asset",
        "source_id": "asset_screenshot",
        "quote_preview": None,
        "evidence_kind": "image_metadata",
        "evidence_modality": "image",
    }
    items = [
        {
            "item_id": "image_metadata",
            "item_type": "extraction_artifact",
            "score": 0.92,
            "citations": [citation],
            "diagnostics": {"retrieval_source": "artifact_evidence"},
        }
    ]

    top_evidence = _top_evidence_to_response(items)
    answer_support = _answer_support_to_response(
        items=items,
        top_evidence=top_evidence,
        diagnostics={
            "context_requirement_coverage": {
                "missing_total": 1,
                "missing_evidence_features": ["extracted_text"],
            }
        },
    )

    assert answer_support["status"] == "missing"
    assert "missing_extracted_text_requirement" in answer_support["warnings"]


def test_answer_support_reports_partial_for_missing_noncritical_requirement() -> None:
    citation = {
        "citation_id": "fact:atlas:citation:1",
        "source_type": "fact",
        "source_id": "fact_atlas",
        "quote_preview": "Atlas renewal was approved by Alex.",
        "char_range": {"start": 0, "end": 35},
    }
    items = [
        {
            "item_id": "fact_atlas",
            "item_type": "fact",
            "score": 0.95,
            "citations": [citation],
            "diagnostics": {"retrieval_source": "postgres_facts"},
        }
    ]

    answer_support = _answer_support_to_response(
        items=items,
        top_evidence=_top_evidence_to_response(items),
        diagnostics={
            "context_requirement_coverage": {
                "missing_total": 1,
                "missing_anchor_kinds": ["person"],
            }
        },
    )

    assert answer_support["status"] == "partial"
    assert "explicit_requirements_missing" in answer_support["warnings"]
    assert "missing_person_anchor_requirement" in answer_support["warnings"]


def test_memory_suggestion_review_audit_is_bounded_and_redacted() -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    enum = SimpleNamespace

    response = suggestion_to_response(
        SimpleNamespace(
            id="sug_1",
            space_id="space_1",
            memory_scope_id="scope_1",
            candidate_text="Safe candidate text",
            kind=enum(value="note"),
            operation=enum(value="add"),
            status=enum(value="approved"),
            source_refs=[
                SimpleNamespace(
                    source_type="manual",
                    source_id="https://user:password@example.com/private",
                    chunk_id=f"chunk-{raw_secret}",
                    char_start=None,
                    char_end=None,
                    quote_preview=f"Bearer {raw_secret}",
                )
            ],
            confidence=enum(value="medium"),
            trust_level=enum(value="medium"),
            safe_reason=f"candidate reason with Bearer {raw_secret}",
            target_fact_id="fact_1",
            target_fact_version=1,
            category=None,
            tags=(),
            ttl_policy=None,
            expires_at=None,
            expiry_reason=None,
            created_from_capture_id="capture_1",
            candidate_fingerprint=None,
            review_payload={
                "debug": f"Bearer {raw_secret}",
                "review_events": [
                    {
                        "event_type": "memory_suggestion_reviewed",
                        "suggestion_id": f"sug_{index}",
                        "space_id": "space_1",
                        "memory_scope_id": "scope_1",
                        "operation": "add",
                        "action": "approve",
                        "previous_status": "pending",
                        "new_status": "approved",
                        "reviewed_at": now.isoformat(),
                        "target_fact_id": "fact_1",
                        "target_fact_version": 1,
                        "created_from_capture_id": "capture_1",
                        "reason": f"approved with Bearer {raw_secret}",
                        "authorization": f"Bearer {raw_secret}",
                    }
                    for index in range(12)
                ],
            },
            review_reason=f"reviewed with Bearer {raw_secret}",
            created_at=now,
            updated_at=now,
            reviewed_at=now,
        )
    )
    rendered = json.dumps(response, sort_keys=True)

    assert response["review_audit"]["event_count"] == 12
    assert response["review_audit"]["truncated"] is True
    assert len(response["review_audit"]["events"]) == 10
    assert response["review_audit"]["events"][0]["suggestion_id"] == "sug_2"
    assert "authorization" not in response["review_audit"]["events"][0]
    assert response["review_reason"] == "[redacted]"
    assert response["safe_reason"] == "[redacted]"
    assert response["source_refs"][0]["source_id"] == ("https://[redacted]@example.com/private")
    assert response["source_refs"][0]["chunk_id"] == "chunk-[redacted]"
    assert raw_secret not in rendered
    assert "user:password" not in rendered
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


def test_context_item_response_redacts_sensitive_source_ref_identities() -> None:
    raw_secret = "sk-proj-sourceidentitysecret1234567890"

    response = context_item_to_response(
        SimpleNamespace(
            item_id="chunk_sensitive_source_identity",
            item_type="chunk",
            diagnostics={"retrieval_source": "keyword_chunks"},
            text="safe chunk text",
            score=1.0,
            source_refs=[
                SimpleNamespace(
                    source_type="document",
                    source_id="https://user:password@example.com/private",
                    chunk_id=f"chunk-{raw_secret}",
                    quote_preview="safe quote",
                )
            ],
            is_instruction=False,
        )
    )

    rendered = json.dumps(response, sort_keys=True)

    assert response["source_refs"][0]["source_id"] == ("https://[redacted]@example.com/private")
    assert response["source_refs"][0]["chunk_id"] == "chunk-[redacted]"
    assert "https://[redacted]@example.com/private" in response["citations"][0]["label"]
    assert raw_secret not in rendered
    assert "user:password" not in rendered
    assert "sk-proj-sourceidentitysecret" not in rendered


def test_context_item_response_sanitizes_invalid_source_ref_coordinates() -> None:
    response = context_item_to_response(
        SimpleNamespace(
            item_id="chunk_invalid_coordinates",
            item_type="chunk",
            diagnostics={"retrieval_source": "keyword_chunks"},
            text="safe chunk text",
            score=1.0,
            source_refs=[
                SimpleNamespace(
                    source_type="document",
                    source_id="doc_1",
                    chunk_id="chunk_1",
                    char_start=50,
                    char_end=10,
                    page_number=0,
                    time_start_ms=5000,
                    time_end_ms=1000,
                    bbox=(-1.0, 2.0, 3.0, 4.0),
                    quote_preview="safe quote",
                )
            ],
            is_instruction=False,
        )
    )

    source_ref = response["source_refs"][0]
    citation = response["citations"][0]
    assert source_ref["char_start"] is None
    assert source_ref["char_end"] is None
    assert source_ref["page_number"] is None
    assert source_ref["time_start_ms"] is None
    assert source_ref["time_end_ms"] is None
    assert source_ref["bbox"] is None
    assert citation["char_range"] is None
    assert citation["page_number"] is None
    assert citation["time_range_ms"] is None
    assert citation["bbox"] is None
    assert "bbox" not in citation["label"]
    assert "5000" not in citation["label"]
    assert "p.0" not in citation["label"]
