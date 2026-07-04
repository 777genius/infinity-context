"""Bounded diagnostics for public benchmark cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def preview_value(value: object, *, max_chars: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()[:max_chars]
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


def case_question_preview(case: Any) -> str:
    return str(getattr(case, "question", "") or "")[:240]


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
        str(value).strip()[:120]
        for value in expected_terms[:20]
        if str(value).strip()
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
    return tuple(str(value).strip()[:120] for value in evidence[:20] if str(value).strip())


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
        texts.append(rendered)
    items = data.get("items")
    if isinstance(items, Sequence) and not isinstance(items, str | bytes):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            if isinstance(item.get("text"), str):
                texts.append(item["text"])
            texts.extend(_item_source_ref_evidence_parts(item))
    return "\n".join(texts)


def _evidence_preview_lookup(value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {
            ref: text
            for raw_ref, raw_text in value.items()
            if (ref := str(raw_ref).strip()[:120])
            and (text := preview_value(raw_text, max_chars=240))
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        previews: dict[str, str] = {}
        for item in value[:20]:
            if not isinstance(item, Mapping):
                continue
            ref = str(item.get("ref") or "").strip()[:120]
            text = preview_value(item.get("text"), max_chars=240)
            if ref and text:
                previews[ref] = text
        return previews
    return {}


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
        text = ref.strip()
        return [text[:320]] if text else []
    if not isinstance(ref, Mapping):
        return []
    parts: list[str] = []
    for key in ("source_type", "source_id", "chunk_id", "quote_preview"):
        value = ref.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                parts.append(text[:320])
    return parts
