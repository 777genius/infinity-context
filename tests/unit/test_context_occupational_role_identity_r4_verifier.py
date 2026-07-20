from __future__ import annotations

import pytest
from infinity_context_core.application.context_occupational_role_identity import (
    _self_occupational_role_spans,
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
    ("text", "expected_spans"),
    (
        pytest.param(
            "I work as an Engineering Manager and Dana J. handles recruiting.",
            ("Engineering Manager",),
            id="initial-following-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dr Morgan handles recruiting.",
            ("Engineering Manager",),
            id="honorific-without-full-stop",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dr. Morgan handles recruiting.",
            ("Engineering Manager",),
            id="honorific-with-full-stop",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana, Engineering Director, handles recruiting.",
            ("Engineering Manager",),
            id="role-appositive-after-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana, the recruiter, handles recruiting.",
            ("Engineering Manager",),
            id="lowercase-appositive-after-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana O'Neil handles recruiting.",
            ("Engineering Manager",),
            id="apostrophe-in-following-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee, PhD, handles recruiting.",
            ("Engineering Manager",),
            id="credential-appositive-after-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee (PhD) handles recruiting.",
            ("Engineering Manager",),
            id="parenthesized-appositive-after-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana and Morgan handle recruiting.",
            ("Engineering Manager",),
            id="conjunction-joins-people",
        ),
        pytest.param(
            "I work as an Engineering Manager and I serve as a Product Director; "
            "Dana handles recruiting.",
            ("Engineering Manager", "Product Director"),
            id="multiple-role-clauses",
        ),
        pytest.param(
            "I work as an Engineering Manager who mentors Dana.",
            ("Engineering Manager",),
            id="trailing-relative-verb",
        ),
        pytest.param(
            "I work as an Engineering Manager and lead Dana's recruiting work.",
            ("Engineering Manager",),
            id="trailing-conjoined-verb",
        ),
        pytest.param(
            "I work as an Engineering Manager for fintech and Dana handles recruiting.",
            ("Engineering Manager",),
            id="unknown-lowercase-qualifier",
        ),
        pytest.param(
            "I work as an Engineering Manager (platform) and Dana handles recruiting.",
            ("Engineering Manager",),
            id="unknown-lowercase-parenthetical",
        ),
        pytest.param(
            "I work as an Engineering Manager\r\nDana handles recruiting.",
            ("Engineering Manager",),
            id="crlf-boundary",
        ),
        pytest.param(
            "I work as a Sr. Engineering Manager. Dana handles recruiting.",
            ("Sr. Engineering Manager",),
            id="abbreviation-before-full-stop",
        ),
        pytest.param(
            "I work as an U.S. Engineering Manager. Dana handles recruiting.",
            ("U.S. Engineering Manager",),
            id="multi-full-stop-abbreviation",
        ),
        pytest.param(
            "I work as an Engineering Manager; Dana handles recruiting.",
            ("Engineering Manager",),
            id="semicolon-boundary",
        ),
        pytest.param(
            "I work as an Engineering Manager: Dana handles recruiting.",
            ("Engineering Manager",),
            id="colon-boundary",
        ),
        pytest.param(
            "I work as an Engineering Manager and Мария handles recruiting.",
            ("Engineering Manager",),
            id="cyrillic-following-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Élodie handles recruiting.",
            ("Engineering Manager",),
            id="accented-latin-following-person",
        ),
        pytest.param(
            "I work as an “Engineering Manager (‘Platform & Data’)” and Dana handles recruiting.",
            ("Engineering Manager (‘Platform & Data’)”",),
            id="nested-and-closing-curly-quotes",
        ),
        pytest.param(
            "I work as an Engineering Manager” and Dana handles recruiting.",
            ("Engineering Manager",),
            id="unmatched-closing-quote",
        ),
        pytest.param(
            "I work as a VP, R&D.",
            ("VP, R&D",),
            id="valid-comma-and-ampersand-title",
        ),
        pytest.param(
            "I work as an Engineering Manager (Platform).",
            ("Engineering Manager (Platform)",),
            id="valid-parenthesized-title",
        ),
        pytest.param(
            "I work as a Co-Founder & CTO.",
            ("Co-Founder & CTO",),
            id="valid-conjoined-title",
        ),
        pytest.param(
            "I work as a Director (Children's Services).",
            ("Director (Children's Services)",),
            id="apostrophe-in-valid-parenthesized-title",
        ),
    ),
)
def test_r4_verifier_exact_bounded_role_span_matrix(
    text: str,
    expected_spans: tuple[str, ...],
) -> None:
    actual_spans = tuple(text[start:end] for start, end in _self_occupational_role_spans(text))

    assert actual_spans == expected_spans


@pytest.mark.parametrize(
    ("text", "person_label", "required_person_keys"),
    (
        pytest.param(
            "I work as an Engineering Manager and Dana and Morgan handle recruiting.",
            "Dana",
            {"dana", "morgan"},
            id="r3-conjoined-people",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dr Morgan handles recruiting.",
            "Morgan",
            {"morgan"},
            id="r3-honorific-person",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana O'Neil handles recruiting.",
            "Dana",
            {"dana"},
            id="apostrophe-person-call-sites",
        ),
        pytest.param(
            "I work as an Engineering Manager and Dana Lee, PhD, handles recruiting.",
            "Dana",
            {"dana lee"},
            id="credential-appositive-call-sites",
        ),
        pytest.param(
            "I work as an Engineering Manager and Мария handles recruiting.",
            "Мария",
            {"mariya"},
            id="non-ascii-person-call-sites",
        ),
    ),
)
def test_r4_verifier_following_people_survive_both_call_sites(
    text: str,
    person_label: str,
    required_person_keys: set[str],
) -> None:
    intent = build_query_anchor_intent(text)
    person_intent = build_query_anchor_intent(f"What does {person_label} handle?")

    assert is_self_occupational_role_label(label=person_label, text=text) is False
    assert required_person_keys.issubset(intent.keys_for_kind(MemoryAnchorKind.PERSON))
    assert query_anchor_intent_text_conflicts(person_intent, text) is False


@pytest.mark.parametrize(
    "title",
    (
        "VP, R&D",
        "Engineering Manager (Platform)",
        "Co-Founder & CTO",
    ),
)
def test_r4_verifier_required_valid_continuations_are_not_truncated(title: str) -> None:
    text = f"I work as a {title}."

    assert is_self_occupational_role_label(label=title, text=text) is True
    assert build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()


def test_r4_verifier_031748ae_role_update_evidence_remains_admissible() -> None:
    query = (
        "How many engineers do I lead when I just started my new role as "
        "Senior Software Engineer? How many engineers do I lead now?"
    )
    before = "Taylor: I had just started the role and led a team of 4 engineers."
    now = "Taylor: I now lead a team of five engineers."
    intent = build_query_anchor_intent(query)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert query_anchor_intent_text_conflicts(intent, before) is False
    assert query_anchor_intent_text_conflicts(intent, now) is False
