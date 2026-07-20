from __future__ import annotations

import pytest
from infinity_context_core.application.context_reported_obligation_attribution import (
    third_party_reported_obligation_spans,
)


@pytest.mark.parametrize(
    "text",
    (
        '- The supervisor reported: "I must approve the dispatch manifest."',
        '* Alexandra Morgan stated: "I need to approve the dispatch manifest."',
        "+ The supervisor confirmed: “I still have to approve the dispatch manifest.”",
        "1) The supervisor reported: ‘I should approve the dispatch manifest.’",
        "• The supervisor reported that I must approve the dispatch manifest.",
        '"I must approve the dispatch manifest" the supervisor reported.',
        "‘I need to approve the dispatch manifest’ Alexandra Morgan stated.",
        '"We have to approve the dispatch manifest" reported the supervisor.',
        '"I must approve the dispatch manifest," the supervisor reported briefly.',
        "“I need to approve the dispatch manifest,” Alexandra Morgan stated quietly.",
        'The supervisor reported yesterday: "I must approve the dispatch manifest."',
        "The supervisor reported earlier that I must approve the dispatch manifest.",
        (
            "The senior vice president of global warehouse and regional field operations "
            'reported: "I must approve the dispatch manifest."'
        ),
        (
            '"I must approve the dispatch manifest," the senior vice president of global '
            "warehouse and regional field operations reported."
        ),
        'Alexandra Morgan stated: "I must approve the dispatch manifest."',
        '"I must approve the dispatch manifest," Alexandra Morgan stated.',
        'She reported: "I must approve the dispatch manifest."',
        "“I must approve the dispatch manifest,” they reported.",
        'The supervisor reported: "I must not approve the dispatch manifest."',
        "The supervisor reported that I must not approve the dispatch manifest.",
        "The supervisor said that we need to approve the dispatch manifest.",
        "The supervisor told me that I have to approve the dispatch manifest.",
        "Reported the supervisor — “I must approve the dispatch manifest.”",
        "The supervisor stated: 'I must approve the dispatch manifest.'",
        "The supervisor stated: “I must approve the dispatch manifest.”",
        "The supervisor stated: ‘I must approve the dispatch manifest.’",
    ),
)
def test_reported_obligation_matrix_attributes_complete_third_party_clauses(
    text: str,
) -> None:
    spans = third_party_reported_obligation_spans(text)

    assert spans
    assert all("approve" in text[start:end] for start, end in spans)


@pytest.mark.parametrize(
    "subject_predicate",
    (
        "Morgan must approve",
        "Alexandra Morgan needs to approve",
        "she should approve",
        "they have to approve",
        "the night shift supervisor must approve",
    ),
)
@pytest.mark.parametrize(
    "template",
    (
        'The coordinator reported: "{clause} the dispatch manifest."',
        "The coordinator reported that {clause} the dispatch manifest.",
    ),
)
def test_reported_obligation_parser_supports_bounded_subject_predicates(
    subject_predicate: str,
    template: str,
) -> None:
    text = template.format(clause=subject_predicate)

    spans = third_party_reported_obligation_spans(text)

    assert len(spans) == 1
    assert text[slice(*spans[0])].startswith(subject_predicate)
    assert "dispatch manifest" in text[slice(*spans[0])]


@pytest.mark.parametrize(
    "text",
    (
        "I must approve the dispatch manifest.",
        '"I must approve the dispatch manifest."',
        "'I must approve the dispatch manifest.'",
        "“I must approve the dispatch manifest.”",
        "‘I must approve the dispatch manifest.’",
        "I reported that I must approve the dispatch manifest.",
        '"I must approve the dispatch manifest," I reported briefly.',
        "You said that I must approve the dispatch manifest.",
        '"I must approve the dispatch manifest." The supervisor reported.',
        '"I must approve the dispatch manifest." The supervisor reported a delay.',
        'The supervisor reported a delay. "I must approve the dispatch manifest."',
        '"I must approve the dispatch manifest."\nThe supervisor reported.',
        'The supervisor reported inventory: "I must approve the dispatch manifest."',
        '"I must approve the dispatch manifest," the supervisor reported inventory.',
        'The supervisor discussed: "I must approve the dispatch manifest."',
        'The supervisor reported: "You must approve the dispatch manifest."',
        'The supervisor reported: "I can approve the dispatch manifest."',
        'The supervisor reported: "I do not need to approve the dispatch manifest."',
        'The supervisor reported: "I must approve the dispatch manifest.',
    ),
)
def test_reported_obligation_matrix_preserves_direct_and_unrelated_negative_controls(
    text: str,
) -> None:
    assert third_party_reported_obligation_spans(text) == ()


def test_reported_obligation_policy_keeps_long_input_sentence_local() -> None:
    unrelated = "A warehouse status sentence. " * 2_000
    direct = '"I must approve the dispatch manifest."'
    reported = 'The supervisor reported: "I must approve the loading checklist."'
    text = unrelated + direct + " " + unrelated + reported

    spans = third_party_reported_obligation_spans(text)

    assert len(spans) == 1
    assert text[slice(*spans[0])] == "I must approve the loading checklist."


@pytest.mark.parametrize(
    "text",
    (
        (
            'The draft includes "I must approve the dispatch manifest," '
            "and the supervisor reported supply."
        ),
        (
            "The draft includes I must approve the dispatch manifest, "
            "and the supervisor reported supply."
        ),
    ),
)
def test_reported_obligation_policy_does_not_treat_supply_as_an_adverb(
    text: str,
) -> None:
    assert third_party_reported_obligation_spans(text) == ()


@pytest.mark.parametrize(
    "modifier",
    ("calmly", "clearly", "explicitly", "urgently", "briefly", "quietly"),
)
@pytest.mark.parametrize("placement", ("prefix", "suffix"))
def test_reported_obligation_policy_accepts_bounded_reporting_modifiers(
    modifier: str,
    placement: str,
) -> None:
    if placement == "prefix":
        text = f'The supervisor reported {modifier}: "I must approve the dispatch manifest."'
    else:
        text = f'"I must approve the dispatch manifest," the supervisor reported {modifier}.'

    assert third_party_reported_obligation_spans(text)


@pytest.mark.parametrize(
    "modifier",
    ("supply", "family", "assembly", "friendly", "costly", "monthly"),
)
def test_reported_obligation_policy_rejects_false_reporting_modifiers(
    modifier: str,
) -> None:
    text = f'"I must approve the dispatch manifest," the supervisor reported {modifier}.'

    assert third_party_reported_obligation_spans(text) == ()
