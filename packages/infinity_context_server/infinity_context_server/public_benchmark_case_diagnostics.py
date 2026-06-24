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
