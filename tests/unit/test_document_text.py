from __future__ import annotations

import pytest
from infinity_context_core.application.document_text import (
    document_chunk_retrieval_text,
    projected_document_retrieval_text,
)


def test_document_chunk_retrieval_text_includes_bounded_multimodal_hints() -> None:
    text = document_chunk_retrieval_text(
        text="Image asset evidence for screenshot.",
        metadata={
            "asset_filename": "memory-screenshot.png",
            "normalized_content_type": "image/png",
            "parser_name": "image_metadata",
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "kind": "vision_region",
                    "bbox": [0, 0, 120, 40],
                }
            ],
        },
        title="memory-screenshot.png",
    )

    assert text.startswith("memory-screenshot.png\n\nImage asset evidence")
    assert "Retrieval hints:" in text
    assert "filename: memory-screenshot.png" in text
    assert "normalized content type: image/png" in text
    assert "parser name: image_metadata" in text
    assert "image evidence" in text
    assert "kind: vision_region" in text
    assert "bbox image region" in text


def test_document_chunk_retrieval_text_preserves_time_range_and_transcript_hints() -> None:
    text = document_chunk_retrieval_text(
        text="Alex mentioned the Atlas launch.",
        metadata={
            "normalized_content_type": "audio/mpeg",
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "kind": "transcript_segment",
                    "time_start_ms": 1000,
                    "time_end_ms": 6500,
                }
            ],
        },
    )

    assert "audio transcript evidence" in text
    assert "kind: transcript_segment" in text
    assert "time range transcript segment" in text


def test_document_chunk_retrieval_text_drops_sensitive_hint_keys_and_values() -> None:
    text = document_chunk_retrieval_text(
        text="Safe visible text.",
        metadata={
            "title": "Safe title",
            "api_key": "sk-proj-secretsecretsecret",
            "parser_name": "Bearer abcdefghijklmnop",
            "asset_filename": "safe.png",
            "source_refs": [
                {
                    "source_type": "asset_extraction",
                    "kind": "ocr_text",
                    "authorization": "Bearer abcdefghijklmnop",
                }
            ],
        },
    )

    assert "Safe title" in text
    assert "filename: safe.png" in text
    assert "asset_extraction" in text
    assert "ocr_text" in text
    assert "sk-proj" not in text
    assert "Bearer" not in text
    assert "[redacted]" not in text
    assert "api key" not in text.lower()
    assert "authorization" not in text.lower()


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("  Project TITLE  ", "  Body\n with\tspaces  ", "project title body with spaces"),
        ("Title", "TITLE repeated in body", "title repeated in body"),
        ("Title", "", "title"),
        ("", "Body", "body"),
    ],
)
def test_projected_document_text_is_normalized_explicit_title_and_body(
    title: str, body: str, expected: str
) -> None:
    assert projected_document_retrieval_text(text=body, title=title) == expected
