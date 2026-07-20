"""Bounded coordination for third-party obligation attribution."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from infinity_context_core.application.context_attribution_lexicon import (
    FIRST_OR_SECOND_PERSON_SUBJECTS,
    MAX_NAMED_SUBJECT_WORDS,
    MAX_NOUN_PHRASE_SUBJECT_WORDS,
    OBLIGATION_SUBJECT_PRONOUNS,
    PRE_MODAL_MODIFIERS,
    PREDICATE_NEGATIONS,
    SUBJECT_BOUNDARIES,
    SUBJECT_DETERMINERS,
    WordToken,
    tokens_are_space_joined,
    word_tokens,
)
from infinity_context_core.application.context_quote_scanner import (
    QuoteSpan,
    scan_quotes,
)
from infinity_context_core.application.context_reporting_frames import (
    indirect_reporting_header_end,
    is_reporting_clause,
    malformed_reporting_header_end,
)

_CLAUSE_SEPARATORS = frozenset({".", "!", "?", ";"})
_SENTENCE_TERMINATORS = frozenset({".", "!", "?"})


@dataclass(frozen=True, slots=True)
class _AttributionAnalysis:
    reported_spans: tuple[tuple[int, int], ...]
    promotion_exclusion_spans: tuple[tuple[int, int], ...]


def third_party_reported_obligation_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return obligation spans tied structurally to a third-party reporter."""

    return _analyze_attribution(text).reported_spans


def obligation_promotion_exclusion_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return reported or malformed quote spans unsafe for direct promotion."""

    return _analyze_attribution(text).promotion_exclusion_spans


def _analyze_attribution(text: str) -> _AttributionAnalysis:
    quote_scan = scan_quotes(text)
    reported_quotes, split_quote_exclusions = _quoted_obligation_spans(
        text=text,
        quotes=quote_scan.quotes,
    )
    indirect = tuple(_indirect_obligation_spans(text))
    reported = tuple(dict.fromkeys((*reported_quotes, *indirect)))
    malformed = quote_scan.malformed_spans
    malformed_indirect = tuple(_malformed_indirect_obligation_spans(text))
    exclusions = tuple(
        dict.fromkeys((*reported, *split_quote_exclusions, *malformed, *malformed_indirect))
    )
    return _AttributionAnalysis(
        reported_spans=reported,
        promotion_exclusion_spans=exclusions,
    )


def _quoted_obligation_spans(
    *,
    text: str,
    quotes: tuple[QuoteSpan, ...],
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    attributed: list[bool] = []
    reported: list[tuple[int, int]] = []
    split_exclusions: list[tuple[int, int]] = []
    adjacent_group: list[QuoteSpan] = []

    for quote in quotes:
        inherited = (
            quote.previous_adjacent_quote is not None and attributed[quote.previous_adjacent_quote]
        )
        quote_is_attributed = (
            inherited
            or _has_prefix_reporter(
                text=text,
                quote=quote,
            )
            or _has_suffix_reporter(text=text, quote=quote)
        )
        attributed.append(quote_is_attributed)

        if _has_malformed_reporter_link(text=text, quote=quote):
            split_exclusions.append((quote.body_start, quote.body_end))

        has_predicate = any(
            _obligation_predicate_spans(
                text,
                start=quote.body_start,
                end=quote.body_end,
            )
        )
        if quote_is_attributed and has_predicate:
            reported.append((quote.body_start, quote.body_end))

        if quote.previous_adjacent_quote is None:
            adjacent_group = [quote]
        else:
            adjacent_group.append(quote)
        if (
            quote_is_attributed
            and len(adjacent_group) > 1
            and not has_predicate
            and _joined_quotes_have_obligation(text=text, quotes=adjacent_group)
        ):
            split_exclusions.append((adjacent_group[0].body_start, adjacent_group[-1].body_end))

    return tuple(reported), tuple(split_exclusions)


def _joined_quotes_have_obligation(*, text: str, quotes: list[QuoteSpan]) -> bool:
    joined = " ".join(text[quote.body_start : quote.body_end] for quote in quotes)
    return any(_obligation_predicate_spans(joined))


def _has_prefix_reporter(*, text: str, quote: QuoteSpan) -> bool:
    if quote.prefix_span is None or not quote.prefix_linked or quote.prefix_malformed:
        return False
    return is_reporting_clause(text[slice(*quote.prefix_span)])


def _has_suffix_reporter(*, text: str, quote: QuoteSpan) -> bool:
    if quote.suffix_span is None or quote.suffix_malformed:
        return False
    if not quote.suffix_separated:
        gap = text[quote.end : quote.suffix_span[0]]
        if not gap or not gap.isspace():
            return False
        final_body_character = _last_non_space_character(
            text=text,
            start=quote.body_start,
            end=quote.body_end,
        )
        if final_body_character in _SENTENCE_TERMINATORS:
            return False
    return is_reporting_clause(text[slice(*quote.suffix_span)])


def _has_malformed_reporter_link(*, text: str, quote: QuoteSpan) -> bool:
    prefix_reporter = (
        quote.prefix_malformed
        and quote.prefix_span is not None
        and is_reporting_clause(text[slice(*quote.prefix_span)])
    )
    suffix_reporter = (
        quote.suffix_malformed
        and quote.suffix_span is not None
        and is_reporting_clause(text[slice(*quote.suffix_span)])
    )
    return prefix_reporter or suffix_reporter


def _last_non_space_character(*, text: str, start: int, end: int) -> str:
    while end > start:
        end -= 1
        if not text[end].isspace():
            return text[end]
    return ""


def _indirect_obligation_spans(text: str) -> Iterator[tuple[int, int]]:
    for clause_start, clause_end in _clause_spans(text):
        header_end = indirect_reporting_header_end(
            text=text,
            start=clause_start,
            end=clause_end,
        )
        if header_end is None:
            continue
        for obligation_start, _ in _obligation_predicate_spans(
            text,
            start=header_end,
            end=clause_end,
        ):
            yield obligation_start, clause_end


def _malformed_indirect_obligation_spans(text: str) -> Iterator[tuple[int, int]]:
    for clause_start, clause_end in _clause_spans(text):
        header_end = malformed_reporting_header_end(
            text=text,
            start=clause_start,
            end=clause_end,
        )
        if header_end is None:
            continue
        for obligation_start, _ in _obligation_predicate_spans(
            text,
            start=header_end,
            end=clause_end,
        ):
            yield obligation_start, clause_end


def _obligation_predicate_spans(
    text: str,
    *,
    start: int = 0,
    end: int | None = None,
) -> Iterator[tuple[int, int]]:
    """Parse bounded subject/modal/action predicates within local clauses."""

    clause_end = len(text) if end is None else end
    for local_start, local_end in _clause_spans(text, start=start, end=clause_end):
        tokens = tuple(word_tokens(text=text, start=local_start, end=local_end))
        for modal_start, action_index in _modal_action_pairs(text=text, tokens=tokens):
            subject_start = _obligation_subject_start(
                text=text,
                tokens=tokens,
                modal_start=modal_start,
            )
            if subject_start is not None:
                yield tokens[subject_start].start, tokens[action_index].end


def _modal_action_pairs(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
) -> Iterator[tuple[int, int]]:
    for index in range(len(tokens)):
        modal_end = _modal_end_index(text=text, tokens=tokens, start=index)
        if modal_end is None:
            continue
        action_index = modal_end
        if (
            action_index < len(tokens)
            and tokens[action_index].value.casefold() in PREDICATE_NEGATIONS
        ):
            if not tokens_are_space_joined(
                text=text,
                left=tokens[action_index - 1],
                right=tokens[action_index],
            ):
                continue
            action_index += 1
        if action_index < len(tokens) and tokens_are_space_joined(
            text=text,
            left=tokens[action_index - 1],
            right=tokens[action_index],
        ):
            yield index, action_index


def _modal_end_index(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    start: int,
) -> int | None:
    modal = tokens[start].value.casefold()
    if modal in {"must", "should"}:
        return start + 1
    if modal in {"have", "has", "need", "needs"} and _tokens_match(
        text=text,
        tokens=tokens,
        start=start + 1,
        values=("to",),
    ):
        return start + 2
    if modal in {"am", "are", "is"} and _tokens_match(
        text=text,
        tokens=tokens,
        start=start + 1,
        values=("expected", "to"),
        alternatives=("required", "supposed"),
    ):
        return start + 3
    return None


def _tokens_match(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    start: int,
    values: tuple[str, ...],
    alternatives: tuple[str, ...] = (),
) -> bool:
    if start + len(values) > len(tokens):
        return False
    for offset, expected in enumerate(values):
        token = tokens[start + offset]
        accepted = {expected, *alternatives} if offset == 0 else {expected}
        if token.value.casefold() not in accepted:
            return False
        if offset > 0 and not tokens_are_space_joined(
            text=text,
            left=tokens[start + offset - 1],
            right=token,
        ):
            return False
    return start == 0 or tokens_are_space_joined(
        text=text,
        left=tokens[start - 1],
        right=tokens[start],
    )


def _obligation_subject_start(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    modal_start: int,
) -> int | None:
    subject_end = modal_start
    while (
        subject_end > 0
        and modal_start - subject_end < len(PRE_MODAL_MODIFIERS)
        and tokens[subject_end - 1].value.casefold() in PRE_MODAL_MODIFIERS
        and tokens_are_space_joined(
            text=text,
            left=tokens[subject_end - 1],
            right=tokens[subject_end],
        )
    ):
        subject_end -= 1
    if subject_end == 0 or not tokens_are_space_joined(
        text=text,
        left=tokens[subject_end - 1],
        right=tokens[subject_end],
    ):
        return None
    subject_head = tokens[subject_end - 1]
    folded_head = subject_head.value.casefold()
    if folded_head in OBLIGATION_SUBJECT_PRONOUNS:
        return subject_end - 1
    if folded_head in FIRST_OR_SECOND_PERSON_SUBJECTS and subject_head.value != "US":
        return None
    if subject_head.value[0].isupper():
        return _named_subject_start(text=text, tokens=tokens, subject_end=subject_end)
    return _noun_phrase_subject_start(text=text, tokens=tokens, subject_end=subject_end)


def _named_subject_start(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    subject_end: int,
) -> int | None:
    start = subject_end
    while start > 0 and subject_end - start < MAX_NAMED_SUBJECT_WORDS:
        token = tokens[start - 1]
        if not token.value[0].isupper():
            break
        if start < subject_end and not tokens_are_space_joined(
            text=text,
            left=token,
            right=tokens[start],
        ):
            break
        start -= 1
    return start if start < subject_end else None


def _noun_phrase_subject_start(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    subject_end: int,
) -> int | None:
    head = tokens[subject_end - 1].value.casefold()
    if head in SUBJECT_DETERMINERS or head in SUBJECT_BOUNDARIES:
        return None
    lower_bound = max(0, subject_end - MAX_NOUN_PHRASE_SUBJECT_WORDS)
    start = subject_end - 1
    for index in range(subject_end - 2, lower_bound - 1, -1):
        if not tokens_are_space_joined(
            text=text,
            left=tokens[index],
            right=tokens[index + 1],
        ):
            break
        folded = tokens[index].value.casefold()
        if folded in SUBJECT_BOUNDARIES:
            break
        start = index
        if folded in SUBJECT_DETERMINERS:
            return index
    return start


def _clause_spans(
    text: str,
    *,
    start: int = 0,
    end: int | None = None,
) -> Iterator[tuple[int, int]]:
    limit = len(text) if end is None else end
    clause_start = start
    index = start
    while index < limit:
        if text[index] not in _CLAUSE_SEPARATORS:
            index += 1
            continue
        if index > clause_start:
            yield clause_start, index
        index += 1
        while index < limit and text[index] in _CLAUSE_SEPARATORS:
            index += 1
        clause_start = index
    if clause_start < limit:
        yield clause_start, limit
