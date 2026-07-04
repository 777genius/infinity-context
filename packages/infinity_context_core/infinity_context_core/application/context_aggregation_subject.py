"""Subject grounding checks for aggregation/count evidence reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_counts,
)

_PERSON_NAME_RE = re.compile(r"\b[A-Z][a-z][A-Za-z'_-]{1,39}\b")
_QUESTION_PERSON_STOPWORDS = frozenset(
    {
        "How",
        "List",
        "Name",
        "Show",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
    }
)
_AGGREGATION_SCAFFOLD_TERMS = frozenset(
    {
        "all",
        "answer",
        "answers",
        "both",
        "count",
        "counts",
        "each",
        "every",
        "evidence",
        "item",
        "items",
        "kind",
        "kinds",
        "list",
        "many",
        "mention",
        "mentioned",
        "name",
        "number",
        "numbers",
        "show",
        "thing",
        "things",
        "time",
        "times",
        "total",
        "type",
        "types",
        "which",
        "what",
        "where",
        "who",
    }
)


@dataclass(frozen=True)
class AggregationSubjectGrounding:
    query_subject_term_count: int
    matched_subject_term_count: int
    query_person_count: int
    matched_person_count: int
    text_person_count: int

    @property
    def subject_mismatch(self) -> bool:
        if self.query_person_count and not self.matched_person_count and self.text_person_count:
            return True
        return self.query_subject_term_count > 0 and self.matched_subject_term_count == 0


def aggregation_subject_grounding(*, query: str, text: str) -> AggregationSubjectGrounding:
    """Compare requested subject terms with candidate evidence text.

    Aggregation retrieval intentionally gathers enumerations broadly. This helper
    keeps the reranker from rewarding a well-formed count/list about a different
    subject, while allowing pronoun-heavy snippets when they do not name a
    conflicting person.
    """

    query_people = _query_person_terms(query)
    text_people = _query_person_terms(text)
    text_counts = text_variant_counts(text)
    subject_terms = _subject_terms(query=query, query_people=query_people)
    matched_subject_terms = sum(
        1 for term in subject_terms if query_term_frequency(term, text_counts) > 0
    )
    matched_people = {
        person for person in query_people if query_term_frequency(person, text_counts) > 0
    }
    return AggregationSubjectGrounding(
        query_subject_term_count=len(subject_terms),
        matched_subject_term_count=matched_subject_terms,
        query_person_count=len(query_people),
        matched_person_count=len(matched_people),
        text_person_count=len(text_people),
    )


def aggregation_subject_mismatch(*, query: str, text: str) -> bool:
    return aggregation_subject_grounding(query=query, text=text).subject_mismatch


def _subject_terms(
    *,
    query: str,
    query_people: frozenset[LexicalQueryTerm],
) -> tuple[LexicalQueryTerm, ...]:
    people = {person.raw for person in query_people}
    terms: list[LexicalQueryTerm] = []
    for term in query_terms(query):
        if term.raw in people:
            continue
        if term.raw.isdigit() or term.raw in _AGGREGATION_SCAFFOLD_TERMS:
            continue
        terms.append(term)
    return tuple(terms)


def _query_person_terms(text: str) -> frozenset[LexicalQueryTerm]:
    return frozenset(
        term
        for name in _PERSON_NAME_RE.findall(text)
        if name not in _QUESTION_PERSON_STOPWORDS
        for term in query_terms(name)
    )
