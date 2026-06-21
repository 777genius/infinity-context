"""Query-focused evidence snippet helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    matching_token_spans,
    query_terms,
)
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import SourceRef

_DEFAULT_WINDOW_CHARS = 320
_MAX_QUERY_TERMS = 12
_MAX_SNIPPET_CHARS = 360
_MAX_BOUNDARY_SCAN_CHARS = 40
_MAX_LINE_PREFIX_SCAN_CHARS = 240


@dataclass(frozen=True)
class QuerySnippet:
    text: str
    char_start: int
    char_end: int
    matched_terms: tuple[str, ...]
    unique_term_hits: int


def query_focused_snippet(
    *,
    query: str,
    text: str,
    window_chars: int = _DEFAULT_WINDOW_CHARS,
) -> QuerySnippet | None:
    """Return the smallest useful evidence window around query term hits."""

    terms = _query_terms(query)
    if not terms or not text.strip():
        return None

    hits = _term_hits(text, terms)
    if not hits:
        return None

    window = max(80, window_chars)
    start, end, matched_terms = _best_window(
        text_len=len(text),
        hits=hits,
        window_chars=window,
    )
    start = _left_word_boundary(text, start)
    start = _left_line_boundary(text, start)
    end = _right_word_boundary(text, end)
    snippet = _render_snippet(text=text, start=start, end=end)
    if not snippet:
        return None
    return QuerySnippet(
        text=snippet,
        char_start=start,
        char_end=end,
        matched_terms=matched_terms,
        unique_term_hits=len(matched_terms),
    )


def source_refs_with_query_snippet(
    source_refs: tuple[SourceRef, ...],
    snippet: QuerySnippet | None,
    *,
    include_char_range: bool = False,
) -> tuple[SourceRef, ...]:
    if snippet is None or not source_refs:
        return source_refs
    return tuple(
        replace(
            ref,
            quote_preview=snippet.text,
            char_start=snippet.char_start if include_char_range else ref.char_start,
            char_end=snippet.char_end if include_char_range else ref.char_end,
        )
        for ref in source_refs
    )


def query_snippet_diagnostics(snippet: QuerySnippet | None) -> dict[str, object]:
    if snippet is None:
        return {}
    return {
        "query_snippet": snippet.text,
        "query_snippet_char_start": snippet.char_start,
        "query_snippet_char_end": snippet.char_end,
        "query_snippet_matched_terms": list(snippet.matched_terms),
        "query_snippet_unique_term_hits": snippet.unique_term_hits,
    }


def query_snippet_score_signals(snippet: QuerySnippet | None) -> dict[str, object]:
    if snippet is None:
        return {}
    return {
        "query_snippet_char_start": snippet.char_start,
        "query_snippet_char_end": snippet.char_end,
        "query_snippet_unique_term_hits": snippet.unique_term_hits,
    }


def _query_terms(query: str) -> tuple[LexicalQueryTerm, ...]:
    return query_terms(query, max_terms=_MAX_QUERY_TERMS)


def _term_hits(
    text: str,
    terms: tuple[LexicalQueryTerm, ...],
) -> tuple[tuple[int, int, str], ...]:
    return matching_token_spans(text=text, terms=terms)


def _best_window(
    *,
    text_len: int,
    hits: tuple[tuple[int, int, str], ...],
    window_chars: int,
) -> tuple[int, int, tuple[str, ...]]:
    best_start = 0
    best_end = min(text_len, window_chars)
    best_terms: tuple[str, ...] = ()
    best_key: tuple[int, int, int] = (-1, -1, 0)
    for hit_start, hit_end, _ in hits:
        center = (hit_start + hit_end) // 2
        start, end = _window_bounds(text_len=text_len, center=center, window_chars=window_chars)
        terms = _window_terms(hits=hits, start=start, end=end)
        hit_count = sum(
            1
            for candidate_start, candidate_end, _ in hits
            if candidate_start < end and candidate_end > start
        )
        key = (len(terms), hit_count, -start)
        if key > best_key:
            best_start = start
            best_end = end
            best_terms = terms
            best_key = key
    return best_start, best_end, best_terms


def _window_bounds(*, text_len: int, center: int, window_chars: int) -> tuple[int, int]:
    start = max(0, center - window_chars // 2)
    end = min(text_len, start + window_chars)
    start = max(0, end - window_chars)
    return start, end


def _window_terms(
    *,
    hits: tuple[tuple[int, int, str], ...],
    start: int,
    end: int,
) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for hit_start, hit_end, term in hits:
        if hit_start >= end or hit_end <= start or term in seen:
            continue
        terms.append(term)
        seen.add(term)
    return tuple(terms)


def _left_word_boundary(text: str, start: int) -> int:
    cursor = max(0, start)
    scanned = 0
    while cursor > 0 and not text[cursor - 1].isspace() and scanned < _MAX_BOUNDARY_SCAN_CHARS:
        cursor -= 1
        scanned += 1
    return cursor


def _left_line_boundary(text: str, start: int) -> int:
    cursor = max(0, start)
    if cursor == 0:
        return 0
    line_start = text.rfind("\n", max(0, cursor - _MAX_LINE_PREFIX_SCAN_CHARS), cursor)
    if line_start >= 0:
        return line_start + 1
    if cursor <= _MAX_LINE_PREFIX_SCAN_CHARS:
        return 0
    return cursor


def _right_word_boundary(text: str, end: int) -> int:
    cursor = min(len(text), end)
    scanned = 0
    while cursor < len(text) and not text[cursor].isspace() and scanned < _MAX_BOUNDARY_SCAN_CHARS:
        cursor += 1
        scanned += 1
    return cursor


def _render_snippet(*, text: str, start: int, end: int) -> str:
    snippet = " ".join(text[start:end].strip().split())
    if not snippet:
        return ""
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(text):
        snippet = f"{snippet} ..."
    return safe_metadata_text(snippet, limit=_MAX_SNIPPET_CHARS)
