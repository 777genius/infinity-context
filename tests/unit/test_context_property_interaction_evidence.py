from __future__ import annotations

from datetime import UTC, datetime

import pytest
from infinity_context_core.application.context_distinct_set_evidence import (
    project_distinct_set_evidence,
)
from infinity_context_core.application.dto import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _keyword_aggregation_chunk_items,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)

_PROPERTY_QUERY = "How many properties did I view before making an offer on a townhouse?"


@pytest.mark.parametrize(
    "event_text",
    (
        "my offer got rejected because another buyer submitted a stronger bid",
        "my offer was denied by the seller",
        "my offer was not rejected after the seller reconsidered",
    ),
)
def test_property_offer_outcomes_preserve_user_event_evidence(event_text: str) -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "source:property-event\n"
            "user: I became interested in a modern 2-bedroom condo, and "
            f"{event_text}."
        ),
    )

    assert projection.identities == ("modern 2-bedroom condo",)
    assert projection.interaction_event_count == 1
    assert "source:property-event" in projection.rendered_text
    assert event_text in projection.rendered_text


def test_explicit_offer_object_does_not_borrow_an_unrelated_property() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I bookmarked a lakeside condo, but my offer on a brick townhouse was rejected."
        ),
    )

    assert projection.identities == ("brick townhouse",)
    assert "lakeside condo" not in projection.identities


def test_implicit_offer_event_rejects_ambiguous_property_antecedents() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I compared a lakeside condo with a brick townhouse, but my offer was rejected."
        ),
    )

    assert not projection.present
    assert projection.interaction_event_count == 0


@pytest.mark.parametrize(
    "text",
    (
        "assistant: Your offer on a 2-bedroom condo was rejected.",
        "system: My offer on a 2-bedroom condo was denied.",
        "user: Taylor's offer on a 2-bedroom condo was rejected.",
        "user: My friend said my offer on a 2-bedroom condo might be rejected.",
    ),
)
def test_property_event_projection_preserves_role_subject_and_event_boundaries(
    text: str,
) -> None:
    projection = project_distinct_set_evidence(query=_PROPERTY_QUERY, text=text)

    assert not projection.present


def test_property_event_projection_rejects_temporal_mismatch() -> None:
    projection = project_distinct_set_evidence(
        query="How many properties did I view in February?",
        text=(
            "user: I became interested in a 2-bedroom condo in January, and my offer was rejected."
        ),
    )

    assert not projection.present
    assert projection.temporal_conflict


def test_negated_offer_does_not_invent_an_interaction_event() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text="user: I did not make an offer on a 2-bedroom condo.",
    )

    assert not projection.present


@pytest.mark.parametrize(
    "text",
    (
        (
            "user: I submitted an offer on a canal-side condo sight unseen, "
            "and my offer was rejected."
        ),
        ("user: I never viewed the canal-side condo, but my offer on the property was rejected."),
        ("user: I never toured the canal-side condo, but my offer was rejected."),
        ("user: I never saw the canal-side condo, but my offer was rejected."),
        (
            "user: I did not tour the canal-side condo, although my offer on "
            "the property was denied."
        ),
        (
            "user: There was no viewing of the canal-side condo before my "
            "offer on the property was declined."
        ),
        (
            "user: My offer on a canal-side condo was accepted, but I planned "
            "to view it only after the offer."
        ),
        (
            "user: The viewing of a canal-side condo was scheduled only after "
            "my offer on the property was accepted."
        ),
    ),
)
def test_offer_outcome_does_not_override_explicitly_absent_prior_viewing(
    text: str,
) -> None:
    projection = project_distinct_set_evidence(query=_PROPERTY_QUERY, text=text)

    assert not projection.present
    assert projection.interaction_event_count == 0


def test_completed_viewing_wins_over_unrelated_property_no_viewing() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I viewed a canal-side condo before my offer was rejected, while "
            "there was no viewing of a brick townhouse."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_completed_viewing_wins_over_unrelated_future_property_viewing() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I viewed a canal-side condo before my offer was rejected; "
            "I planned to tour a brick townhouse only after the offer."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_no_viewing_appointment_does_not_negate_a_completed_tour() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I toured a canal-side condo before my offer was rejected, "
            "despite having no viewing appointment."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_never_saw_rejection_idiom_does_not_negate_a_completed_viewing() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I viewed a canal-side condo before my offer was rejected; "
            "I never saw such a fast rejection."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_completed_viewing_from_another_subject_is_not_borrowed() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=("user: Taylor viewed a lake house, and my offer on a canal-side condo was rejected."),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_absent_viewing_from_another_subject_does_not_negate_my_event() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: Taylor never viewed the canal-side condo, but my offer on the "
            "property was rejected."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


@pytest.mark.parametrize(
    "text",
    (
        "My offer on a canal-side condo was rejected because I made it without viewing it.",
        "I never viewed it, but my offer on a canal-side condo was rejected.",
        "My offer on a canal-side condo was rejected before I viewed it.",
    ),
)
def test_offer_event_rejects_confirmed_no_prior_viewing_counterexamples(text: str) -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=f"user: {text}",
    )

    assert projection.identities == ()
    assert projection.interaction_event_count == 0


def test_ambiguous_pronoun_does_not_negate_multiple_event_linked_properties() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I never viewed it, but my offer on a canal-side condo was "
            "rejected and my offer on a brick townhouse was denied."
        ),
    )

    assert projection.identities == ("canal-side condo", "brick townhouse")
    assert projection.interaction_event_count == 2


def test_pronoun_viewing_negation_from_another_subject_does_not_negate_my_event() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=("user: Taylor never viewed it, but my offer on a canal-side condo was rejected."),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_explicit_prior_viewing_wins_over_later_pronoun_negation() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I viewed a canal-side condo before my offer on the property was "
            "rejected, and I never viewed it again."
        ),
    )

    assert projection.identities == ("canal-side condo",)
    assert projection.interaction_event_count == 1


def test_viewing_after_an_unrelated_offer_remains_prior_to_its_linked_offer() -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=(
            "user: I viewed a canal-side condo after my offer on a brick townhouse "
            "was rejected; my offer on the canal-side condo was accepted."
        ),
    )

    assert projection.identities == ("canal-side condo", "brick townhouse")
    assert projection.interaction_event_count == 2


@pytest.mark.parametrize(
    "text",
    (
        "I viewed a canal-side condo after my offer on the property was rejected.",
        "After my offer on a canal-side condo was rejected, I toured the canal-side condo.",
        "Before I saw a canal-side condo, my offer on the property was denied.",
    ),
)
def test_clear_temporal_inversion_is_scoped_to_the_linked_property(text: str) -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=f"user: {text}",
    )

    assert projection.identities == ()
    assert projection.interaction_event_count == 0


@pytest.mark.parametrize(
    "text",
    (
        (
            "I saw the online listing for a canal-side condo before my offer on "
            "the property was rejected, but I never viewed it."
        ),
        (
            "I bookmarked a canal-side condo before my offer on the property was "
            "rejected because I made it without viewing it."
        ),
    ),
)
def test_online_research_does_not_override_explicitly_absent_viewing(text: str) -> None:
    projection = project_distinct_set_evidence(
        query=_PROPERTY_QUERY,
        text=f"user: {text}",
    )

    assert projection.identities == ()
    assert projection.interaction_event_count == 0


def test_named_subject_offer_event_stays_with_requested_subject() -> None:
    morgan = project_distinct_set_evidence(
        query="How many properties did Morgan view before making an offer?",
        text="user: Morgan's offer on a garden condo was declined.",
    )
    taylor = project_distinct_set_evidence(
        query="How many properties did Morgan view before making an offer?",
        text="user: Taylor's offer on a garden condo was declined.",
    )

    assert morgan.identities == ("garden condo",)
    assert not taylor.present
    assert taylor.subject_conflict


def test_property_event_is_reserved_with_exact_source_identity_before_rerank() -> None:
    source_id = "neutral:property-search:episode"
    event = _chunk(
        "property-event",
        (
            "user: I became interested in a 2-bedroom condo, but my offer was "
            "rejected by the seller."
        ),
        source_id=source_id,
    )
    same_source_noise = _chunk(
        "property-paperwork",
        "user: I organized the property offer paperwork for closing.",
        source_id=source_id,
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=_query(_PROPERTY_QUERY),
        seed_chunks=(same_source_noise, event),
    )

    selected = next(item for item in items if item.item_id == event.id)
    assert "offer was rejected" in selected.text
    assert {ref.source_id for ref in selected.source_refs} == {source_id}
    assert (
        selected.diagnostics["score_signals"]["keyword_aggregation_interaction_event_support"] == 1
    )
    assert diagnostics["keyword_aggregation_distinct_member_reservations_used"] == 1


def _query(text: str) -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space-neutral"),
        memory_scope_ids=(MemoryScopeId("scope-neutral"),),
        query=text,
        max_chunks=10,
        token_budget=512,
        consistency_mode=ConsistencyMode.CANONICAL_ONLY,
    )


def _chunk(chunk_id: str, text: str, *, source_id: str) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space-neutral"),
        memory_scope_id=MemoryScopeId("scope-neutral"),
        document_id=MemoryDocumentId(f"{chunk_id}-document"),
        source_type="document",
        source_external_id=source_id,
        source_hash=f"{chunk_id}-hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=max(1, len(text.split())),
        now=now,
    )
