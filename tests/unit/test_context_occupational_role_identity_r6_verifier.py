from __future__ import annotations

import pytest
from infinity_context_core.application.context_occupational_role_identity import (
    _MAX_TITLE_CHARS,
    _MAX_TITLE_TOKENS,
    _SELF_ROLE_TITLE_AFTER_RE,
    _candidate_start,
    _self_occupational_role_spans,
    _tokenize,
    is_non_person_identity_label,
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


def _person_keys(text: str) -> frozenset[str]:
    return build_query_anchor_intent(text).keys_for_kind(MemoryAnchorKind.PERSON)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        pytest.param(
            "I am a Security Director and DANA LEE, MD, handles audits.",
            ("Security Director",),
            id="uppercase-person-with-comma-credential",
        ),
        pytest.param(
            "I am a Security Director and DaNa McNeil [PhD] handles audits.",
            ("Security Director",),
            id="mixed-case-person-with-bracketed-credential",
        ),
        pytest.param(
            "I am a Manager and DaNa Lee, PhD, Morgan Kim and Riley Chen work nearby.",
            ("Manager",),
            id="three-candidates-after-credential",
        ),
        pytest.param(
            "I am a Manager, and DaNa Lee (PhD), Morgan Kim works nearby.",
            ("Manager",),
            id="comma-and-before-two-candidates",
        ),
        pytest.param(
            "I am a Manager and DaNa Lee [PhD, Morgan Kim works nearby.",
            ("Manager",),
            id="unclosed-square-credential-before-second-candidate",
        ),
        pytest.param(
            "I am a Manager and DaNa Lee (PhD] and Morgan Kim work nearby.",
            ("Manager",),
            id="mismatched-credential-group-before-second-candidate",
        ),
        pytest.param(
            "I am a Manager and DaNa Lee ((PhD)) and Morgan Kim work nearby.",
            ("Manager",),
            id="nested-credential-before-second-candidate",
        ),
        pytest.param(
            "I am a Manager and DaNa Lee, Esq., handles audits.",
            ("Manager",),
            id="credential-with-nearby-full-stop",
        ),
        pytest.param(
            "I serve as a Product Director — DaNa Lee, DPhil, handles research.",
            ("Product Director",),
            id="spaced-em-dash-before-person",
        ),
        pytest.param(
            "I work as a Principal Engineer?! DaNa Lee handles support.",
            ("Principal Engineer",),
            id="adjacent-question-exclamation-boundary",
        ),
    ),
)
def test_r6_verifier_people_and_credentials_never_extend_role_spans(
    text: str,
    expected: tuple[str, ...],
) -> None:
    assert _role_spans(text) == expected


@pytest.mark.parametrize("apostrophe", ("'", "’"))
def test_r6_verifier_nested_possessive_titles_are_complete_without_person_leakage(
    apostrophe: str,
) -> None:
    title = f"Director (Children{apostrophe}s Services (R&D))"
    text = f"My current role: {title}; DaNa handles intake."

    assert _role_spans(text) == (title,)
    assert is_self_occupational_role_label(label=title, text=text) is True
    assert _person_keys(text) == frozenset({"dana"})


@pytest.mark.parametrize(
    ("text", "label", "expected"),
    (
        pytest.param(
            "I work as a Platform Director.",
            "Platform Director",
            True,
            id="self-role-is-non-person",
        ),
        pytest.param(
            "DaNa Lee, PhD, handles recruiting.",
            "PhD",
            True,
            id="comma-credential-is-non-person",
        ),
        pytest.param(
            "DaNa Lee [DPhil] handles research.",
            "DPhil",
            True,
            id="bracketed-credential-is-non-person",
        ),
        pytest.param(
            "DaNa Lee, Esq., handles contracts.",
            "Esq",
            True,
            id="punctuated-credential-is-non-person",
        ),
        pytest.param(
            "DaNa Lee ((PhD)) handles research.",
            "PhD",
            True,
            id="nested-credential-is-non-person",
        ),
        pytest.param(
            "DaNa Lee {PhD handles research.",
            "PhD",
            True,
            id="unclosed-credential-is-non-person",
        ),
        pytest.param(
            "DaNa Lee handles recruiting.",
            "DaNa Lee",
            False,
            id="person-remains-person",
        ),
        pytest.param(
            "I work as a Platform Director. Platform Director Kim handles recruiting.",
            "Platform Director",
            False,
            id="mixed-role-and-person-occurrences-remain-person-capable",
        ),
    ),
)
def test_r6_verifier_person_hint_classification(
    text: str,
    label: str,
    expected: bool,
) -> None:
    assert is_non_person_identity_label(label=label, text=text) is expected


_CREDENTIAL_EVIDENCE = (
    pytest.param(
        "DaNa Lee, PhD, handles recruiting.",
        "PhD",
        id="comma-phd",
    ),
    pytest.param(
        "DaNa Lee, Esq., handles contracts.",
        "Esq",
        id="punctuated-esquire",
    ),
    pytest.param(
        "DaNa Lee ((PhD)) handles research.",
        "PhD",
        id="nested-phd",
    ),
    pytest.param(
        "DaNa Lee (PhD handles research.",
        "PhD",
        id="unclosed-phd",
    ),
)


@pytest.mark.parametrize(("evidence", "credential"), _CREDENTIAL_EVIDENCE)
def test_r6_verifier_credentials_are_noise_at_query_intent_call_site(
    evidence: str,
    credential: str,
) -> None:
    person_keys = _person_keys(evidence)

    assert credential.casefold() not in person_keys
    assert person_keys == frozenset({"dana lee"})


@pytest.mark.parametrize(("evidence", "credential"), _CREDENTIAL_EVIDENCE)
def test_r6_verifier_credentials_are_noise_at_conflict_call_site(
    evidence: str,
    credential: str,
) -> None:
    matching_person = build_query_anchor_intent("What does DaNa Lee handle?")
    unrelated_person = build_query_anchor_intent("What does Morgan Kim handle?")
    credential_as_person = build_query_anchor_intent(f"What does {credential} handle?")

    assert query_anchor_intent_text_conflicts(matching_person, evidence) is False
    assert query_anchor_intent_text_conflicts(unrelated_person, evidence) is True
    assert query_anchor_intent_text_conflicts(credential_as_person, evidence) is True


def test_r6_verifier_multiple_people_survive_query_and_conflict_call_sites() -> None:
    evidence = (
        "I am a Manager and DaNa Lee, PhD, Morgan Kim and Riley Chen work nearby."
    )
    expected_people = frozenset({"dana lee", "morgan kim", "riley chen"})

    assert _role_spans(evidence) == ("Manager",)
    assert _person_keys(evidence) == expected_people
    for person in ("DaNa Lee", "Morgan Kim", "Riley Chen"):
        intent = build_query_anchor_intent(f"What does {person} handle?")
        assert query_anchor_intent_text_conflicts(intent, evidence) is False
    unrelated = build_query_anchor_intent("What does Taylor Jones handle?")
    assert query_anchor_intent_text_conflicts(unrelated, evidence) is True


def test_r6_verifier_unclosed_group_does_not_leak_credential_or_swallow_people() -> None:
    evidence = "I am a Manager and DaNa Lee [PhD, Morgan Kim works nearby."

    assert _role_spans(evidence) == ("Manager",)
    assert _person_keys(evidence) == frozenset({"dana lee", "morgan kim"})


def test_r6_verifier_long_inline_whitespace_keeps_a_single_bounded_window() -> None:
    within_window = "I work as an" + (" " * 64) + "Engineering Manager; DaNa works."
    beyond_window = (
        "I work as an" + (" " * (_MAX_TITLE_CHARS + 1)) + "Engineering Manager."
    )

    assert _role_spans(within_window) == ("Engineering Manager",)
    assert _person_keys(within_window) == frozenset({"dana"})
    assert _role_spans(beyond_window) == ()


class _ReadCountingText(str):
    reads: int

    def __new__(cls, value: str) -> _ReadCountingText:
        instance = super().__new__(cls, value)
        instance.reads = 0
        return instance

    def __getitem__(self, key: int | slice) -> str:
        self.reads += 1
        return super().__getitem__(key)


def test_r6_verifier_candidate_and_token_scans_have_hard_caps() -> None:
    raw = "I work as a" + (" " * 50_000)
    match = _SELF_ROLE_TITLE_AFTER_RE.search(raw)
    assert match is not None
    counted = _ReadCountingText(raw)

    assert _candidate_start(counted, match) is None
    assert counted.reads <= _MAX_TITLE_CHARS + 1

    tokens = _tokenize("Manager " * 50_000, 0, 400_000)
    assert len(tokens) == _MAX_TITLE_TOKENS


def test_r6_verifier_role_only_query_remains_admissible_at_conflict_call_site() -> None:
    query = (
        "How many reports do I have in my role as "
        "Director (Children’s Services (R&D))?"
    )
    intent = build_query_anchor_intent(query)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert query_anchor_intent_text_conflicts(
        intent,
        "Taylor: I now lead five engineers.",
    ) is False
