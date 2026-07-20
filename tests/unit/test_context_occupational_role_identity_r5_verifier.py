from __future__ import annotations

import pytest
from infinity_context_core.application.context_occupational_role_identity import (
    _MAX_TITLE_CHARS,
    _MAX_TITLE_TOKENS,
    _self_occupational_role_spans,
    _tokenize,
    is_self_occupational_role_label,
)
from infinity_context_core.application.context_query_intent_extraction import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_query_intent_matching import (
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.domain.entities import MemoryAnchorKind


def _role_spans(text: str) -> tuple[str, ...]:
    return tuple(text[start:end] for start, end in _self_occupational_role_spans(text))


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        pytest.param(
            "I work as an Engineering Manager and Dana O'Neil handles recruiting.",
            ("Engineering Manager",),
            id="straight-apostrophe-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana O’Neil handles recruiting.",
            ("Engineering Manager",),
            id="curly-apostrophe-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee, PhD, handles recruiting.",
            ("Engineering Manager",),
            id="comma-credential-appositive",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee (PhD) handles recruiting.",
            ("Engineering Manager",),
            id="parenthesized-credential-appositive",
        ),
        pytest.param(
            "I work as a Director (Children's Services).",
            ("Director (Children's Services)",),
            id="straight-possessive-role-title",
        ),
        pytest.param(
            "I work as a Director (Children’s Services).",
            ("Director (Children’s Services)",),
            id="curly-possessive-role-title",
        ),
    ),
)
def test_r5_verifier_six_prior_failures_have_exact_role_spans(
    text: str,
    expected: tuple[str, ...],
) -> None:
    assert _role_spans(text) == expected


@pytest.mark.parametrize(
    ("text", "person_query", "expected_keys"),
    (
        pytest.param(
            "I work as an Engineering Manager and Dana O'Neil handles recruiting.",
            "What does Dana handle?",
            {"dana", "neil"},
            id="straight-apostrophe",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana O’Neil handles recruiting.",
            "What does Dana handle?",
            {"dana", "neil"},
            id="curly-apostrophe",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee, PhD, handles recruiting.",
            "What does Dana Lee handle?",
            {"dana lee"},
            id="comma-credential",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee (PhD) handles recruiting.",
            "What does Dana Lee handle?",
            {"dana lee"},
            id="parenthesized-credential",
        ),
    ),
)
def test_r5_verifier_following_people_survive_both_identity_call_sites(
    text: str,
    person_query: str,
    expected_keys: set[str],
) -> None:
    extracted = build_query_anchor_intent(text)
    matching = build_query_anchor_intent(person_query)
    other = build_query_anchor_intent("What does Morgan handle?")

    assert extracted.keys_for_kind(MemoryAnchorKind.PERSON) == expected_keys
    assert query_anchor_intent_text_conflicts(matching, text) is False
    assert query_anchor_intent_text_conflicts(other, text) is True


@pytest.mark.parametrize("apostrophe", ("'", "’"))
def test_r5_verifier_possessive_role_title_is_not_a_query_person(
    apostrophe: str,
) -> None:
    query = (
        "How many reports do I have in my role as "
        f"Director (Children{apostrophe}s Services)?"
    )

    assert build_query_anchor_intent(query).keys_for_kind(
        MemoryAnchorKind.PERSON
    ) == frozenset()


@pytest.mark.parametrize("apostrophe", ("'", "’"))
def test_r5_verifier_possessive_role_title_does_not_conflict_with_state_evidence(
    apostrophe: str,
) -> None:
    query = (
        "How many reports do I have in my role as "
        f"Director (Children{apostrophe}s Services)?"
    )
    intent = build_query_anchor_intent(query)

    assert query_anchor_intent_text_conflicts(
        intent,
        "Taylor: I now lead five engineers.",
    ) is False


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        pytest.param(
            "I WORK AS AN Engineering Manager; Dana handles recruiting!",
            ("Engineering Manager",),
            id="mixed-case-marker-and-punctuation",
        ),
        pytest.param(
            "I work as an Engineering Manager and DaNa handles recruiting.",
            ("Engineering Manager",),
            id="mixed-case-person",
        ),
        pytest.param(
            "I work as a VP, R&D: Dana O'Neil handles recruiting.",
            ("VP, R&D",),
            id="comma-title-colon-boundary",
        ),
        pytest.param(
            "I work as a Director (Children’s Services), and Dana handles recruiting.",
            ("Director (Children’s Services)",),
            id="possessive-title-comma-boundary",
        ),
        pytest.param(
            "I am a Manager and DANA works.",
            ("Manager",),
            id="uppercase-person-before-predicate",
        ),
        pytest.param(
            "I am a Manager and Dana Lee, PhD, Morgan works.",
            ("Manager",),
            id="credential-appositive-before-second-candidate",
        ),
    ),
)
def test_r5_verifier_punctuation_case_and_multiple_candidate_boundaries(
    text: str,
    expected: tuple[str, ...],
) -> None:
    assert _role_spans(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        pytest.param("", (), id="empty"),
        pytest.param(
            'I work as a "Manager and Dana works.',
            (),
            id="unclosed-role-quote",
        ),
        pytest.param(
            "I am a Manager and Dana (PhD works.",
            ("Manager",),
            id="unclosed-credential-parenthesis",
        ),
    ),
)
def test_r5_verifier_malformed_input_does_not_swallow_people(
    text: str,
    expected: tuple[str, ...],
) -> None:
    assert _role_spans(text) == expected


def test_r5_verifier_blank_labels_and_mixed_occurrences_are_not_exempted() -> None:
    text = (
        "I work as an Engineering Manager. "
        "Engineering Manager Dana handles recruiting."
    )

    assert is_self_occupational_role_label(label="", text=text) is False
    assert is_self_occupational_role_label(label="engineering manager", text=text) is False
    assert is_self_occupational_role_label(label="DaNa", text=text) is False


def test_r5_verifier_candidate_scans_obey_character_and_token_caps() -> None:
    beyond_candidate_window = "I work as a " + (" " * (_MAX_TITLE_CHARS + 1)) + "Manager."
    tokens = _tokenize("A " * (_MAX_TITLE_TOKENS + 20), 0, (_MAX_TITLE_TOKENS + 20) * 2)

    assert _role_spans(beyond_candidate_window) == ()
    assert len(tokens) == _MAX_TITLE_TOKENS
