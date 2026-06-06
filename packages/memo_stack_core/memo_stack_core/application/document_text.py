"""Document chunk text helpers for retrieval-facing projections."""

from __future__ import annotations

from collections.abc import Mapping


def document_chunk_retrieval_text(
    *,
    text: str,
    metadata: Mapping[str, object] | None = None,
    title: str | None = None,
) -> str:
    """Return chunk text with document title included for search and recall."""
    body = text.strip()
    resolved_title = (title or _title_from_metadata(metadata) or "").strip()
    if not resolved_title:
        return body
    if _body_already_starts_with_title(body, resolved_title):
        return body
    return f"{resolved_title}\n\n{body}" if body else resolved_title


def _title_from_metadata(metadata: Mapping[str, object] | None) -> str | None:
    if not metadata:
        return None
    title = metadata.get("title")
    return title if isinstance(title, str) else None


def _body_already_starts_with_title(body: str, title: str) -> bool:
    normalized_body = " ".join(body.casefold().split())
    normalized_title = " ".join(title.casefold().split())
    return bool(normalized_title and normalized_body.startswith(normalized_title))
