"""Public source-ref serialization helpers."""

from __future__ import annotations

from typing import Any

from memo_stack_server.api.public_payload import safe_public_text


def source_ref_to_response(ref: object) -> dict[str, Any]:
    quote_preview = getattr(ref, "quote_preview", None)
    return {
        "source_type": getattr(ref, "source_type", ""),
        "source_id": getattr(ref, "source_id", ""),
        "chunk_id": getattr(ref, "chunk_id", None),
        "char_start": getattr(ref, "char_start", None),
        "char_end": getattr(ref, "char_end", None),
        "quote_preview": safe_public_text(quote_preview) if quote_preview else None,
        "page_number": getattr(ref, "page_number", None),
        "time_start_ms": getattr(ref, "time_start_ms", None),
        "time_end_ms": getattr(ref, "time_end_ms", None),
        "bbox": _bbox_to_response(getattr(ref, "bbox", None)),
    }


def _bbox_to_response(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None
