from __future__ import annotations

from collections.abc import Callable

import pytest
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_reported_obligation_attribution import (
    third_party_reported_obligation_spans,
)
from infinity_context_core.application.context_source_siblings import (
    is_direct_source_sibling_obligation_evidence,
    project_source_sibling_obligation_evidence,
)

MORGAN_QUERY = "Which dispatch manifest must Morgan approve?"
MORGAN_DIRECT = "Morgan must approve the dispatch manifest"


def _projection(*, query: str, text: str):  # type: ignore[no-untyped-def]
    return project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )


def _assert_direct(*, query: str, text: str, expected: str) -> None:
    projection = _projection(query=query, text=text)

    assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank == 0
    assert projection.applied
    assert projection.text == expected
    assert projection.spans
    assert all(text[slice(*span)] in expected for span in projection.spans)


def _assert_reported_only(*, query: str, text: str) -> None:
    projection = _projection(query=query, text=text)

    assert third_party_reported_obligation_spans(text)
    assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize(
    ("subject", "query"),
    (
        ("Morgan", MORGAN_QUERY),
        ("Alexandra Morgan", "Which dispatch manifest must Alexandra Morgan approve?"),
        ("Jean-Luc O'Neill", "Which dispatch manifest must Jean-Luc O'Neill approve?"),
        ("Mary-Jane O’Connor", "Which dispatch manifest must Mary-Jane O’Connor approve?"),
        ("he", "Which dispatch manifest must he approve?"),
        ("she", "Which dispatch manifest must she approve?"),
        ("they", "Which dispatch manifest must they approve?"),
        (
            "the regional night-shift supervisor",
            "Which dispatch manifest must the regional night-shift supervisor approve?",
        ),
        (
            "the compliance auditor",
            "Which dispatch manifest must the compliance auditor approve?",
        ),
    ),
)
def test_r16_subject_matrix_is_clause_local_for_direct_quoted_and_indirect_forms(
    subject: str,
    query: str,
) -> None:
    direct = f"{subject} must approve the dispatch manifest"
    quoted = f'The coordinator reported: "{direct}."'
    indirect = f"The coordinator reported that {direct}."

    assert third_party_reported_obligation_spans(direct) == ()
    _assert_direct(query=query, text=direct, expected=direct)
    _assert_reported_only(query=query, text=quoted)
    _assert_reported_only(query=query, text=indirect)


@pytest.mark.parametrize(
    "text",
    (
        f'The supervisor reported: "{MORGAN_DIRECT}."',
        f'The supervisor reported, "{MORGAN_DIRECT}."',
        f'"{MORGAN_DIRECT}," the supervisor reported.',
        f"The supervisor reported: {MORGAN_DIRECT}.",
        f"The supervisor reported that {MORGAN_DIRECT}.",
    ),
)
def test_r16_colon_comma_quoted_and_indirect_reporting_forms_are_attributed(
    text: str,
) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r16_named_obligation_without_a_reporter_stays_direct() -> None:
    _assert_direct(query=MORGAN_QUERY, text=MORGAN_DIRECT, expected=MORGAN_DIRECT)


def test_r16_prior_self_report_does_not_leak_into_the_next_sentence() -> None:
    text = f"I reported the outage. {MORGAN_DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


@pytest.mark.parametrize("boundary", ("; ", "\n"))
@pytest.mark.parametrize("reported_first", (False, True))
def test_r16_reported_and_matching_direct_clauses_survive_in_both_orders(
    boundary: str,
    reported_first: bool,
) -> None:
    reported = f'The supervisor reported: "{MORGAN_DIRECT}"'
    clauses = (reported, MORGAN_DIRECT) if reported_first else (MORGAN_DIRECT, reported)
    text = boundary.join(clauses)

    spans = third_party_reported_obligation_spans(text)

    assert len(spans) == 1
    assert text[slice(*spans[0])] == MORGAN_DIRECT
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


@pytest.mark.parametrize(
    "prefix",
    (
        "The outage report was archived.",
        "The outage was reported yesterday.",
        "The reporting dashboard is offline.",
    ),
)
def test_r16_unrelated_report_word_forms_do_not_contaminate_a_later_clause(
    prefix: str,
) -> None:
    text = f"{prefix} {MORGAN_DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


@pytest.mark.parametrize(
    "text",
    (
        f'The outage report: "{MORGAN_DIRECT}."',
        f'The outage report, "{MORGAN_DIRECT}."',
        f'Please report: "{MORGAN_DIRECT}."',
        f'"{MORGAN_DIRECT}," report the outage.',
    ),
)
def test_r16_noun_and_imperative_report_are_not_third_party_reporters(text: str) -> None:
    assert third_party_reported_obligation_spans(text) == ()


@pytest.mark.parametrize(
    "text",
    (
        f'The supervisor reported: "She said, \'{MORGAN_DIRECT}.\'"',
        f'The supervisor reported: "“{MORGAN_DIRECT}.”"',
        f'The supervisor reported: “\'{MORGAN_DIRECT}.\'”',
        f'"{MORGAN_DIRECT}," the supervisor reported, "and the coordinator agreed."',
    ),
)
def test_r16_nested_and_split_closing_quotes_remain_reporter_attributed(text: str) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r16_closed_quote_and_report_in_separate_sentences_remains_direct() -> None:
    text = f'"{MORGAN_DIRECT}." The supervisor reported the outage.'
    projection = _projection(query=MORGAN_QUERY, text=text)

    assert third_party_reported_obligation_spans(text) == ()
    assert is_direct_source_sibling_obligation_evidence(
        query_text=MORGAN_QUERY,
        text=text,
    )
    assert projection.rank == 0
    assert projection.applied
    assert MORGAN_DIRECT in projection.text


@pytest.mark.parametrize(
    "text",
    (
        f'The supervisor reported: "{MORGAN_DIRECT.replace(" must ", " must not ")}."',
        f"The supervisor reported that {MORGAN_DIRECT.replace(' must ', ' must never ')}.",
    ),
)
def test_r16_reported_negation_is_attributed_and_never_promoted(text: str) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r16_direct_negation_is_not_positive_obligation_evidence() -> None:
    text = MORGAN_DIRECT.replace(" must ", " must not ")
    projection = _projection(query=MORGAN_QUERY, text=text)

    assert third_party_reported_obligation_spans(text) == ()
    assert not is_direct_source_sibling_obligation_evidence(
        query_text=MORGAN_QUERY,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize("modifier", ("calmly", "clearly", "explicitly", "urgently"))
@pytest.mark.parametrize(
    "render",
    (
        lambda modifier: f'The supervisor reported {modifier}: "{MORGAN_DIRECT}."',
        lambda modifier: f'"{MORGAN_DIRECT}," the supervisor reported {modifier}.',
        lambda modifier: f"The supervisor reported {modifier} that {MORGAN_DIRECT}.",
    ),
)
def test_r16_reporting_modifiers_are_bounded_but_supported(
    modifier: str,
    render: Callable[[str], str],
) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=render(modifier))


class _CountingText(str):
    reads: int

    def __new__(cls, value: str) -> _CountingText:
        instance = super().__new__(cls, value)
        instance.reads = 0
        return instance

    def __getitem__(self, key: int | slice) -> str:
        if isinstance(key, int):
            self.reads += 1
        return super().__getitem__(key)


def test_r16_many_unclosed_curly_quotes_have_a_linear_character_scan_bound() -> None:
    text = _CountingText("“" * 1_000 + f"\n{MORGAN_DIRECT}.")

    assert third_party_reported_obligation_spans(text) == ()
    assert text.reads <= len(text) * 12


def test_r16_long_malformed_clause_does_not_capture_a_later_direct_sentence() -> None:
    malformed = "The supervisor reported that " + "very " * 5_000 + "Morgan must"
    text = f"{malformed}. {MORGAN_DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)
