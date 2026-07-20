from __future__ import annotations

import pytest
from infinity_context_core.application.context_occupational_role_identity import (
    is_self_occupational_role_label,
)
from infinity_context_core.application.context_query_intent_extraction import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_query_intent_matching import (
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.domain.entities import MemoryAnchorKind


@pytest.mark.parametrize(
    ("text", "person"),
    (
        ("I work as an Engineering Manager. Dana handles recruiting.", "Dana"),
        ("I work as an Engineering Manager? Morgan handles recruiting.", "Morgan"),
        ("I work as an Engineering Manager! Dana handles recruiting.", "Dana"),
        ("I work as an Engineering Manager\nMorgan handles recruiting.", "Morgan"),
        ("I work as an Engineering Manager\n\nDana handles recruiting.", "Dana"),
        ("I work as an Engineering Manager; Morgan handles recruiting.", "Morgan"),
        ("I work as an Engineering Manager, and Dana handles recruiting.", "Dana"),
        ("I work as an Engineering Manager and Morgan handles recruiting.", "Morgan"),
    ),
)
def test_self_role_span_stops_before_following_person_across_boundaries(
    text: str,
    person: str,
) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    assert is_self_occupational_role_label(label=person, text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {
        person.casefold()
    }


@pytest.mark.parametrize(
    "text",
    (
        "My role is Engineering Manager. Dana handles recruiting.",
        "I work as an Engineering Manager. Dana handles recruiting.",
        "I worked as an Engineering Manager. Dana handles recruiting.",
        "I served as an Engineering Manager. Dana handles recruiting.",
        "Engineering Manager was my previous role. Dana handles recruiting.",
        '"Engineering Manager" was my previous role. Dana handles recruiting.',
    ),
)
def test_role_phrase_forms_end_before_the_next_sentence(text: str) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}


@pytest.mark.parametrize(
    ("text", "title"),
    (
        (
            'I work as a "Senior Engineering Manager." Dana handles recruiting.',
            "Senior Engineering Manager",
        ),
        (
            "I work as a Sr. Engineering Manager. Dana handles recruiting.",
            "Sr. Engineering Manager",
        ),
        (
            "I work as a U.S. Engineering Manager. Dana handles recruiting.",
            "U.S. Engineering Manager",
        ),
        ("I work as a VP of R&D. Dana handles recruiting.", "VP of R&D"),
        ("I work as a CTO. Dana handles recruiting.", "CTO"),
    ),
)
def test_title_punctuation_abbreviations_and_acronyms_preserve_following_person(
    text: str,
    title: str,
) -> None:
    assert is_self_occupational_role_label(label=title, text=text) is True
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}


@pytest.mark.parametrize(
    "text",
    (
        "Engineering Manager Dana handles recruiting.",
        "Dana, Engineering Manager, handles recruiting.",
        "Dana is an Engineering Manager.",
        "I watched as Engineering Manager Dana presented the roadmap.",
        "I used Engineering Manager as a search term. Dana agreed.",
        "I described Engineering Manager as an occupation. Dana agreed.",
        "I work as Dana's Engineering Manager.",
        "I work as Dana’s Engineering Manager.",
    ),
)
def test_non_self_role_wording_preserves_titles_and_named_people(text: str) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is False
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {
        "dana",
        "engineering manager",
    }


def test_third_person_served_as_preserves_both_people() -> None:
    text = "Dana served as Engineering Manager. Morgan handled recruiting."

    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is False
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert is_self_occupational_role_label(label="Morgan", text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {
        "dana",
        "engineering manager",
        "morgan",
    }


@pytest.mark.parametrize(
    "role_sentence",
    (
        "I work as an Engineering Manager.",
        "My role is Engineering Manager.",
        "I served as an Engineering Manager.",
        "Engineering Manager was my previous role.",
    ),
)
def test_period_separated_people_drive_candidate_identity_conflicts(
    role_sentence: str,
) -> None:
    dana_intent = build_query_anchor_intent("What does Dana handle?")
    morgan_intent = build_query_anchor_intent("What does Morgan handle?")
    dana_text = f"{role_sentence} Dana handles recruiting."
    morgan_text = f"{role_sentence} Morgan handles recruiting."

    assert query_anchor_intent_text_conflicts(dana_intent, dana_text) is False
    assert query_anchor_intent_text_conflicts(dana_intent, morgan_text) is True
    assert query_anchor_intent_text_conflicts(morgan_intent, morgan_text) is False
    assert query_anchor_intent_text_conflicts(morgan_intent, dana_text) is True


@pytest.mark.parametrize(
    ("text", "people"),
    (
        (
            "I work as an Engineering Manager and Dana and Morgan handle recruiting.",
            ("Dana", "Morgan"),
        ),
        (
            "I work as an Engineering Manager and Dana, Morgan, and Lee handle recruiting.",
            ("Dana", "Morgan", "Lee"),
        ),
        (
            "I work as an Engineering Manager & Dana & Morgan handle recruiting.",
            ("Dana", "Morgan"),
        ),
        (
            "I work as an Engineering Manager and Dr Morgan handles recruiting.",
            ("Dr Morgan", "Morgan"),
        ),
        (
            "I work as an Engineering Manager, and Dr. Morgan and Prof. Lee handle recruiting.",
            ("Dr. Morgan", "Morgan", "Prof. Lee", "Lee"),
        ),
        (
            "I work as an Engineering Manager and Alex C. handles recruiting.",
            ("Alex C.", "Alex"),
        ),
        (
            "I work as an Engineering Manager and Director Dana handles recruiting.",
            ("Director Dana", "Dana"),
        ),
        (
            "I work as an Engineering Manager and Dana, the CTO, handles recruiting.",
            ("Dana", "CTO"),
        ),
    ),
)
def test_title_conjunction_stops_before_a_syntactic_person_clause(
    text: str,
    people: tuple[str, ...],
) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    for person in people:
        assert is_self_occupational_role_label(label=person, text=text) is False


def test_verifier_conjunction_regression_preserves_both_people_in_both_paths() -> None:
    text = "I work as an Engineering Manager and Dana and Morgan handle recruiting."
    intent = build_query_anchor_intent(text)
    dana_intent = build_query_anchor_intent("What does Dana handle?")
    lee_intent = build_query_anchor_intent("What does Lee handle?")

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"dana", "morgan"}
    assert query_anchor_intent_text_conflicts(dana_intent, text) is False
    assert query_anchor_intent_text_conflicts(lee_intent, text) is True


def test_honorific_person_after_role_survives_query_intent_extraction() -> None:
    text = "I work as an Engineering Manager and Dr Morgan handles recruiting."

    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {"morgan"}


@pytest.mark.parametrize(
    ("text", "title"),
    (
        ("I work as a VP, R&D.", "VP, R&D"),
        ("I work as a Co-Founder & CTO.", "Co-Founder & CTO"),
        ("I work as a Co-Founder and CTO.", "Co-Founder and CTO"),
        (
            "I work as a Research and Development Manager.",
            "Research and Development Manager",
        ),
        (
            "I work as a Head of Research and Development.",
            "Head of Research and Development",
        ),
        (
            "I work as a Chief Product & Technology Officer.",
            "Chief Product & Technology Officer",
        ),
        (
            "I work as a Research, Development and Engineering Manager.",
            "Research, Development and Engineering Manager",
        ),
        ("I work as an Engineering Manager, Platform.", "Engineering Manager, Platform"),
        ("I work as a VP / CTO.", "VP / CTO"),
    ),
)
def test_title_connectors_continue_only_when_the_grammar_is_title_like(
    text: str,
    title: str,
) -> None:
    assert is_self_occupational_role_label(label=title, text=text) is True
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()


@pytest.mark.parametrize(
    ("text", "title", "qualifiers"),
    (
        (
            "I work as an Engineering Manager (Platform). Dana handles recruiting.",
            "Engineering Manager (Platform)",
            ("Platform",),
        ),
        (
            "I work as an Engineering Manager (Platform (R&D)). Dana handles recruiting.",
            "Engineering Manager (Platform (R&D))",
            ("Platform", "R&D"),
        ),
        (
            'I work as a "VP, R&D (Platform & AI)". Dana handles recruiting.',
            "VP, R&D (Platform & AI)",
            ("Platform", "AI"),
        ),
        (
            "I work as a “Engineering Manager (‘Platform & Data’)”. Dana handles recruiting.",
            "Engineering Manager (‘Platform & Data’)",
            ("Platform", "Data"),
        ),
        (
            '"Engineering Manager (Platform)" was my previous role. Dana agreed.',
            "Engineering Manager (Platform)",
            ("Platform",),
        ),
        (
            "My previous Engineering Manager (Platform) role changed. Dana agreed.",
            "Engineering Manager (Platform)",
            ("Platform",),
        ),
    ),
)
def test_balanced_quoted_and_parenthesized_title_qualifiers_are_in_the_role_span(
    text: str,
    title: str,
    qualifiers: tuple[str, ...],
) -> None:
    assert is_self_occupational_role_label(label=title, text=text) is True
    for qualifier in qualifiers:
        assert is_self_occupational_role_label(label=qualifier, text=text) is True
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}


@pytest.mark.parametrize(
    "text",
    (
        "I work as an Engineering Manager (Dana handles recruiting). Morgan agreed.",
        "I work as an Engineering Manager (Dr Morgan handles recruiting). Dana agreed.",
    ),
)
def test_parentheses_do_not_turn_a_following_person_clause_into_a_title_qualifier(
    text: str,
) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    assert is_self_occupational_role_label(label="Morgan", text=text) is False
    assert is_self_occupational_role_label(label="Dana", text=text) is False


@pytest.mark.parametrize(
    ("text", "person"),
    (
        ("I work as an Engineering Manager (Dana). Morgan agreed.", "Dana"),
        ("I work as an Engineering Manager (Dana Morgan). Lee agreed.", "Dana Morgan"),
        ("I work as an Engineering Manager (Dr Morgan). Dana agreed.", "Morgan"),
    ),
)
def test_bare_parenthetical_person_phrases_are_not_title_qualifiers(
    text: str,
    person: str,
) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    assert is_self_occupational_role_label(label=person, text=text) is False


@pytest.mark.parametrize(
    ("text", "title"),
    (
        ("I work as a Sr. Engineering Manager. Dana agreed.", "Sr. Engineering Manager"),
        ("I work as a U.S. Engineering Manager. Dana agreed.", "U.S. Engineering Manager"),
        ("I work as an R&D VP. Dana agreed.", "R&D VP"),
        ("I work as a C++ Engineering Lead. Dana agreed.", "C++ Engineering Lead"),
    ),
)
def test_abbreviations_and_acronyms_do_not_create_false_sentence_boundaries(
    text: str,
    title: str,
) -> None:
    assert is_self_occupational_role_label(label=title, text=text) is True
    assert is_self_occupational_role_label(label="Dana", text=text) is False


@pytest.mark.parametrize(
    "text",
    (
        "I work as an Engineering Manager, 2026-07-19; Dana owns the data.",
        "I work as an Engineering Manager: headcount=12; Dana owns the data.",
        "I work as an Engineering Manager — Q3 metrics follow. Dana owns the data.",
        "I work as an Engineering Manager, $125k band. Dana owns the data.",
    ),
)
def test_data_punctuation_terminates_the_title_without_swallowing_people(text: str) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is True
    assert is_self_occupational_role_label(label="Dana", text=text) is False


@pytest.mark.parametrize(
    "text",
    (
        "Engineering Manager Dana handles recruiting.",
        "Dana, Engineering Manager, handles recruiting.",
        "Dana is the Engineering Manager who handles recruiting.",
        "Director Dana said Morgan is an Engineering Manager.",
        "I watched as Engineering Manager Dana presented the roadmap.",
        "I treated Engineering Manager as ordinary data; Dana agreed.",
        "I work as Dana's Engineering Manager.",
        "I work as Dana’s Engineering Manager.",
    ),
)
def test_names_titles_possessives_and_ordinary_as_stay_outside_self_role_spans(
    text: str,
) -> None:
    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is False
    assert is_self_occupational_role_label(label="Dana", text=text) is False


def test_same_title_label_in_self_role_and_third_person_context_is_not_globally_exempted() -> None:
    text = (
        "I work as an Engineering Manager. Engineering Manager Dana handles recruiting for Morgan."
    )

    assert is_self_occupational_role_label(label="Engineering Manager", text=text) is False
    assert is_self_occupational_role_label(label="Dana", text=text) is False
    assert is_self_occupational_role_label(label="Morgan", text=text) is False
