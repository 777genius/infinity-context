"""Document chunk text helpers for retrieval-facing projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from infinity_context_core.application.normalize import normalize_text
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.application.sensitive_text import contains_sensitive_text

_MAX_HINTS = 24
_MAX_HINT_VALUE_CHARS = 120
_MAX_HINT_LINE_CHARS = 700
_MAX_SOURCE_REF_HINTS = 12
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
)
_SCALAR_HINT_KEYS = (
    "asset_filename",
    "filename",
    "title",
    "asset_content_type",
    "content_type",
    "normalized_content_type",
    "source_kind",
    "source_type",
    "parser_profile",
    "parser_name",
    "language",
    "node_kind",
    "heading",
)
_LIST_HINT_KEYS = (
    "modalities",
    "evidence_modalities",
    "evidence_kinds",
    "primary_artifact_types",
    "transcript_features",
    "vision_features",
)
_TRUE_FLAG_HINTS = {
    "evidence_has_page_ref": "page evidence",
    "evidence_has_bbox_ref": "bbox image region",
    "evidence_has_time_range_ref": "time range evidence",
}


def projected_document_retrieval_text(*, text: str, title: str) -> str:
    """Canonical projected embedding text: normalized explicit title and body only.

    Projection metadata and source citations remain structured data; they must not
    add embedding tokens after a caller has budgeted the title and body.
    """
    return normalize_text(document_chunk_retrieval_text(text=text, title=title))


def document_chunk_retrieval_text(
    *,
    text: str,
    metadata: Mapping[str, object] | None = None,
    title: str | None = None,
) -> str:
    """Return chunk text enriched with safe retrieval-only metadata hints."""
    body = text.strip()
    resolved_title = (title or _title_from_metadata(metadata) or "").strip()
    parts: list[str] = []
    if resolved_title and not _body_already_starts_with_title(body, resolved_title):
        parts.append(resolved_title)
    if body:
        parts.append(body)
    hints = _retrieval_hints(metadata)
    if hints:
        parts.append(f"Retrieval hints: {'; '.join(hints)[:_MAX_HINT_LINE_CHARS]}")
    return "\n\n".join(parts)


def _title_from_metadata(metadata: Mapping[str, object] | None) -> str | None:
    if not metadata:
        return None
    title = metadata.get("title")
    return title if isinstance(title, str) else None


def _body_already_starts_with_title(body: str, title: str) -> bool:
    normalized_body = " ".join(body.casefold().split())
    normalized_title = " ".join(title.casefold().split())
    return bool(normalized_title and normalized_body.startswith(normalized_title))


def _retrieval_hints(metadata: Mapping[str, object] | None) -> list[str]:
    if not metadata:
        return []
    hints: list[str] = []
    seen: set[str] = set()
    for key in _SCALAR_HINT_KEYS:
        _add_scalar_hint(hints, seen, key=key, value=metadata.get(key))
    for key in _LIST_HINT_KEYS:
        _add_iterable_hints(hints, seen, values=_iterable_metadata_values(metadata.get(key)))
    for key, hint in _TRUE_FLAG_HINTS.items():
        if metadata.get(key) is True:
            _add_hint(hints, seen, hint)
    _add_content_type_hints(hints, seen, metadata)
    _add_source_ref_hints(hints, seen, metadata)
    return hints[:_MAX_HINTS]


def _add_scalar_hint(
    hints: list[str],
    seen: set[str],
    *,
    key: str,
    value: object,
) -> None:
    if not isinstance(value, str):
        return
    if _looks_sensitive_key(key) or contains_sensitive_text(value):
        return
    safe_value = safe_metadata_text(value, limit=_MAX_HINT_VALUE_CHARS).strip()
    if not safe_value or "[redacted]" in safe_value:
        return
    _add_hint(hints, seen, f"{_hint_label(key)}: {safe_value}")


def _add_iterable_hints(
    hints: list[str],
    seen: set[str],
    *,
    values: Iterable[object],
) -> None:
    for value in values:
        if not isinstance(value, str) or contains_sensitive_text(value):
            continue
        safe_value = safe_metadata_text(value, limit=_MAX_HINT_VALUE_CHARS).strip()
        if safe_value and "[redacted]" not in safe_value:
            _add_hint(hints, seen, safe_value)


def _add_content_type_hints(
    hints: list[str],
    seen: set[str],
    metadata: Mapping[str, object],
) -> None:
    raw = metadata.get("normalized_content_type") or metadata.get("asset_content_type")
    if not isinstance(raw, str):
        return
    content_type = raw.strip().lower()
    if content_type.startswith("image/"):
        _add_hint(hints, seen, "image evidence")
    elif content_type.startswith("audio/"):
        _add_hint(hints, seen, "audio transcript evidence")
    elif content_type.startswith("video/"):
        _add_hint(hints, seen, "video keyframe transcript evidence")
    elif content_type in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        _add_hint(hints, seen, "document page evidence")


def _add_source_ref_hints(
    hints: list[str],
    seen: set[str],
    metadata: Mapping[str, object],
) -> None:
    refs = metadata.get("source_refs")
    if not isinstance(refs, (list, tuple)):
        return
    for ref in refs[:_MAX_SOURCE_REF_HINTS]:
        if not isinstance(ref, Mapping):
            continue
        _add_scalar_hint(hints, seen, key="source_type", value=ref.get("source_type"))
        _add_scalar_hint(hints, seen, key="kind", value=ref.get("kind"))
        if ref.get("page_number") is not None:
            _add_hint(hints, seen, "page evidence")
        if ref.get("bbox") is not None:
            _add_hint(hints, seen, "bbox image region")
        if ref.get("time_start_ms") is not None or ref.get("time_end_ms") is not None:
            _add_hint(hints, seen, "time range transcript segment")


def _add_hint(hints: list[str], seen: set[str], hint: str) -> None:
    normalized = " ".join(hint.casefold().split())
    if not normalized or normalized in seen or len(hints) >= _MAX_HINTS:
        return
    seen.add(normalized)
    hints.append(hint)


def _iterable_metadata_values(value: object) -> Iterable[object]:
    if isinstance(value, (list, tuple, set)):
        return value
    return ()


def _hint_label(key: str) -> str:
    return key.removeprefix("asset_").replace("_", " ")


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)
