from __future__ import annotations

import pytest
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_reported_obligation_attribution import (
    third_party_reported_obligation_spans,
)
from infinity_context_core.application.context_source_siblings import (
    is_direct_source_sibling_obligation_evidence,
    project_source_sibling_obligation_evidence,
)

QUERY = "Which dispatch manifest must Morgan approve?"
DIRECT = "Morgan must approve the dispatch manifest"


@pytest.mark.parametrize(
    "reported",
    (
        'The supervisor reported: "Morgan must approve the dispatch manifest."',
        "The supervisor reported that Morgan must approve the dispatch manifest.",
    ),
)
def test_named_subject_report_is_not_admitted_as_direct_obligation(reported: str) -> None:
    projection = project_source_sibling_obligation_evidence(
        query_text=QUERY,
        relevance=score_query_relevance(query=QUERY, text=reported),
        text=reported,
    )

    assert not is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=reported)
    assert projection.rank != 0
    assert not projection.applied
    assert third_party_reported_obligation_spans(reported)


def test_named_subject_direct_clause_excludes_matching_reported_sibling() -> None:
    text = f'{DIRECT}. The supervisor reported: "Morgan must approve the dispatch manifest."'
    projection = project_source_sibling_obligation_evidence(
        query_text=QUERY,
        relevance=score_query_relevance(query=QUERY, text=text),
        text=text,
    )

    assert is_direct_source_sibling_obligation_evidence(query_text=QUERY, text=text)
    assert projection.rank == 0
    assert projection.text == DIRECT
    assert len(projection.spans) == 1
    assert third_party_reported_obligation_spans(text)
