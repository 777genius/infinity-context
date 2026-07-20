"""Single-pass quote state for the bounded attribution parser."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_attribution_lexicon import (
    POST_REPORTING_MODIFIERS,
    REPORTING_BASE_FORMS,
    REPORTING_FINITE_FORMS,
    WORD_RE,
    is_word_apostrophe,
)

_QUOTE_OPENERS = {'"': '"', "'": "'", "“": "”", "‘": "’"}
_QUOTE_CLOSERS = frozenset(_QUOTE_OPENERS.values())
_REVERSED_DIRECTIONAL_QUOTES = {"”": "“", "’": "‘"}
_SOFT_SEPARATORS = frozenset({",", ":", "—", "–"})
_HARD_SEPARATORS = frozenset({".", "!", "?", ";"})
_ADJACENT_QUOTE_CONNECTORS = frozenset({"", "and", "or"})
_MAX_POSTFIX_SCAN_CHARACTERS = 512


@dataclass(slots=True)
class QuoteSpan:
    start: int
    body_start: int
    body_end: int
    end: int
    prefix_span: tuple[int, int] | None
    prefix_linked: bool
    prefix_malformed: bool
    previous_adjacent_quote: int | None
    suffix_span: tuple[int, int] | None = None
    suffix_separated: bool = False
    suffix_malformed: bool = False


@dataclass(frozen=True, slots=True)
class QuoteScan:
    quotes: tuple[QuoteSpan, ...]
    malformed_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _OpenQuote:
    start: int
    body_start: int
    closer: str
    prefix_span: tuple[int, int] | None
    prefix_linked: bool
    prefix_malformed: bool
    previous_adjacent_quote: int | None
    valid_orientation: bool


def scan_quotes(text: str) -> QuoteScan:
    """Scan balanced, nested, adjacent, and malformed quotes in linear time."""

    quotes: list[QuoteSpan] = []
    malformed_spans: list[tuple[int, int]] = []
    stack: list[_OpenQuote] = []
    pending_suffixes: list[int] = []
    last_segment: tuple[int, int] | None = None
    segment_start = 0
    last_closed_quote: int | None = None

    def finish_segment(end: int) -> None:
        nonlocal last_segment
        span = _trimmed_span(text=text, start=segment_start, end=end)
        if span is None:
            return
        for quote_index in pending_suffixes:
            quote = quotes[quote_index]
            _, separated, malformed = _separator_link(
                text=text,
                start=quote.end,
                end=span[0],
            )
            quote.suffix_span = span
            quote.suffix_separated = separated
            quote.suffix_malformed = malformed
        pending_suffixes.clear()
        last_segment = span

    for index in range(len(text)):
        character = text[index]
        if stack:
            if character == "\n":
                _append_nonempty_span(
                    malformed_spans,
                    start=stack[0].body_start,
                    end=index,
                )
                stack.clear()
                pending_suffixes.clear()
                last_segment = None
                segment_start = index + 1
                last_closed_quote = None
                continue
            syntax_closer = character == stack[-1].closer and _is_syntax_closing_apostrophe(
                text=text,
                index=index,
            )
            if not syntax_closer and is_word_apostrophe(text=text, index=index):
                continue
            if character == stack[-1].closer:
                opened = stack.pop()
                if not stack:
                    if not opened.valid_orientation:
                        _append_nonempty_span(
                            malformed_spans,
                            start=opened.body_start,
                            end=index,
                        )
                        pending_suffixes.clear()
                        last_segment = None
                        segment_start = index + 1
                        last_closed_quote = None
                        continue
                    quote = QuoteSpan(
                        start=opened.start,
                        body_start=opened.body_start,
                        body_end=index,
                        end=index + 1,
                        prefix_span=opened.prefix_span,
                        prefix_linked=opened.prefix_linked,
                        prefix_malformed=opened.prefix_malformed,
                        previous_adjacent_quote=opened.previous_adjacent_quote,
                    )
                    quotes.append(quote)
                    last_closed_quote = len(quotes) - 1
                    pending_suffixes.append(last_closed_quote)
                    last_segment = None
                    segment_start = index + 1
                continue
            closer = _QUOTE_OPENERS.get(character)
            if closer is not None:
                stack.append(
                    _OpenQuote(
                        start=index,
                        body_start=index + 1,
                        closer=closer,
                        prefix_span=None,
                        prefix_linked=False,
                        prefix_malformed=False,
                        previous_adjacent_quote=None,
                        valid_orientation=True,
                    )
                )
            continue

        if is_word_apostrophe(text=text, index=index):
            continue
        closer = _QUOTE_OPENERS.get(character)
        if closer is not None:
            previous_adjacent_quote = _adjacent_quote_index(
                text=text,
                quotes=quotes,
                previous_index=last_closed_quote,
                end=index,
            )
            finish_segment(index)
            pending_suffixes.clear()
            prefix_linked = False
            prefix_malformed = False
            if last_segment is not None:
                prefix_linked, _, prefix_malformed = _separator_link(
                    text=text,
                    start=last_segment[1],
                    end=index,
                )
            stack.append(
                _OpenQuote(
                    start=index,
                    body_start=index + 1,
                    closer=closer,
                    prefix_span=last_segment,
                    prefix_linked=prefix_linked,
                    prefix_malformed=prefix_malformed,
                    previous_adjacent_quote=previous_adjacent_quote,
                    valid_orientation=True,
                )
            )
            segment_start = index + 1
            continue
        reversed_closer = _REVERSED_DIRECTIONAL_QUOTES.get(character)
        if reversed_closer is not None:
            finish_segment(index)
            pending_suffixes.clear()
            stack.append(
                _OpenQuote(
                    start=index,
                    body_start=index + 1,
                    closer=reversed_closer,
                    prefix_span=None,
                    prefix_linked=False,
                    prefix_malformed=False,
                    previous_adjacent_quote=None,
                    valid_orientation=False,
                )
            )
            segment_start = index + 1
            continue
        if character in _HARD_SEPARATORS:
            finish_segment(index)
            pending_suffixes.clear()
            last_segment = None
            segment_start = index + 1
            last_closed_quote = None
            continue
        if (
            character in _SOFT_SEPARATORS
            or _is_ascii_dash_separator(text=text, index=index)
            or _is_malformed_separator_boundary(text=text, index=index)
        ):
            finish_segment(index)
            segment_start = index + 1

    if stack:
        _append_nonempty_span(
            malformed_spans,
            start=stack[0].body_start,
            end=len(text),
        )
    else:
        finish_segment(len(text))
    return QuoteScan(quotes=tuple(quotes), malformed_spans=tuple(malformed_spans))


def _adjacent_quote_index(
    *,
    text: str,
    quotes: list[QuoteSpan],
    previous_index: int | None,
    end: int,
) -> int | None:
    if previous_index is None:
        return None
    bridge = text[quotes[previous_index].end : end]
    words = " ".join(bridge.translate(str.maketrans("", "", ",:—–-")).split()).casefold()
    return previous_index if words in _ADJACENT_QUOTE_CONNECTORS else None


def _append_nonempty_span(
    spans: list[tuple[int, int]],
    *,
    start: int,
    end: int,
) -> None:
    if start < end:
        spans.append((start, end))


def _separator_link(*, text: str, start: int, end: int) -> tuple[bool, bool, bool]:
    """Classify whitespace or one delimiter between a clause and a quote."""

    bridge = text[start:end]
    if not bridge:
        return False, False, False
    punctuation = tuple(character for character in bridge if not character.isspace())
    if not punctuation:
        return True, False, False
    if len(punctuation) == 1 and punctuation[0] in _SOFT_SEPARATORS | {"-"}:
        return True, True, False
    return False, False, True


def _trimmed_span(*, text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and (text[start].isspace() or text[start] in _QUOTE_CLOSERS):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in _QUOTE_CLOSERS):
        end -= 1
    return (start, end) if start < end else None


def _is_ascii_dash_separator(*, text: str, index: int) -> bool:
    if text[index] != "-":
        return False
    return (index > 0 and text[index - 1].isspace()) or (
        index + 1 < len(text) and text[index + 1].isspace()
    )


def _is_malformed_separator_boundary(*, text: str, index: int) -> bool:
    if text[index] != "/":
        return False
    return index > 0 and text[index - 1] in _SOFT_SEPARATORS | {"-"}


def _is_syntax_closing_apostrophe(*, text: str, index: int) -> bool:
    """Close an s-final single quote when the following syntax is decisive."""

    if text[index] not in {"'", "’"} or index == 0 or text[index - 1].casefold() != "s":
        return False
    cursor = index + 1
    if cursor >= len(text) or not text[cursor].isspace():
        return False
    while cursor < len(text) and text[cursor].isspace() and text[cursor] != "\n":
        cursor += 1
    if cursor >= len(text) or text[cursor] == "\n":
        return False
    if _starts_adjacent_quote_bridge(text=text, start=cursor):
        return True
    return _is_postfix_reporting_clause(text=text, start=cursor, closer=text[index])


def _starts_adjacent_quote_bridge(*, text: str, start: int) -> bool:
    connector = WORD_RE.match(text, start)
    if connector is None or connector.group(0).casefold() not in _ADJACENT_QUOTE_CONNECTORS:
        return False
    cursor = connector.end()
    if cursor >= len(text) or not text[cursor].isspace():
        return False
    while cursor < len(text) and text[cursor].isspace() and text[cursor] != "\n":
        cursor += 1
    return cursor < len(text) and text[cursor] in _QUOTE_OPENERS


def _is_postfix_reporting_clause(*, text: str, start: int, closer: str) -> bool:
    end = start
    limit = min(len(text), start + _MAX_POSTFIX_SCAN_CHARACTERS)
    while end < limit and text[end] != "\n" and text[end] not in _HARD_SEPARATORS:
        if text[end] == closer:
            return False
        end += 1
    if end == limit and limit < len(text):
        return False
    tokens = tuple(WORD_RE.finditer(text, start, end))
    if not tokens:
        return False
    if text[start : tokens[0].start()].strip() or text[tokens[-1].end() : end].strip():
        return False
    if any(
        text[left.end() : right.start()].strip()
        for left, right in zip(tokens, tokens[1:], strict=False)
    ):
        return False
    final = tokens[-1].group(0).casefold()
    if final in POST_REPORTING_MODIFIERS and len(tokens) > 1:
        final = tokens[-2].group(0).casefold()
    return final in REPORTING_FINITE_FORMS | REPORTING_BASE_FORMS
