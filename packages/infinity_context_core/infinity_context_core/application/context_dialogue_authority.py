"""Role-aware authority policy for bounded dialogue evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ROLE_MARKER_RE = re.compile(r"(?<![\w-])(?P<role>user|assistant)\s*:\s*", re.IGNORECASE)
_SELF_REFERENCE_RE = re.compile(
    r"\b(?:i|i['’](?:m|ve|d|ll)|me|my|mine|myself)\b",
    re.IGNORECASE,
)
_SELF_QUERY_RE = re.compile(r"\b(?:i|me|my|mine|myself)\b", re.IGNORECASE)
_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|neither|without|cannot|can't|won't|isn't|aren't|wasn't|weren't|"
    r"don't|doesn't|didn't|haven't|hasn't|hadn't)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_DIGIT_VALUE_RE = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?%?(?!\w)")
_CLAUSE_RE = re.compile(r"[^.!?;\n]+[.!?;]?", re.UNICODE)
_DISTRIBUTIVE_RE = re.compile(r"\b(?:each|every|per)\b", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"\b(?:a|an)\b", re.IGNORECASE)

_NUMBER_WORD_VALUES = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
_CONTEXT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class DialogueEvidenceRange:
    """A contiguous source range selected for prompt-visible evidence."""

    char_start: int
    char_end: int


@dataclass(frozen=True)
class _DialogueTurn:
    role: str
    marker_start: int
    body_start: int
    end: int


def prefer_direct_user_assertion(
    *,
    query: str,
    text: str,
    char_start: int,
    char_end: int,
) -> DialogueEvidenceRange:
    """Clip a conflicting assistant paraphrase after a relevant user assertion.

    The policy is deliberately narrow. It applies only to first-person queries and
    explicit ``user:``/``assistant:`` dialogue. A later assistant turn is clipped
    only when a query-relevant user statement about their own state and an
    overlapping assistant statement assert incompatible values or polarity.
    """

    selected = DialogueEvidenceRange(
        char_start=max(0, char_start),
        char_end=min(len(text), max(char_start, char_end)),
    )
    if not _SELF_QUERY_RE.search(query):
        return selected
    turns = _dialogue_turns(text)
    if not turns:
        return selected
    query_tokens = _context_tokens(query)
    for index, user_turn in enumerate(turns[:-1]):
        assistant_turn = turns[index + 1]
        if user_turn.role != "user" or assistant_turn.role != "assistant":
            continue
        if assistant_turn.marker_start >= selected.char_end:
            continue
        if user_turn.end <= selected.char_start:
            continue
        user_text = text[user_turn.body_start : user_turn.end]
        assistant_text = text[assistant_turn.body_start : assistant_turn.end]
        if not _is_direct_relevant_user_assertion(user_text, query_tokens=query_tokens):
            continue
        if not _has_conflicting_paraphrase(user_text, assistant_text):
            continue
        if assistant_turn.marker_start <= selected.char_start:
            continue
        return DialogueEvidenceRange(
            char_start=selected.char_start,
            char_end=assistant_turn.marker_start,
        )
    return selected


def _dialogue_turns(text: str) -> tuple[_DialogueTurn, ...]:
    markers = tuple(_ROLE_MARKER_RE.finditer(text))
    if len(markers) < 2:
        return ()
    return tuple(
        _DialogueTurn(
            role=marker.group("role").casefold(),
            marker_start=marker.start(),
            body_start=marker.end(),
            end=markers[index + 1].start() if index + 1 < len(markers) else len(text),
        )
        for index, marker in enumerate(markers)
    )


def _is_direct_relevant_user_assertion(
    text: str,
    *,
    query_tokens: frozenset[str],
) -> bool:
    if not _SELF_REFERENCE_RE.search(text):
        return False
    for clause in _clauses(text):
        if "?" in clause or not _SELF_REFERENCE_RE.search(clause):
            continue
        if _context_tokens(clause) & query_tokens:
            return True
    return False


def _has_conflicting_paraphrase(user_text: str, assistant_text: str) -> bool:
    for user_clause in _clauses(user_text):
        user_context = _context_tokens(user_clause)
        if len(user_context) < 2:
            continue
        for assistant_clause in _clauses(assistant_text):
            if len(user_context & _context_tokens(assistant_clause)) < 2:
                continue
            user_values = _asserted_values(user_clause)
            assistant_values = _asserted_values(assistant_clause)
            if user_values and assistant_values and user_values.isdisjoint(assistant_values):
                return True
            if bool(_NEGATION_RE.search(user_clause)) != bool(
                _NEGATION_RE.search(assistant_clause)
            ):
                return True
    return False


def _asserted_values(text: str) -> frozenset[str]:
    values = {
        match.group(0).casefold().replace(",", "") for match in _DIGIT_VALUE_RE.finditer(text)
    }
    values.update(
        _NUMBER_WORD_VALUES[token]
        for token in _tokens(text)
        if token in _NUMBER_WORD_VALUES
    )
    if _DISTRIBUTIVE_RE.search(text) and _ARTICLE_RE.search(text):
        values.add("1")
    return frozenset(values)


def _clauses(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).strip()
        for match in _CLAUSE_RE.finditer(text)
        if match.group(0).strip()
    )


def _context_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _tokens(text)
        if token not in _CONTEXT_STOP_WORDS
        and token not in _NUMBER_WORD_VALUES
        and not token.replace(",", "").replace(".", "", 1).isdigit()
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold().replace("’", "'") for match in _TOKEN_RE.finditer(text))
