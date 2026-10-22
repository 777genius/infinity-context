"""Versioned source identity and conservative proof for legacy document text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from infinity_context_core.features.document_ingestion.domain.source_document import (
    normalize_document_text,
)

_DOCUMENT_CONTENT_V2_PREFIX = b"INFINITY-DOCUMENT-CONTENT-V2\0"
_LEGACY_SPACE = re.compile(r"\s+")


def document_content_digest(text: str) -> str:
    """Hash semantic source bytes in a namespace unreachable by legacy lowercase text."""
    return sha256(
        _DOCUMENT_CONTENT_V2_PREFIX + normalize_document_text(text).encode("utf-8")
    ).hexdigest()


def legacy_document_content_digest(text: str) -> str:
    """Read-only compatibility with the original case/whitespace-folded digest."""
    normalized = _LEGACY_SPACE.sub(" ", text.strip().lower())
    return sha256(normalized.encode("utf-8")).hexdigest()


def document_fragment_span_is_valid(*, text: str, char_start: object, char_end: object) -> bool:
    """Reject intrinsically impossible spans without guessing original source layout."""
    return (
        type(char_start) is int
        and type(char_end) is int
        and char_start >= 0
        and char_end >= char_start
        and char_end - char_start >= len(text)
    )


@dataclass(frozen=True, slots=True)
class LegacyDocumentFragmentEvidence:
    """Source spans whose canonical ownership has already been validated."""

    text: str
    sequence: int
    char_start: int
    char_end: int


def proves_legacy_document_source(
    *,
    text: str,
    persisted_hash: str,
    fragments: tuple[LegacyDocumentFragmentEvidence, ...],
) -> bool:
    """Accept only a complete single span; never infer discarded source or whitespace."""
    if len(fragments) != 1:
        return False
    fragment = fragments[0]
    return (
        fragment.sequence == 0
        and fragment.char_start == 0
        and fragment.char_end == len(fragment.text)
        and persisted_hash == legacy_document_content_digest(text)
        and persisted_hash == legacy_document_content_digest(fragment.text)
        and normalize_document_text(fragment.text) == normalize_document_text(text)
    )


__all__ = (
    "LegacyDocumentFragmentEvidence",
    "document_content_digest",
    "document_fragment_span_is_valid",
    "legacy_document_content_digest",
    "proves_legacy_document_source",
)
