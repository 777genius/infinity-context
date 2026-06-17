from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from memo_stack_server.api.public_payload import safe_public_metadata
from memo_stack_server.api.v1.anchors import anchor_to_response
from memo_stack_server.api.v1.context import context_item_to_response
from memo_stack_server.api.v1.context_links import context_link_to_response
from memo_stack_server.api.v1.documents import chunk_to_response


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
            "numbers": [1, f"password={raw_secret}"],
        }
    )
    rendered = json.dumps(metadata, sort_keys=True)

    assert "api_key" not in metadata
    assert raw_secret not in metadata
    assert raw_secret not in rendered
    assert "[redacted]" in rendered
    assert metadata["edit_events"][0]["changed_fields"] == ["reason"]
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
