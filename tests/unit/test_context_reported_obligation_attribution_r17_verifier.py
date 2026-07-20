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


def _assert_reported_only(*, query: str, text: str) -> None:
    projection = _projection(query=query, text=text)

    assert third_party_reported_obligation_spans(text)
    assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize(
    ("subject", "query"),
    (
        (
            "Mary-Jane O’Connor",
            "Which dispatch manifest must Mary-Jane O’Connor approve?",
        ),
        (
            "the compliance auditor",
            "Which dispatch manifest must the compliance auditor approve?",
        ),
        (
            "the intermodal wayfinding cartographer",
            "Which dispatch manifest must the intermodal wayfinding cartographer approve?",
        ),
        (
            "the crew’s nocturnal liaison",
            "Which dispatch manifest must the crew’s nocturnal liaison approve?",
        ),
        (
            "warehouse robots",
            "Which dispatch manifest must warehouse robots approve?",
        ),
        (
            "each rotating warehouse liaison",
            "Which dispatch manifest must each rotating warehouse liaison approve?",
        ),
    ),
)
def test_r17_typographic_apostrophes_and_open_ended_noun_subjects_are_local(
    subject: str,
    query: str,
) -> None:
    direct = f"{subject} must approve the dispatch manifest"

    assert third_party_reported_obligation_spans(direct) == ()
    _assert_direct(query=query, text=direct, expected=direct)
    _assert_reported_only(
        query=query,
        text=f"The unlisted cross-dock ombudsperson reported: “{direct}.”",
    )
    _assert_reported_only(
        query=query,
        text=f"The unlisted cross-dock ombudsperson reported that {direct}.",
    )


@pytest.mark.parametrize(
    "text",
    (
        f'The outage report: "{MORGAN_DIRECT}."',
        f'The outage report, "{MORGAN_DIRECT}."',
        f'Please report: "{MORGAN_DIRECT}."',
        f'"{MORGAN_DIRECT}," report the outage.',
        f'The status report: "{MORGAN_DIRECT}."',
        f'The news report, “{MORGAN_DIRECT}.”',
        f'The operations report — “{MORGAN_DIRECT}.”',
    ),
)
def test_r17_report_nouns_and_imperatives_never_create_a_reporter(text: str) -> None:
    assert third_party_reported_obligation_spans(text) == ()
    assert is_direct_source_sibling_obligation_evidence(
        query_text=MORGAN_QUERY,
        text=text,
    )


def test_r17_minimal_news_report_noun_is_not_a_reporting_frame() -> None:
    assert third_party_reported_obligation_spans('News report:"M must go"') == ()


@pytest.mark.parametrize(
    "text",
    (
        f'The auditors report: "{MORGAN_DIRECT}."',
        f'The auditor reports: “{MORGAN_DIRECT}.”',
        f'The cross-dock ombudsperson reported — “{MORGAN_DIRECT}.”',
        f'“{MORGAN_DIRECT},” the crew’s liaison reported.',
    ),
)
def test_r17_finite_reporting_verbs_with_unlisted_reporters_are_attributed(
    text: str,
) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r17_split_closing_quote_keeps_the_preceding_obligation_attributed() -> None:
    text = (
        f'"{MORGAN_DIRECT}," the supervisor reported, '
        '"and the coordinator agreed."'
    )

    spans = third_party_reported_obligation_spans(text)

    assert len(spans) == 1
    assert text[slice(*spans[0])] == f"{MORGAN_DIRECT},"
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r17_adjacent_quoted_complements_share_the_explicit_reporter() -> None:
    first = "Alex must approve the loading sheet"
    second = f"{MORGAN_DIRECT}."
    text = f'The supervisor reported: “{first}” and “{second}”'

    reported = tuple(text[start:end] for start, end in third_party_reported_obligation_spans(text))

    assert reported == (first, second)
    _assert_reported_only(query=MORGAN_QUERY, text=text)


def test_r17_split_quoted_predicate_cannot_be_promoted_as_direct_evidence() -> None:
    text = 'The supervisor reported: “Morgan must” “approve the dispatch manifest.”'
    projection = _projection(query=MORGAN_QUERY, text=text)

    assert not is_direct_source_sibling_obligation_evidence(
        query_text=MORGAN_QUERY,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize(
    "render",
    (
        lambda value: f'The supervisor reported: "{value}."',
        lambda value: f"The supervisor reported: '{value}.'",
        lambda value: f"The supervisor reported: “{value}.”",
        lambda value: f"The supervisor reported: ‘{value}.’",
    ),
)
def test_r17_balanced_straight_and_curly_quotes_are_attributed(
    render: Callable[[str], str],
) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=render(MORGAN_DIRECT))


@pytest.mark.parametrize("opener", ('"', "'", "“", "‘"))
def test_r17_unclosed_reported_quotes_fail_closed_at_candidate_admission(
    opener: str,
) -> None:
    text = f"The supervisor reported: {opener}{MORGAN_DIRECT}."
    projection = _projection(query=MORGAN_QUERY, text=text)

    assert third_party_reported_obligation_spans(text) == ()
    assert not is_direct_source_sibling_obligation_evidence(
        query_text=MORGAN_QUERY,
        text=text,
    )
    assert projection.rank != 0
    assert not projection.applied


@pytest.mark.parametrize("opener", ('"', "“"))
def test_r17_unclosed_quote_does_not_leak_across_a_newline(opener: str) -> None:
    text = f"{opener}malformed quote\n{MORGAN_DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


@pytest.mark.parametrize(
    "text",
    (
        f'The supervisor reported: "{MORGAN_DIRECT}."',
        f'The supervisor reported, “{MORGAN_DIRECT}.”',
        f'The supervisor reported — “{MORGAN_DIRECT}.”',
        f'The supervisor reported that {MORGAN_DIRECT}.',
        f'The supervisor reported: {MORGAN_DIRECT}.',
    ),
)
def test_r17_reporting_punctuation_forms_remain_attributed(text: str) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


@pytest.mark.parametrize(
    "text",
    (
        f'The supervisor reported:\n"{MORGAN_DIRECT}."',
        f'The supervisor reported that\n{MORGAN_DIRECT}.',
        f'"{MORGAN_DIRECT},"\nthe supervisor reported.',
    ),
)
def test_r17_line_wrapping_inside_a_reporting_clause_preserves_attribution(
    text: str,
) -> None:
    _assert_reported_only(query=MORGAN_QUERY, text=text)


@pytest.mark.parametrize("reported_first", (False, True))
def test_r17_reported_and_direct_multiline_clauses_stay_candidate_local(
    reported_first: bool,
) -> None:
    reported = f'The supervisor reported: “{MORGAN_DIRECT}.”'
    clauses = (reported, MORGAN_DIRECT) if reported_first else (MORGAN_DIRECT, reported)
    text = ";\n".join(clauses)

    spans = third_party_reported_obligation_spans(text)

    assert len(spans) == 1
    assert text[slice(*spans[0])] == f"{MORGAN_DIRECT}."
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


def test_r17_multiple_reporters_are_attributed_without_cross_candidate_state() -> None:
    alex = "Alex must approve the loading sheet"
    text = (
        f'The auditor stated: “{alex}.”; '
        f'“{MORGAN_DIRECT},” the supervisor and coordinator reported.'
    )

    reported = tuple(text[start:end] for start, end in third_party_reported_obligation_spans(text))

    assert reported == (f"{alex}.", f"{MORGAN_DIRECT},")
    _assert_reported_only(query=MORGAN_QUERY, text=text)


@pytest.mark.parametrize("direct_first", (False, True))
def test_r17_reported_candidate_cannot_leak_into_a_direct_candidate(
    direct_first: bool,
) -> None:
    reported = f'The supervisor reported: “{MORGAN_DIRECT}.”'
    candidates = (MORGAN_DIRECT, reported) if direct_first else (reported, MORGAN_DIRECT)

    outcomes = tuple(
        (
            is_direct_source_sibling_obligation_evidence(
                query_text=MORGAN_QUERY,
                text=candidate,
            ),
            _projection(query=MORGAN_QUERY, text=candidate).rank,
        )
        for candidate in candidates
    )

    expected = ((True, 0), (False, 3)) if direct_first else ((False, 3), (True, 0))
    assert outcomes == expected


@pytest.mark.parametrize(
    ("text", "expected_direct"),
    (
        (
            f'The supervisor reported: “{MORGAN_DIRECT}.”; '
            "Morgan must approve the cafeteria menu.",
            False,
        ),
        (
            'The supervisor reported: “Alex must approve the loading sheet.”; '
            f"{MORGAN_DIRECT}.",
            True,
        ),
        (
            "Morgan must approve the cafeteria menu; "
            'The supervisor reported: “Alex must approve the dispatch manifest.”',
            False,
        ),
    ),
)
def test_r17_query_scope_and_reported_spans_are_candidate_local(
    text: str,
    expected_direct: bool,
) -> None:
    projection = _projection(query=MORGAN_QUERY, text=text)

    assert (
        is_direct_source_sibling_obligation_evidence(
            query_text=MORGAN_QUERY,
            text=text,
        )
        is expected_direct
    )
    assert projection.applied is expected_direct
    assert (projection.rank == 0) is expected_direct
    if expected_direct:
        assert projection.text == MORGAN_DIRECT


@pytest.mark.parametrize(
    "text",
    (
        "",
        "'",
        "“”",
        "\x00\ud800;;;\n",
        "report report report",
        "The supervisor reported that",
    ),
)
def test_r17_malformed_input_is_rejected_without_attribution(text: str) -> None:
    assert third_party_reported_obligation_spans(text) == ()


def test_r17_long_malformed_header_cannot_capture_a_later_direct_clause() -> None:
    malformed = "The supervisor reported that " + "very " * 1_000 + "Morgan must"
    text = f"{malformed}. {MORGAN_DIRECT}."

    assert third_party_reported_obligation_spans(text) == ()
    _assert_direct(query=MORGAN_QUERY, text=text, expected=MORGAN_DIRECT)


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


def test_r17_quote_scanner_read_growth_is_linear_at_1k_and_4k() -> None:
    reads: list[int] = []
    lengths: list[int] = []
    for quote_count in (1_000, 4_000):
        text = _CountingText("“" * quote_count + f"\n{MORGAN_DIRECT}.")

        assert third_party_reported_obligation_spans(text) == ()
        assert text.reads <= len(text) * 12
        reads.append(text.reads)
        lengths.append(len(text))

    assert reads[1] <= reads[0] * 4 + 64
    assert reads[1] / lengths[1] <= reads[0] / lengths[0] * 1.10
