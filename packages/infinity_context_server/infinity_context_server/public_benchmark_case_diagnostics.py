"""Bounded diagnostics for public benchmark cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_source_identity import (
    looks_like_raw_source_ref,
    safe_item_id_for_output,
    safe_source_refs_for_output,
)

_REDACTED_TEXT = "[redacted]"


def preview_value(value: object, *, max_chars: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _safe_preview_text(value, max_chars=max_chars)
    if isinstance(value, int | float | bool):
        return str(value)[:max_chars]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        parts = [
            preview_value(item, max_chars=80)
            for item in value[:8]
            if item is not None
        ]
        return ", ".join(part for part in parts if part)[:max_chars]
    if isinstance(value, Mapping):
        return ""
    return str(value).strip()[:max_chars]


def artifact_text_value(value: object, *, max_chars: int = 240) -> str:
    return redact_sensitive_text(str(value or "").strip())[:max_chars]


def case_question_preview(case: Any) -> str:
    return preview_value(getattr(case, "question", ""))


def case_answer_preview(case: Any) -> str:
    metadata = getattr(case, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return ""
    return preview_value(metadata.get("answer_preview"))


def case_expected_terms_preview(case: Any) -> tuple[str, ...]:
    expected_terms = getattr(case, "expected_terms", ()) or ()
    if not isinstance(expected_terms, Sequence) or isinstance(expected_terms, str | bytes):
        return ()
    return tuple(
        preview
        for value in expected_terms[:20]
        if (preview := preview_value(value, max_chars=120))
    )


def case_evidence_refs(case: Any) -> tuple[str, ...]:
    metadata = getattr(case, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return ()
    evidence = metadata.get("evidence")
    if not evidence:
        evidence = metadata.get("evidence_terms")
    if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
        return ()
    refs: list[str] = []
    for value in _flatten_scalar_values(evidence)[:20]:
        for ref in safe_source_refs_for_output(value):
            if ref and ref not in refs:
                refs.append(ref[:120])
    return tuple(refs)


def case_evidence_ref_previews(
    case: Any,
    *,
    refs: Sequence[str] | None = None,
) -> tuple[str, ...]:
    metadata = getattr(case, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return ()
    raw_previews = metadata.get("evidence_previews")
    preview_by_ref = _evidence_preview_lookup(raw_previews)
    if not preview_by_ref:
        return ()
    selected_refs = tuple(refs) if refs is not None else case_evidence_refs(case)
    previews: list[str] = []
    for raw_ref in selected_refs[:20]:
        ref = str(raw_ref).strip()[:120]
        text = preview_by_ref.get(ref)
        if not ref or not text:
            continue
        previews.append(f"{ref}: {text}"[:360])
    return tuple(previews)


def response_evidence_text(data: Mapping[str, object]) -> str:
    texts: list[str] = []
    rendered = data.get("rendered_text")
    if isinstance(rendered, str):
        texts.append(_safe_evidence_text(rendered))
    items = data.get("items")
    if isinstance(items, Sequence) and not isinstance(items, str | bytes):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if isinstance(item.get("text"), str):
                texts.append(_safe_evidence_text(item["text"]))
            texts.extend(_item_source_ref_evidence_parts(item))
    return "\n".join(texts)


def _evidence_preview_lookup(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {
            ref: text
            for raw_ref, raw_text in value.items()
            if (ref := _safe_preview_ref(raw_ref))
            and (text := preview_value(raw_text, max_chars=240))
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        previews: dict[str, str] = {}
        for item in value[:20]:
            if not isinstance(item, Mapping):
                continue
            ref = _safe_preview_ref(item.get("ref"))
            text = preview_value(item.get("text"), max_chars=240)
            if ref and text:
                previews[ref] = text
        return previews
    return {}


def _flatten_scalar_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        return ()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        flattened: list[object] = []
        for item in value:
            flattened.extend(_flatten_scalar_values(item))
        return tuple(flattened)
    return (value,) if value is not None else ()


def _item_source_ref_evidence_parts(item: Mapping[str, object]) -> list[str]:
    parts: list[str] = []
    source_refs = item.get("source_refs")
    if isinstance(source_refs, Sequence) and not isinstance(source_refs, str | bytes):
        for ref in source_refs[:8]:
            parts.extend(_source_ref_evidence_parts(ref))
    citations = item.get("citations")
    if isinstance(citations, Sequence) and not isinstance(citations, str | bytes):
        for citation in citations[:8]:
            if not isinstance(citation, Mapping):
                continue
            parts.extend(_source_ref_evidence_parts(citation.get("source")))
            parts.extend(_source_ref_evidence_parts(citation))
    return parts


def _source_ref_evidence_parts(ref: object) -> list[str]:
    if isinstance(ref, str):
        return _safe_source_ref_text_parts(ref)
    if not isinstance(ref, Mapping):
        return []
    parts: list[str] = []
    for key in ("source_type", "source_id", "chunk_id", "quote_preview"):
        value = ref.get(key)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if key == "source_type":
                source_type = safe_item_id_for_output(text)
                if source_type:
                    parts.append(source_type[:80])
            elif key == "quote_preview":
                quote = preview_value(text, max_chars=320)
                if quote:
                    parts.append(quote)
            else:
                item_id = safe_item_id_for_output(text)
                if item_id:
                    parts.append(item_id[:320])
                for part in _safe_source_ref_text_parts(text):
                    if part not in parts:
                        parts.append(part)
    return parts


def _safe_source_ref_text_parts(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    refs = safe_source_refs_for_output((text,))
    if refs:
        return [ref[:320] for ref in refs]
    item_id = safe_item_id_for_output(text)
    return [item_id[:320]] if item_id else []


def _safe_preview_ref(value: object) -> str:
    refs = safe_source_refs_for_output(value)
    if refs:
        return refs[0][:120]
    return ""


def _safe_preview_text(value: object, *, max_chars: int) -> str:
    text = redact_sensitive_text(str(value or "").strip())
    if not text:
        return ""
    if looks_like_raw_source_ref(text):
        return _REDACTED_TEXT
    return text[:max_chars]


def _safe_evidence_text(value: object) -> str:
    text = redact_sensitive_text(str(value or "").strip())
    if not text:
        return ""
    if looks_like_raw_source_ref(text):
        return _REDACTED_TEXT
    return text
