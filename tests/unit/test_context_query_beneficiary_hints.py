from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    match_query_anchor_intent,
    query_anchor_intent_conflicts,
    query_anchor_intent_text_conflicts,
    query_anchor_lookup_keys,
)
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)


def _person_anchor(label: str) -> MemoryAnchor:
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(f"anchor_{label.casefold()}"),
        space_id=SpaceId("space_context_query_beneficiary"),
        memory_scope_id=MemoryScopeId("memory_scope_context_query_beneficiary"),
        kind=MemoryAnchorKind.PERSON,
        normalized_key=label.casefold(),
        label=label,
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(MemoryAnchorKind.PERSON, label),
        now=datetime(2026, 8, 4, tzinfo=UTC),
    )


def test_beneficiary_only_person_hints_are_support_only() -> None:
    cases = (
        ("What did I prepare for Dana?", "dana"),
        ("What did I prepare for Atlas?", "atlas"),
        ("What did I buy for Customers?", "customers"),
    )

    for query, expected_key in cases:
        intent = build_query_anchor_intent(query)

        assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {expected_key}
        assert intent.conflict_keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
        assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == frozenset()
        assert query_anchor_intent_conflicts(intent, _person_anchor("Morgan")) is False
        assert query_anchor_intent_text_conflicts(
            intent,
            "Morgan received the item.",
        ) is False


def test_beneficiary_hint_still_supports_dana_lookup_and_match() -> None:
    intent = build_query_anchor_intent("What did I prepare for Dana?")

    assert match_query_anchor_intent(intent, _person_anchor("Dana")) is not None
    assert any(
        key.kind == MemoryAnchorKind.PERSON and key.normalized_key == "dana"
        for key in query_anchor_lookup_keys(intent)
    )


def test_explicit_person_hint_remains_conflict_eligible() -> None:
    intent = build_query_anchor_intent("What did Dana present?")

    assert intent.conflict_keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}
    assert query_anchor_intent_conflicts(intent, _person_anchor("Morgan")) is True


def test_non_beneficiary_for_phrases_remain_non_person_hints() -> None:
    bare_label = build_query_anchor_intent("What changed for Atlas?")
    generic_group = build_query_anchor_intent("What does this mean for Customers?")
    explicit_project = build_query_anchor_intent("What changed for Project Atlas?")

    assert bare_label.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert generic_group.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert explicit_project.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert explicit_project.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
