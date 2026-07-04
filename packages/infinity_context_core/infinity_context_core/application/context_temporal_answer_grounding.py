"""Ground temporal answer evidence to the queried event or person."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.dto import ContextItem

_TEMPORAL_ANSWER_EVIDENCE_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:|today|yesterday|tomorrow|recently|ago|"
    r"last\s+(?:week|month|year|night|weekend|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"сегодня|вчера|завтра|неделю\s+назад|месяц\s+назад|год\s+назад|"
    r"прошл\w+\s+(?:недел\w+|месяц\w+|год\w+|ноч\w+)|"
    r"следующ\w+\s+(?:недел\w+|месяц\w+|год\w+))\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|"
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|"
    r"\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)(?:,?\s+\d{2,4})?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{2,4})?\b",
    re.IGNORECASE,
)
_DATE_HEADER_RE = re.compile(r"\b(?:session_\d+\s+date|date:)\b", re.IGNORECASE)
_TURN_MARKER_SPLIT_RE = re.compile(r"(?=\bD\d+:\d+\s+)")
_GROUNDING_STOPWORDS = frozenset(
    {
        "date",
        "day",
        "days",
        "exact",
        "last",
        "month",
        "next",
        "time",
        "week",
        "when",
        "какая",
        "какие",
        "какой",
        "когда",
        "числа",
    }
)
_METADATA_TEMPORAL_KEYS = (
    "temporal_hint_code",
    "event_temporal_hint_code",
    "event_valid_from",
    "event_valid_to",
    "valid_from",
    "valid_to",
)


@dataclass(frozen=True)
class TemporalAnswerGrounding:
    has_temporal_evidence: bool
    grounded: bool

    @property
    def missing(self) -> bool:
        return not self.has_temporal_evidence

    @property
    def ungrounded(self) -> bool:
        return self.has_temporal_evidence and not self.grounded


def temporal_answer_grounding(query: str, item: ContextItem) -> TemporalAnswerGrounding:
    """Return whether temporal evidence is tied to the query target."""

    text_grounding = temporal_text_answer_grounding(query=query, text=item.text)
    has_temporal_evidence = text_grounding.has_temporal_evidence
    grounded = text_grounding.grounded
    if _item_metadata_has_temporal_anchor(item):
        has_temporal_evidence = True
        grounded = grounded or _text_has_query_grounding(query=query, text=item.text)
    for ref in item.source_refs:
        ref_text = ref.quote_preview or ""
        ref_has_temporal = (
            ref.time_start_ms is not None
            or ref.time_end_ms is not None
            or _TEMPORAL_ANSWER_EVIDENCE_RE.search(ref_text) is not None
        )
        if not ref_has_temporal:
            continue
        has_temporal_evidence = True
        grounded = grounded or _text_has_query_grounding(
            query=query,
            text="\n".join(part for part in (ref_text, item.text) if part),
        )
    return TemporalAnswerGrounding(
        has_temporal_evidence=has_temporal_evidence,
        grounded=grounded,
    )


def temporal_text_answer_grounding(*, query: str, text: str) -> TemporalAnswerGrounding:
    segments = _temporal_segments(text)
    temporal_segments = tuple(
        segment for segment in segments if _TEMPORAL_ANSWER_EVIDENCE_RE.search(segment)
    )
    if not temporal_segments:
        return TemporalAnswerGrounding(has_temporal_evidence=False, grounded=False)
    if not _query_grounding_terms(query):
        return TemporalAnswerGrounding(has_temporal_evidence=True, grounded=True)
    if any(
        _text_has_query_grounding(query=query, text=segment)
        for segment in temporal_segments
    ):
        return TemporalAnswerGrounding(has_temporal_evidence=True, grounded=True)
    if any(_DATE_HEADER_RE.search(segment) is not None for segment in temporal_segments):
        non_header_text = "\n".join(
            segment for segment in segments if _DATE_HEADER_RE.search(segment) is None
        )
        if _text_has_query_grounding(query=query, text=non_header_text):
            return TemporalAnswerGrounding(has_temporal_evidence=True, grounded=True)
    return TemporalAnswerGrounding(has_temporal_evidence=True, grounded=False)


def has_grounded_temporal_text_answer_evidence(*, query: str, text: str) -> bool:
    grounding = temporal_text_answer_grounding(query=query, text=text)
    return grounding.grounded


def _item_metadata_has_temporal_anchor(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return any(
        metadata.get(key)
        for metadata in (diagnostics, provenance)
        for key in _METADATA_TEMPORAL_KEYS
    )


def _temporal_segments(text: str) -> tuple[str, ...]:
    segments: list[str] = []
    for line in text.splitlines() or [text]:
        for segment in _TURN_MARKER_SPLIT_RE.split(line):
            stripped = segment.strip()
            if stripped:
                segments.append(stripped)
    return tuple(segments)


def _text_has_query_grounding(*, query: str, text: str) -> bool:
    terms = _query_grounding_terms(query)
    if not terms:
        return True
    text_casefold = text.casefold()
    hits = sum(1 for variants in terms if _variant_matches(text_casefold, variants))
    return hits >= min(2, len(terms))


def _query_grounding_terms(query: str) -> tuple[tuple[str, ...], ...]:
    terms: list[tuple[str, ...]] = []
    for term in query_terms(query, min_chars=3, max_terms=16):
        if term.raw.casefold() in _GROUNDING_STOPWORDS:
            continue
        variants = tuple(
            variant.casefold()
            for variant in term.variants
            if variant.casefold() not in _GROUNDING_STOPWORDS
        )
        if variants:
            terms.append(variants)
    return tuple(terms)


def _variant_matches(text_casefold: str, variants: Iterable[str]) -> bool:
    return any(
        re.search(rf"\b{re.escape(variant)}\b", text_casefold) is not None
        for variant in variants
    )
