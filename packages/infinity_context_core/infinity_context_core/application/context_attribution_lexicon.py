"""Lexical classes shared by the bounded attribution parser."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

_WORD_PART = r"[^\W\d_]+(?:['’][^\W\d_]+)*(?:['’])?"
WORD_RE = re.compile(rf"{_WORD_PART}(?:-{_WORD_PART})*")
REPORTER_SUBJECT_RE = re.compile(rf"{WORD_RE.pattern}(?:\s+{WORD_RE.pattern})*")
LEADING_LIST_MARKER_RE = re.compile(r"^(?:[-+*•]|\d+[.)])\s+")

REPORTING_BASE_FORMS = frozenset(
    {
        "announce",
        "claim",
        "confirm",
        "declare",
        "explain",
        "insist",
        "mention",
        "note",
        "reply",
        "report",
        "say",
        "state",
        "tell",
        "warn",
        "write",
    }
)
REPORTING_FINITE_FORMS = frozenset(
    {
        "announced",
        "announces",
        "claimed",
        "claims",
        "confirmed",
        "confirms",
        "declared",
        "declares",
        "explained",
        "explains",
        "insisted",
        "insists",
        "mentioned",
        "mentions",
        "noted",
        "notes",
        "replied",
        "replies",
        "reported",
        "reports",
        "said",
        "says",
        "stated",
        "states",
        "tells",
        "told",
        "warned",
        "warns",
        "writes",
        "wrote",
    }
)
REPORTING_PRESENT_SINGULAR_FORMS = frozenset(
    {
        "announces",
        "claims",
        "confirms",
        "declares",
        "explains",
        "insists",
        "mentions",
        "notes",
        "reports",
        "replies",
        "says",
        "states",
        "tells",
        "warns",
        "writes",
    }
)
REPORTING_PRESENT_PARTICIPLE_FORMS = frozenset(
    {
        "announcing",
        "claiming",
        "confirming",
        "declaring",
        "explaining",
        "insisting",
        "mentioning",
        "noting",
        "replying",
        "reporting",
        "saying",
        "stating",
        "telling",
        "warning",
        "writing",
    }
)
REPORTING_PROGRESSIVE_AUXILIARIES = frozenset({"are", "is", "was", "were"})
REPORTING_NOUN_PLURAL_FORMS = frozenset({"reports"})
REPORTER_CLAUSE_WORDS = REPORTING_FINITE_FORMS | frozenset(
    {
        "am",
        "are",
        "be",
        "been",
        "being",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "please",
        "was",
        "were",
        "will",
        "would",
    }
)
POST_REPORTING_MODIFIERS = frozenset(
    {
        "again",
        "briefly",
        "calmly",
        "clearly",
        "earlier",
        "explicitly",
        "later",
        "now",
        "quietly",
        "then",
        "today",
        "tonight",
        "urgently",
        "yesterday",
    }
)
FIRST_OR_SECOND_PERSON_SUBJECTS = frozenset({"i", "me", "us", "we", "you"})
OBLIGATION_SUBJECT_PRONOUNS = frozenset({"i", "we", "he", "she", "they"})
PRE_MODAL_MODIFIERS = frozenset({"also", "just", "really", "still"})
PREDICATE_NEGATIONS = frozenset({"never", "not"})
SUBJECT_DETERMINERS = frozenset({"a", "an", "each", "the", "this", "that"})
SUBJECT_BOUNDARIES = frozenset(
    {
        "am",
        "and",
        "are",
        "because",
        "but",
        "did",
        "do",
        "does",
        "if",
        "is",
        "never",
        "not",
        "or",
        "reported",
        "said",
        "stated",
        "that",
        "then",
        "was",
        "were",
        "when",
        "while",
    }
)
AGENTIVE_PLURAL_SUFFIXES = ("ants", "ents", "ers", "ians", "ists", "ors")
AGENTIVE_SINGULAR_SUFFIXES = ("er", "ian", "ist", "or", "person")
SINGULAR_REPORTER_DETERMINERS = frozenset({"a", "an", "each", "every", "that", "the", "this"})
SINGULAR_REPORTER_PRONOUNS = frozenset({"he", "it", "she"})

MAX_NAMED_SUBJECT_WORDS = 4
MAX_NOUN_PHRASE_SUBJECT_WORDS = 8
MAX_REPORTER_WORDS = 32


class ReportingVerbKind(Enum):
    """Syntactic information supplied by a reporting verb token."""

    BASE = "base"
    FINITE = "finite"


@dataclass(frozen=True, slots=True)
class WordToken:
    value: str
    start: int
    end: int


def classify_reporting_verb(value: str) -> ReportingVerbKind | None:
    """Classify a reporting token without deciding whether it forms a frame."""

    folded = value.casefold()
    if folded in REPORTING_FINITE_FORMS:
        return ReportingVerbKind.FINITE
    if folded in REPORTING_BASE_FORMS:
        return ReportingVerbKind.BASE
    return None


def word_tokens(*, text: str, start: int, end: int) -> Iterator[WordToken]:
    for match in WORD_RE.finditer(text, start, end):
        yield WordToken(value=match.group(0), start=match.start(), end=match.end())


def tokens_are_space_joined(*, text: str, left: WordToken, right: WordToken) -> bool:
    gap = text[left.end : right.start]
    return bool(gap) and gap.isspace()


def tokens_cover_space_joined_text(*, text: str, tokens: tuple[WordToken, ...]) -> bool:
    if text[: tokens[0].start].strip() or text[tokens[-1].end :].strip():
        return False
    return all(
        tokens_are_space_joined(text=text, left=left, right=right)
        for left, right in zip(tokens, tokens[1:], strict=False)
    )


def is_word_apostrophe(
    *,
    text: str,
    index: int,
) -> bool:
    """Distinguish lexical apostrophes from straight or curly quote marks."""

    if text[index] not in {"'", "’"}:
        return False
    internal = (
        index > 0
        and index + 1 < len(text)
        and text[index - 1].isalnum()
        and text[index + 1].isalnum()
    )
    if internal:
        return True
    return (
        index > 0
        and index + 1 < len(text)
        and text[index - 1].casefold() == "s"
        and text[index + 1].isspace()
    )
