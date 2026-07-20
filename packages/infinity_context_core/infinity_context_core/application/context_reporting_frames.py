"""Recognition of bounded third-party reporting frames."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_attribution_lexicon import (
    AGENTIVE_PLURAL_SUFFIXES,
    AGENTIVE_SINGULAR_SUFFIXES,
    FIRST_OR_SECOND_PERSON_SUBJECTS,
    LEADING_LIST_MARKER_RE,
    MAX_REPORTER_WORDS,
    POST_REPORTING_MODIFIERS,
    REPORTER_CLAUSE_WORDS,
    REPORTER_SUBJECT_RE,
    REPORTING_NOUN_PLURAL_FORMS,
    REPORTING_PRESENT_PARTICIPLE_FORMS,
    REPORTING_PRESENT_SINGULAR_FORMS,
    REPORTING_PROGRESSIVE_AUXILIARIES,
    SINGULAR_REPORTER_DETERMINERS,
    SINGULAR_REPORTER_PRONOUNS,
    WORD_RE,
    ReportingVerbKind,
    WordToken,
    classify_reporting_verb,
    tokens_are_space_joined,
    tokens_cover_space_joined_text,
    word_tokens,
)

_REPORTING_COMPLEMENT_SEPARATORS = frozenset({",", ":", "—", "–", "-"})
_MALFORMED_COMPLEMENT_SEPARATORS = _REPORTING_COMPLEMENT_SEPARATORS | {"/"}


@dataclass(frozen=True, slots=True)
class _ReportingExpression:
    """One finite reporting expression and its subject/tail boundaries."""

    start_index: int
    tail_index: int
    verb_kind: ReportingVerbKind
    agreement_value: str
    progressive: bool = False


def is_reporting_clause(value: str) -> bool:
    """Return whether an isolated clause is a finite reporting frame."""

    clause = _strip_leading_list_marker(" ".join(value.split()))
    tokens = tuple(word_tokens(text=clause, start=0, end=len(clause)))
    if not tokens or len(tokens) > MAX_REPORTER_WORDS + 2:
        return False
    if not tokens_cover_space_joined_text(text=clause, tokens=tokens):
        return False
    for expression in _reporting_expressions(text=clause, tokens=tokens):
        if expression.start_index > 0 and _forward_frame_is_complete(
            clause=clause,
            tokens=tokens,
            expression=expression,
        ):
            return True
        if (
            expression.start_index == 0
            and not expression.progressive
            and expression.tail_index < len(tokens)
        ):
            reporter = clause[tokens[expression.tail_index].start :].strip()
            if _is_finite_reporting_frame(
                verb_kind=expression.verb_kind,
                verb_value=expression.agreement_value,
                reporter=reporter,
                inverted=True,
                progressive=False,
            ):
                return True
    return False


def indirect_reporting_header_end(*, text: str, start: int, end: int) -> int | None:
    """Return the complement start after a bounded forward reporting frame."""

    return _reporting_header_end(text=text, start=start, end=end, malformed=False)


def malformed_reporting_header_end(*, text: str, start: int, end: int) -> int | None:
    """Return a complement start after a duplicated or mixed frame separator."""

    return _reporting_header_end(text=text, start=start, end=end, malformed=True)


def _reporting_header_end(
    *,
    text: str,
    start: int,
    end: int,
    malformed: bool,
) -> int | None:

    tokens = tuple(word_tokens(text=text, start=start, end=end))
    if not tokens:
        return None
    bounded_tokens = tokens[: MAX_REPORTER_WORDS + 2]
    for expression in _reporting_expressions(text=text, tokens=bounded_tokens):
        if expression.start_index == 0:
            continue
        reporter_start = tokens[expression.start_index].start
        reporter = _strip_leading_list_marker(text[start:reporter_start].strip())
        if not _is_finite_reporting_frame(
            verb_kind=expression.verb_kind,
            verb_value=expression.agreement_value,
            reporter=reporter,
            inverted=False,
            progressive=expression.progressive,
        ):
            continue
        tail_index = expression.tail_index
        if (
            tail_index < len(tokens)
            and tokens[tail_index].value.casefold() in POST_REPORTING_MODIFIERS
        ):
            tail_index += 1
        if tail_index >= len(tokens):
            continue
        previous = tokens[tail_index - 1]
        connector = tokens[tail_index]
        if connector.value.casefold() == "that" and tokens_are_space_joined(
            text=text,
            left=previous,
            right=connector,
        ):
            if not malformed:
                return connector.end
            continue
        separator = tuple(
            character
            for character in text[previous.end : connector.start]
            if not character.isspace()
        )
        if (
            not malformed
            and len(separator) == 1
            and (separator[0] in _REPORTING_COMPLEMENT_SEPARATORS)
        ):
            return connector.start
        if (
            malformed
            and len(separator) > 1
            and any(character in _REPORTING_COMPLEMENT_SEPARATORS for character in separator)
            and all(character in _MALFORMED_COMPLEMENT_SEPARATORS for character in separator)
        ):
            return connector.start
    return None


def _forward_frame_is_complete(
    *,
    clause: str,
    tokens: tuple[WordToken, ...],
    expression: _ReportingExpression,
) -> bool:
    reporter = clause[: tokens[expression.start_index].start].strip()
    if not _is_finite_reporting_frame(
        verb_kind=expression.verb_kind,
        verb_value=expression.agreement_value,
        reporter=reporter,
        inverted=False,
        progressive=expression.progressive,
    ):
        return False
    remaining = tokens[expression.tail_index :]
    return not remaining or (
        len(remaining) == 1 and remaining[0].value.casefold() in POST_REPORTING_MODIFIERS
    )


def _reporting_expressions(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
) -> tuple[_ReportingExpression, ...]:
    expressions: list[_ReportingExpression] = []
    for index, token in enumerate(tokens):
        verb_kind = classify_reporting_verb(token.value)
        if verb_kind is not None:
            expressions.append(
                _ReportingExpression(
                    start_index=index,
                    tail_index=_reporting_verb_tail_index(
                        text=text,
                        tokens=tokens,
                        index=index,
                    ),
                    verb_kind=verb_kind,
                    agreement_value=token.value,
                )
            )
            continue
        if index == 0 or token.value.casefold() not in REPORTING_PRESENT_PARTICIPLE_FORMS:
            continue
        auxiliary = tokens[index - 1]
        if (
            auxiliary.value.casefold() not in REPORTING_PROGRESSIVE_AUXILIARIES
            or not tokens_are_space_joined(text=text, left=auxiliary, right=token)
        ):
            continue
        expressions.append(
            _ReportingExpression(
                start_index=index - 1,
                tail_index=index + 1,
                verb_kind=ReportingVerbKind.FINITE,
                agreement_value=auxiliary.value,
                progressive=True,
            )
        )
    return tuple(expressions)


def _reporting_verb_tail_index(
    *,
    text: str,
    tokens: tuple[WordToken, ...],
    index: int,
) -> int:
    tail = index + 1
    if (
        tokens[index].value.casefold() in {"tell", "tells", "told"}
        and tail < len(tokens)
        and tokens[tail].value.casefold() in {"me", "us"}
        and tokens_are_space_joined(text=text, left=tokens[index], right=tokens[tail])
    ):
        tail += 1
    return tail


def _is_finite_reporting_frame(
    *,
    verb_kind: ReportingVerbKind,
    verb_value: str,
    reporter: str,
    inverted: bool,
    progressive: bool,
) -> bool:
    plural_source = (
        verb_kind is ReportingVerbKind.BASE
        and not inverted
        and _reporter_is_overtly_plural_source(reporter)
    )
    if not _is_third_party_reporter(reporter, allow_plural_source=plural_source):
        return False
    if progressive:
        return _progressive_agrees_with_reporter(
            auxiliary=verb_value,
            reporter=reporter,
        )
    if verb_kind is ReportingVerbKind.FINITE:
        if verb_value.casefold() in REPORTING_PRESENT_SINGULAR_FORMS:
            if verb_value.casefold() == "reports":
                return _reporter_is_overtly_singular_agent(reporter)
            return _reporter_is_overtly_singular(reporter)
        return True
    return not inverted and (_reporter_is_overtly_plural_agent(reporter) or plural_source)


def _is_third_party_reporter(value: str, *, allow_plural_source: bool = False) -> bool:
    if REPORTER_SUBJECT_RE.fullmatch(value) is None:
        return False
    words = tuple(match.group(0) for match in WORD_RE.finditer(value))
    if not words or len(words) > MAX_REPORTER_WORDS:
        return False
    folded_words = tuple(word.casefold() for word in words)
    clause_words = folded_words[:-1] if allow_plural_source else folded_words
    if any(word in REPORTER_CLAUSE_WORDS for word in clause_words):
        return False
    return not any(
        word in FIRST_OR_SECOND_PERSON_SUBJECTS and original != "US"
        for word, original in zip(folded_words, words, strict=True)
    )


def _reporter_is_overtly_plural_agent(value: str) -> bool:
    """Resolve ambiguous base forms conservatively as verbs, not report nouns."""

    words = tuple(match.group(0) for match in WORD_RE.finditer(value))
    if not words:
        return False
    folded = tuple(word.casefold() for word in words)
    if folded[-1] == "they" or "and" in folded:
        return True
    head = folded[-1]
    return head.endswith(AGENTIVE_PLURAL_SUFFIXES)


def _reporter_is_overtly_plural_source(value: str) -> bool:
    words = tuple(match.group(0).casefold() for match in WORD_RE.finditer(value))
    return bool(words) and words[-1] in REPORTING_NOUN_PLURAL_FORMS


def _reporter_is_overtly_singular_agent(value: str) -> bool:
    """Disambiguate singular ``reports`` from a plural report-noun heading."""

    words = tuple(match.group(0) for match in WORD_RE.finditer(value))
    if not words:
        return False
    folded = tuple(word.casefold() for word in words)
    if folded[0] in SINGULAR_REPORTER_PRONOUNS:
        return len(words) == 1
    head = folded[-1].rstrip("'’")
    if folded[0] in SINGULAR_REPORTER_DETERMINERS:
        return head.endswith(AGENTIVE_SINGULAR_SUFFIXES)
    return words[0][0].isupper() and not head.endswith("s")


def _progressive_agrees_with_reporter(*, auxiliary: str, reporter: str) -> bool:
    folded_auxiliary = auxiliary.casefold()
    if folded_auxiliary in {"is", "was"}:
        return _reporter_is_overtly_singular_agent(reporter)
    return _reporter_is_overtly_plural_agent(reporter)


def _reporter_is_overtly_singular(value: str) -> bool:
    """Require singular-present frames to expose a grammatical subject shape."""

    words = tuple(match.group(0) for match in WORD_RE.finditer(value))
    if not words:
        return False
    folded = tuple(word.casefold() for word in words)
    if folded[0] in SINGULAR_REPORTER_PRONOUNS:
        return len(words) == 1
    if words[0][0].isupper():
        return True
    if folded[0] not in SINGULAR_REPORTER_DETERMINERS:
        return False
    head = folded[-1].rstrip("'’")
    return not head.endswith("s") or head.endswith(("is", "ss", "us"))


def _strip_leading_list_marker(value: str) -> str:
    return LEADING_LIST_MARKER_RE.sub("", value, count=1).strip()
