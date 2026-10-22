from dataclasses import replace
from hashlib import sha256

import pytest

from infinity_context_core.features.document_ingestion.public import (
    LegacyDocumentFragmentEvidence,
    document_content_digest,
    document_fragment_span_is_valid,
    legacy_document_content_digest,
    proves_legacy_document_source,
)


def test_document_digest_preserves_case_indentation_and_literal_whitespace() -> None:
    for left, right in (
        ("return UserID", "return userid"),
        ("if x:\n    return 1\nreturn 2", "if x:\n    return 1\n    return 2"),
        ('label = "a  b"', 'label = "a b"'),
    ):
        assert legacy_document_content_digest(left) == legacy_document_content_digest(right)
        assert document_content_digest(left) != document_content_digest(right)
    assert document_content_digest("x\r\n    y") == document_content_digest("x\n    y")


def test_document_digest_namespace_cannot_be_legacy_lowercased_source() -> None:
    text = "hello"
    naive_prefix = "document-content-v2\0"
    naive_digest = sha256((naive_prefix + text).encode()).hexdigest()
    assert legacy_document_content_digest(naive_prefix + text) == naive_digest
    assert (
        document_content_digest(text) == sha256(b"INFINITY-DOCUMENT-CONTENT-V2\0hello").hexdigest()
    )
    assert document_content_digest(text) != legacy_document_content_digest(naive_prefix + text)
    assert document_content_digest(text) != legacy_document_content_digest(
        "INFINITY-DOCUMENT-CONTENT-V2\0" + text
    )


@pytest.mark.parametrize(
    "fragments",
    (
        (),
        (LegacyDocumentFragmentEvidence("return UserID", 1, 0, 13),),
        (LegacyDocumentFragmentEvidence("return UserID", 0, 1, 14),),
        (LegacyDocumentFragmentEvidence("return userid", 0, 0, 13),),
        (LegacyDocumentFragmentEvidence("return UserID", 0, 0, 12),),
        (
            LegacyDocumentFragmentEvidence("return UserID", 0, 0, 13),
            LegacyDocumentFragmentEvidence("return UserID", 0, 0, 13),
        ),
    ),
)
def test_legacy_source_requires_one_complete_exact_span(fragments) -> None:
    assert not proves_legacy_document_source(
        text="return UserID",
        persisted_hash=legacy_document_content_digest("return UserID"),
        fragments=fragments,
    )


def test_legacy_source_proof_rejects_lost_heading_and_stale_hash() -> None:
    text = "return UserID"
    fragment = LegacyDocumentFragmentEvidence(text, 0, 0, len(text))
    assert proves_legacy_document_source(
        text=text, persisted_hash=legacy_document_content_digest(text), fragments=(fragment,)
    )
    assert not proves_legacy_document_source(
        text=text, persisted_hash="f" * 64, fragments=(fragment,)
    )
    source = "# Build Protocol\nDecision: Keep SQLite"
    lossy = replace(fragment, text="Decision: Keep SQLite", char_start=17, char_end=len(source))
    assert not proves_legacy_document_source(
        text=source,
        persisted_hash=legacy_document_content_digest(source),
        fragments=(lossy,),
    )


@pytest.mark.parametrize(
    "start,end", ((-1, 10), (10, 0), (0, 2), (True, 10), (0, False), (0.0, 10), (0, "10"))
)
def test_fragment_spans_reject_impossible_ranges(start, end) -> None:
    assert not document_fragment_span_is_valid(text="body", char_start=start, char_end=end)


def test_fragment_spans_preserve_valid_absolute_offsets_and_trimming() -> None:
    assert document_fragment_span_is_valid(text="body", char_start=17, char_end=21)
    assert document_fragment_span_is_valid(text="body", char_start=17, char_end=24)
