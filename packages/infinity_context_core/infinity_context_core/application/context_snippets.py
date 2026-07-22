"""Query-focused evidence snippet helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from infinity_context_core.application.context_dialogue_authority import (
    prefer_direct_user_assertion,
)
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
_MAX_STRUCTURED_SNIPPET_CHARS = 640
_MAX_STRUCTURED_SNIPPET_LINES = 4
_MAX_STRUCTURED_PREVIOUS_LINES = 2
_MAX_STRUCTURED_PREFIX_LINES = 7
_MAX_BOUNDARY_SCAN_CHARS = 40
_MAX_LINE_PREFIX_SCAN_CHARS = 1200
_STRUCTURED_EVIDENCE_LINE_RE = re.compile(r"^\s*(?:D\d+:\d+|S\d+:\d+|T\d+:\d+)\b")
_STRUCTURED_EVIDENCE_PREFIX_RE = re.compile(r"^\s*((?:(?:D|S|T)\d+:\d+\s+){0,7}(?:D|S|T)\d+:\d+)\b")
_INLINE_STRUCTURED_EVIDENCE_MARKER_RE = re.compile(r"\b(?:D|S|T)\d+:\d+\b")
_MAX_INLINE_STRUCTURED_SNIPPET_CHARS = 640
_MAX_INLINE_STRUCTURED_PREVIOUS_MARKERS = 2
_MAX_INLINE_STRUCTURED_FOLLOWING_MARKERS = 6


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
    word_start = _left_word_boundary(text, start)
    line_start = _left_line_boundary(text, word_start)
    structured_line = _is_structured_evidence_line(text, line_start)
    if not structured_line:
        inline_snippet = _inline_structured_evidence_snippet(
            query=query,
            query_terms=terms,
            text=text,
        )
        if inline_snippet is not None and _should_prefer_inline_structured_snippet(
            inline_snippet=inline_snippet,
            matched_terms=matched_terms,
        ):
            return inline_snippet
    max_chars = _MAX_STRUCTURED_SNIPPET_CHARS if structured_line else _MAX_SNIPPET_CHARS
    start = line_start if end - line_start <= max_chars else word_start
    structured_context_start = structured_line and start == line_start
    if structured_context_start:
        start = _left_structured_context_boundary(
            text=text,
            line_start=line_start,
            end=end,
            max_chars=max_chars,
        )
    end = _right_word_boundary(text, end)
    if structured_context_start:
        end = _right_structured_line_boundary(text=text, start=start, end=end)
    evidence_range = prefer_direct_user_assertion(
        query=query,
        text=text,
        char_start=start,
        char_end=end,
    )
    start, end = evidence_range.char_start, evidence_range.char_end
    matched_terms = _window_terms(hits=hits, start=start, end=end)
    snippet = _render_snippet(text=text, start=start, end=end, max_chars=max_chars)
    if structured_line and start != line_start:
        snippet = _prepend_structured_evidence_prefix(
            text=text,
            line_start=line_start,
            snippet=snippet,
            max_chars=max_chars,
        )
    if structured_line:
        snippet = _prepend_adjacent_structured_evidence_prefixes(
            text=text,
            line_start=line_start,
            snippet=snippet,
            max_chars=max_chars,
        )
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
            quote_preview=snippet.text if index == 0 else ref.quote_preview,
            char_start=snippet.char_start if include_char_range and index == 0 else ref.char_start,
            char_end=snippet.char_end if include_char_range and index == 0 else ref.char_end,
        )
        for index, ref in enumerate(source_refs)
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


def _should_prefer_inline_structured_snippet(
    *,
    inline_snippet: QuerySnippet,
    matched_terms: tuple[str, ...],
) -> bool:
    if inline_snippet.unique_term_hits >= len(matched_terms):
        return True
    return inline_snippet.unique_term_hits >= 4 and inline_snippet.unique_term_hits >= (
        len(matched_terms) - 1
    )


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


def _is_structured_evidence_line(text: str, line_start: int) -> bool:
    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return bool(_STRUCTURED_EVIDENCE_LINE_RE.match(line))


def _prepend_structured_evidence_prefix(
    *,
    text: str,
    line_start: int,
    snippet: str,
    max_chars: int,
) -> str:
    if not snippet:
        return ""
    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    match = _STRUCTURED_EVIDENCE_PREFIX_RE.match(line)
    if not match:
        return snippet
    prefix = " ".join(match.group(1).split())
    if prefix in snippet:
        return snippet
    normalized_snippet = snippet.removeprefix("... ").strip()
    return safe_metadata_text(f"{prefix} ... {normalized_snippet}", limit=max_chars)


def _prepend_adjacent_structured_evidence_prefixes(
    *,
    text: str,
    line_start: int,
    snippet: str,
    max_chars: int,
) -> str:
    if not snippet:
        return ""
    prefixes = _adjacent_structured_evidence_prefixes(text=text, line_start=line_start)
    missing = tuple(prefix for prefix in prefixes if prefix not in snippet)
    if not missing:
        return snippet
    normalized_snippet = snippet.removeprefix("... ").strip()
    prefix_text = " ".join(missing)
    return safe_metadata_text(f"{prefix_text} ... {normalized_snippet}", limit=max_chars)


def _adjacent_structured_evidence_prefixes(
    *,
    text: str,
    line_start: int,
) -> tuple[str, ...]:
    prefixes: list[str] = []
    previous = _previous_line_start(text, line_start)
    if previous is not None:
        previous_prefix = _structured_evidence_prefix(text=text, line_start=previous)
        if previous_prefix:
            prefixes.append(previous_prefix)
    cursor = line_start
    for _ in range(_MAX_STRUCTURED_PREFIX_LINES):
        prefix = _structured_evidence_prefix(text=text, line_start=cursor)
        if prefix:
            prefixes.append(prefix)
        next_line = _next_line_start(text, cursor)
        if next_line is None:
            break
        cursor = next_line
    return tuple(_dedupe_prefixes(prefixes))


def _structured_evidence_prefix(*, text: str, line_start: int) -> str:
    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    match = _STRUCTURED_EVIDENCE_PREFIX_RE.match(line)
    return " ".join(match.group(1).split()) if match else ""


def _previous_line_start(text: str, line_start: int) -> int | None:
    if line_start <= 0:
        return None
    previous_end = line_start - 1
    previous_start = text.rfind("\n", 0, previous_end)
    return 0 if previous_start == -1 else previous_start + 1


def _left_structured_context_boundary(
    *,
    text: str,
    line_start: int,
    end: int,
    max_chars: int,
) -> int:
    cursor = line_start
    for _ in range(_MAX_STRUCTURED_PREVIOUS_LINES):
        previous = _previous_line_start(text, cursor)
        if previous is None or not _structured_evidence_prefix(
            text=text,
            line_start=previous,
        ):
            break
        if end - previous > max_chars:
            break
        cursor = previous
    return cursor


def _next_line_start(text: str, line_start: int) -> int | None:
    line_end = text.find("\n", line_start)
    if line_end == -1 or line_end + 1 >= len(text):
        return None
    return line_end + 1


def _dedupe_prefixes(prefixes: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        result.append(prefix)
    return tuple(result)


def _right_structured_line_boundary(*, text: str, start: int, end: int) -> int:
    cursor = _right_line_boundary_at_or_after(text, end)
    line_count = text[start:cursor].count("\n") + 1
    scan_start = cursor + 1 if cursor < len(text) else cursor
    while scan_start < len(text) and line_count < _MAX_STRUCTURED_SNIPPET_LINES:
        candidate_end = _right_line_boundary_at_or_after(text, scan_start)
        if candidate_end - start > _MAX_STRUCTURED_SNIPPET_CHARS:
            break
        cursor = candidate_end
        line_count += 1
        if cursor >= len(text):
            break
        scan_start = cursor + 1
    return min(len(text), max(end, cursor))


def _inline_structured_evidence_snippet(
    *,
    query: str,
    query_terms: tuple[LexicalQueryTerm, ...],
    text: str,
) -> QuerySnippet | None:
    markers = tuple(_INLINE_STRUCTURED_EVIDENCE_MARKER_RE.finditer(text))
    if len(markers) < 2:
        return None
    best: tuple[tuple[int, int, int], int, int, tuple[str, ...]] | None = None
    for marker_index, _ in enumerate(markers):
        start_index = max(0, marker_index - _MAX_INLINE_STRUCTURED_PREVIOUS_MARKERS)
        end_index = min(
            len(markers) - 1,
            marker_index + _MAX_INLINE_STRUCTURED_FOLLOWING_MARKERS,
        )
        start = markers[start_index].start()
        end = markers[end_index + 1].start() if end_index + 1 < len(markers) else len(text)
        hits = _term_hits(text[start:end], query_terms)
        if not hits:
            continue
        matched_terms = _window_terms(hits=hits, start=0, end=end - start)
        hit_count = len(hits)
        key = (len(matched_terms), hit_count, -start)
        if best is None or key > best[0]:
            best = (key, start, end, matched_terms)
    if best is None:
        return None
    _, start, end, matched_terms = best
    evidence_range = prefer_direct_user_assertion(
        query=query,
        text=text,
        char_start=start,
        char_end=end,
    )
    start, end = evidence_range.char_start, evidence_range.char_end
    hits = _term_hits(text[start:end], query_terms)
    matched_terms = _window_terms(hits=hits, start=0, end=end - start)
    snippet = _render_snippet(
        text=text,
        start=start,
        end=end,
        max_chars=_MAX_INLINE_STRUCTURED_SNIPPET_CHARS,
    )
    snippet = _prepend_missing_inline_structured_prefixes(
        markers=markers,
        start=start,
        end=end,
        snippet=snippet,
        max_chars=_MAX_INLINE_STRUCTURED_SNIPPET_CHARS,
    )
    if not snippet:
        return None
    return QuerySnippet(
        text=snippet,
        char_start=start,
        char_end=end,
        matched_terms=matched_terms,
        unique_term_hits=len(matched_terms),
    )


def _prepend_missing_inline_structured_prefixes(
    *,
    markers: tuple[re.Match[str], ...],
    start: int,
    end: int,
    snippet: str,
    max_chars: int,
) -> str:
    if not snippet:
        return ""
    prefixes = tuple(
        dict.fromkeys(
            marker.group(0)
            for marker in markers
            if marker.start() >= start and marker.start() < end
        )
    )
    missing = tuple(prefix for prefix in prefixes if prefix not in snippet)
    if not missing:
        return snippet
    normalized_snippet = snippet.removeprefix("... ").strip()
    return safe_metadata_text(
        f"{' '.join(missing)} ... {normalized_snippet}",
        limit=max_chars,
    )


def _right_line_boundary_at_or_after(text: str, end: int) -> int:
    line_end = text.find("\n", end)
    return len(text) if line_end == -1 else line_end


def _render_snippet(*, text: str, start: int, end: int, max_chars: int) -> str:
    snippet = " ".join(text[start:end].strip().split())
    if not snippet:
        return ""
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(text):
        snippet = f"{snippet} ..."
    return safe_metadata_text(snippet, limit=max_chars)
