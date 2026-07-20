from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_core.application.context_distinct_set_evidence import (
    extract_distinct_set_request,
    project_distinct_set_evidence,
)
from infinity_context_core.application.context_distinct_set_selection import (
    prepare_distinct_set_evidence_for_rerank,
    restore_distinct_set_evidence_items,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.context_requirement_guard import (
    _apply_explicit_requirement_guard,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.distinct_set_membership import (
    DistinctSetMemberCandidate,
    DistinctSetMemberReservationPolicy,
)
from infinity_context_core.domain.entities import SourceRef


@pytest.mark.parametrize(
    ("query", "target", "actions"),
    (
        (
            "How many tanks do I currently have, including the one I set up?",
            "tank",
            {"own"},
        ),
        (
            "How many different museums or galleries did I visit in February?",
            "museum",
            {"visit"},
        ),
        (
            "How many different types of citrus fruits have I used in recipes?",
            "citrus",
            {"use"},
        ),
        (
            "How many cuisines have I learned to cook or tried out?",
            "cuisine",
            {"learn", "try"},
        ),
        (
            "How many food delivery services have I used recently?",
            "service",
            {"use"},
        ),
        (
            "How many pieces of furniture did I buy, assemble, sell, or fix?",
            "furniture",
            {"assemble", "buy", "fix", "sell"},
        ),
        ("How many weddings have I attended this year?", "wedding", {"attend"}),
        ("How many model kits have I worked on or bought?", "kit", {"buy", "work"}),
        ("How many properties did I view before making an offer?", "property", {"view"}),
    ),
)
def test_distinct_set_request_extracts_general_target_and_actions(
    query: str,
    target: str,
    actions: set[str],
) -> None:
    request = extract_distinct_set_request(query)

    assert request is not None
    assert target in request.target_terms
    assert set(request.action_terms).issuperset(actions)


def test_current_ownership_assertions_satisfy_tank_membership_without_action_overlap() -> None:
    query = "How many tanks do I currently have, including the one I set up?"

    community = project_distinct_set_evidence(
        query=query,
        text="source-a\nuser: I need plants for my community tank.",
    )
    five_gallon = project_distinct_set_evidence(
        query=query,
        text="source-b\nuser: I have a 5-gallon tank with a betta fish.",
    )
    one_gallon = project_distinct_set_evidence(
        query=query,
        text=(
            "source-c\nuser: I've also been taking care of a small 1-gallon tank "
            "that I set up for a friend's kid."
        ),
    )

    assert community.present
    assert five_gallon.present
    assert one_gallon.present
    assert community.identities == ("community tank",)
    assert five_gallon.identities == ("5-gallon tank",)
    assert one_gallon.identities == ("1-gallon tank",)
    assert len({community.member_ids[0], five_gallon.member_ids[0], one_gallon.member_ids[0]}) == 3


def test_contextual_anchor_relaxation_is_limited_to_first_person_set_requests() -> None:
    first_person = extract_distinct_set_request("How many weddings have I attended this year?")
    named_subject = extract_distinct_set_request(
        "How many weddings has Morgan attended with my friend this year?"
    )

    assert first_person is not None and first_person.subject_is_first_person
    assert named_subject is not None and not named_subject.subject_is_first_person


def test_member_identity_ignores_cocktail_context_for_same_citrus() -> None:
    query = "How many different types of citrus fruits have I used in cocktail recipes?"

    daiquiri = project_distinct_set_evidence(
        query=query,
        text=(
            "source-old\nuser: I learned a classic Daiquiri using fresh lime juice "
            "and simple syrup."
        ),
    )
    gimlet = project_distinct_set_evidence(
        query=query,
        text=(
            "source-new\nuser: I made a Cucumber Gimlet and mixed it with lime juice "
            "and simple syrup."
        ),
    )
    orange = project_distinct_set_evidence(
        query=query,
        text="source-orange\nuser: I made orange bitters using orange peels and vodka.",
    )

    assert daiquiri.present and gimlet.present and orange.present
    assert daiquiri.member_ids == gimlet.member_ids
    assert daiquiri.member_ids != orange.member_ids


def test_projection_uses_user_assertions_not_assistant_suggestions() -> None:
    projection = project_distinct_set_evidence(
        query="How many tanks do I currently have?",
        text=(
            "source-a\nuser: I have a 5-gallon tank with a betta.\n"
            "assistant: You could buy a large quarantine tank next."
        ),
    )

    assert projection.present
    assert "5-gallon tank" in projection.rendered_text
    assert "quarantine tank" not in projection.rendered_text


@pytest.mark.parametrize("role", ("assistant", "system"))
def test_projection_rejects_role_labeled_non_user_first_person_text(role: str) -> None:
    projection = project_distinct_set_evidence(
        query="How many tanks do I currently have?",
        text=f"{role}: I have a 5-gallon tank.",
    )

    assert not projection.present
    assert projection.identities == ()


def test_projection_respects_current_state_and_explicit_month_bounds() -> None:
    current = project_distinct_set_evidence(
        query="How many tanks do I currently have?",
        text=(
            "source-a\nuser: My old 2-gallon tank was difficult to clean. "
            "I have a 5-gallon tank now."
        ),
    )
    february = project_distinct_set_evidence(
        query="How many museums did I visit in February?",
        text=(
            "source-b\nuser: I attended a workshop at the Modern Art Museum in January. "
            "I visited the Natural History Museum in February."
        ),
    )

    assert "old 2-gallon tank" not in current.rendered_text
    assert "5-gallon tank" in current.rendered_text
    assert "Modern Art Museum" not in february.rendered_text
    assert "Natural History Museum" in february.rendered_text


def test_projection_filters_each_temporal_clause_before_collecting_members() -> None:
    current = project_distinct_set_evidence(
        query="How many tanks do I currently have?",
        text=(
            "user: I no longer have a 2-gallon tank, "
            "but I still have a 5-gallon tank."
        ),
    )
    february = project_distinct_set_evidence(
        query="How many museums did I visit in February?",
        text=(
            "user: I visited the Modern Art Museum in January "
            "and the Natural History Museum in February."
        ),
    )

    assert current.identities == ("5-gallon tank",)
    assert current.temporal_rejection_count == 1
    assert february.identities == ("natural history museum",)
    assert february.temporal_rejection_count == 1


def test_projection_supports_accompanied_visits_and_numeric_month_bounds() -> None:
    query = "How many museums did I visit in February?"

    february = project_distinct_set_evidence(
        query=query,
        text="user: I took my niece to the Natural History Museum on 2/8.",
    )
    january = project_distinct_set_evidence(
        query=query,
        text="user: I took my niece to the Natural History Museum on 1/28.",
    )

    assert february.identities == ("natural history museum",)
    assert not january.present
    assert january.temporal_conflict


def test_projection_accepts_named_gallery_visited_in_requested_month() -> None:
    projection = project_distinct_set_evidence(
        query="How many museums or galleries did I visit in February?",
        text="user: I visited The Art Cube on 2/15.",
    )

    assert projection.identities == ("art cube",)


def test_projection_treats_seen_property_and_diorama_as_grounded_members() -> None:
    property_projection = project_distinct_set_evidence(
        query="How many properties did I view before making an offer?",
        text=(
            "user: I've seen some properties that did not fit my budget, "
            "like that one in Cedar Creek."
        ),
    )
    kit_projection = project_distinct_set_evidence(
        query="How many model kits have I worked on or bought?",
        text="user: I started working on a diorama featuring a Tiger tank.",
    )

    assert property_projection.present
    assert kit_projection.present


def test_this_year_wedding_projection_excludes_last_year_and_keeps_last_weekend() -> None:
    projection = project_distinct_set_evidence(
        query="How many weddings have I attended this year?",
        text=(
            "user: I attended Robin's wedding last year, "
            "but I attended a wedding last weekend."
        ),
    )

    assert projection.identities == ("wedding weekend",)
    assert "Robin" not in projection.rendered_text
    assert "wedding last weekend" in projection.rendered_text
    assert projection.temporal_rejection_count == 1


def test_recent_furniture_projection_recognizes_an_ordered_mattress() -> None:
    projection = project_distinct_set_evidence(
        query="How many pieces of furniture did I buy in the past few months?",
        text="user: I ordered a new mattress from Casper last week.",
    )

    assert projection.present
    assert projection.identities == ("mattress casper",)
    assert "ordered a new mattress" in projection.rendered_text


def test_named_subject_request_rejects_another_speakers_first_person_assertion() -> None:
    query = "How many weddings has Morgan attended this year?"

    wrong_subject = project_distinct_set_evidence(
        query=query,
        text="user: I attended Riley's wedding this year.",
    )
    grounded_subject = project_distinct_set_evidence(
        query=query,
        text="user: Morgan attended Riley's wedding this year.",
    )

    assert not wrong_subject.present
    assert wrong_subject.subject_conflict
    assert grounded_subject.present


def test_named_subject_projection_isolates_explicit_other_subject_clause() -> None:
    projection = project_distinct_set_evidence(
        query="How many weddings has Morgan attended?",
        text=(
            "user: Morgan attended Riley's wedding, "
            "but Jordan attended Casey's wedding."
        ),
    )

    assert projection.identities == ("morgan attended riley's wedding",)
    assert "Jordan" not in projection.rendered_text
    assert projection.subject_rejection_count == 1


def test_named_provider_identity_is_action_and_target_grounded() -> None:
    projection = project_distinct_set_evidence(
        query="How many food delivery services have I used recently?",
        text=(
            "user: In March I used DoorDash for food delivery "
            "while listening to Spotify."
        ),
    )

    assert projection.identities == ("doordash",)
    assert "march" not in projection.identities
    assert "spotify" not in projection.identities


@pytest.mark.parametrize(
    ("text", "identity"),
    (
        ("user: I had Domino's Pizza after relying on food delivery services.", "domino's pizza"),
        ("user: My weekends have been all about Uber Eats lately.", "uber eat"),
        (
            "user: I've been relying on food delivery services, like one called Fresh Fusion.",
            "fresh fusion",
        ),
    ),
)
def test_named_provider_projection_keeps_grounded_delivery_provider(
    text: str,
    identity: str,
) -> None:
    projection = project_distinct_set_evidence(
        query="How many food delivery services have I used recently?",
        text=text,
    )

    assert projection.identities == (identity,)


def test_domain_policy_dedupes_source_first_and_member_second() -> None:
    selection = DistinctSetMemberReservationPolicy().select(
        (
            _candidate("lime-current", "source-current", "lime"),
            _candidate("lime-context-variant", "source-old", "lime"),
            _candidate("orange", "source-orange", "orange"),
            _candidate("same-source-lemon", "source-orange", "lemon"),
        ),
        limit=8,
    )

    assert selection.selected_ids == ("lime-current", "orange")
    assert selection.reserved_member_ids == ("lime", "orange")


def test_packer_reserves_novel_members_without_selecting_duplicate_context_variant() -> None:
    query = "How many different types of citrus fruits have I used in cocktail recipes?"
    result = ContextPacker().pack(
        bundle_id="ctx-distinct",
        items=(
            _item(
                "lime-current",
                "source-current\nuser: I made a Gimlet using lime juice.",
                score=0.99,
                source="source-current",
            ),
            _item(
                "lime-old",
                "source-old\nuser: I learned a Daiquiri using lime juice.",
                score=0.98,
                source="source-old",
            ),
            _item(
                "orange",
                "source-orange\nuser: I made orange bitters using orange peels.",
                score=0.97,
                source="source-orange",
            ),
        ),
        token_budget=100,
        query=query,
    )

    selected_ids = {item.item_id for item in result.bundle.items}
    assert selected_ids == {"lime-current", "orange"}
    selected_lime = next(item for item in result.bundle.items if item.item_id == "lime-current")
    assert {ref.source_id for ref in selected_lime.source_refs} == {
        "source-current",
        "source-old",
    }
    assert result.bundle.diagnostics["distinct_set_items_selected"] == 2
    assert result.bundle.diagnostics["distinct_set_member_slots_selected"] == 2


def test_exact_member_projection_is_restored_after_generic_candidate_policies() -> None:
    evidence = ContextItem(
        item_id="shared",
        item_type="chunk",
        text="source-a\nuser assertion: I attended my cousin's vineyard wedding.",
        score=0.985,
        source_refs=(SourceRef(source_type="synthetic", source_id="source-a"),),
        diagnostics={
            "retrieval_source": "keyword_aggregation_chunks",
            "retrieval_sources": ["keyword_aggregation_chunks"],
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )
    generic = ContextItem(
        item_id="shared",
        item_type="chunk",
        text="source-a\nassistant: Here are some wedding planning suggestions.",
        score=0.99,
        source_refs=evidence.source_refs,
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
        },
    )

    restored, diagnostics = restore_distinct_set_evidence_items(
        (generic,),
        query="How many different weddings have I attended this year?",
        evidence_items=(evidence,),
    )

    assert restored[0].text == evidence.text
    assert restored[0].score == generic.score
    assert diagnostics == {
        "distinct_set_evidence_items_considered": 1,
        "distinct_set_evidence_bodies_restored": 1,
        "distinct_set_evidence_items_readded": 0,
        "distinct_set_evidence_items_missing_after_ranking": 0,
        "distinct_set_evidence_items_rejected_by_rerank": 0,
    }


def test_exact_member_projection_is_evaluated_by_rerank_before_final_restoration() -> None:
    query = "How many different types of citrus fruits have I used in cocktail recipes?"
    evidence = _item(
        "shared",
        "source-a\nuser assertion: I used lime juice in a cocktail recipe.",
        score=0.985,
        source="source-a",
    )
    evidence = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )

    prepared, diagnostics = prepare_distinct_set_evidence_for_rerank(
        (), evidence_items=(evidence,)
    )

    assert prepared[0].text == evidence.text
    assert prepared[0].diagnostics is not None
    assert prepared[0].diagnostics["provenance"] == {
        "distinct_set_projection_verified": True,
    }
    assert "deterministic_rerank_applied" not in prepared[0].diagnostics["provenance"]
    assert diagnostics["distinct_set_evidence_items_added_for_rerank"] == 1

    reranked = apply_deterministic_rerank_adjustments(
        prepared,
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    rerank_provenance = reranked[0].diagnostics["provenance"]
    assert rerank_provenance["distinct_set_projection_verified"] is True
    assert rerank_provenance["deterministic_rerank_applied"] is True
    assert rerank_provenance["deterministic_rerank_anchor_conflict"] is False
    assert "query_relevance_supported" in rerank_provenance["deterministic_rerank_reasons"]

    rejected = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "provenance": {"deterministic_rerank_reasons": ["query_anchor_conflict"]},
        },
    )
    rejected_prepared, rejected_diagnostics = prepare_distinct_set_evidence_for_rerank(
        (), evidence_items=(rejected,)
    )
    assert rejected_prepared == ()
    assert rejected_diagnostics["distinct_set_evidence_items_rejected_before_rerank"] == 1


def test_safe_exact_projection_clears_stale_same_key_generic_rerank_rejection() -> None:
    query = "How many different types of citrus fruits have I used in cocktail recipes?"
    evidence = _item(
        "shared",
        "source-safe\nuser assertion: I used lime juice in a cocktail recipe.",
        score=0.985,
        source="source-safe",
    )
    evidence = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )
    stale_generic = replace(
        evidence,
        text="source-stale\nassistant: Generic cocktail planning notes.",
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {
                "keyword_aggregation_distinct_member_support": 1,
                "deterministic_rerank_penalty": 0.1,
            },
            "provenance": {
                "deterministic_rerank_applied": True,
                "deterministic_rerank_reasons": ["query_anchor_conflict"],
                "deterministic_rerank_anchor_conflict": True,
            },
        },
    )

    prepared, diagnostics = prepare_distinct_set_evidence_for_rerank(
        (stale_generic,), evidence_items=(evidence,)
    )

    assert diagnostics["distinct_set_evidence_bodies_restored"] == 1
    assert prepared[0].text == evidence.text
    assert prepared[0].diagnostics["provenance"] == {
        "distinct_set_projection_verified": True
    }
    assert "deterministic_rerank_penalty" not in prepared[0].diagnostics["score_signals"]

    reranked = apply_deterministic_rerank_adjustments(
        prepared,
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
    )
    assert reranked[0].diagnostics["provenance"]["deterministic_rerank_applied"] is True
    assert not any(
        "conflict" in reason
        for reason in reranked[0].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_restoration_does_not_revive_missing_or_rerank_rejected_evidence() -> None:
    evidence = _item(
        "shared",
        "source-a\nuser: I attended a wedding last weekend.",
        score=0.985,
        source="source-a",
    )
    evidence = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )
    rejected = ContextItem(
        item_id="shared",
        item_type="chunk",
        text="source-a\nassistant: Here are wedding suggestions.",
        score=0.8,
        source_refs=evidence.source_refs,
        diagnostics={
            "provenance": {"deterministic_rerank_reasons": ["query_anchor_conflict"]},
        },
    )

    missing_items, missing_diagnostics = restore_distinct_set_evidence_items(
        (),
        query="How many weddings have I attended this year?",
        evidence_items=(evidence,),
    )
    rejected_items, rejected_diagnostics = restore_distinct_set_evidence_items(
        (rejected,),
        query="How many weddings have I attended this year?",
        evidence_items=(evidence,),
    )

    assert missing_items == ()
    assert missing_diagnostics["distinct_set_evidence_items_missing_after_ranking"] == 1
    assert rejected_items == (rejected,)
    assert rejected_diagnostics["distinct_set_evidence_items_rejected_by_rerank"] == 1

    safe_ranked = replace(rejected, diagnostics={})
    readded_items, readded_diagnostics = restore_distinct_set_evidence_items(
        (),
        query="How many weddings have I attended this year?",
        evidence_items=(evidence,),
        ranked_items=(safe_ranked,),
    )
    assert readded_items[0].text == evidence.text
    assert readded_diagnostics["distinct_set_evidence_items_readded"] == 1

    rejected_ranked_items, rejected_ranked_diagnostics = restore_distinct_set_evidence_items(
        (),
        query="How many weddings have I attended this year?",
        evidence_items=(evidence,),
        ranked_items=(rejected,),
    )
    assert rejected_ranked_items == ()
    assert rejected_ranked_diagnostics["distinct_set_evidence_items_rejected_by_rerank"] == 1

    packed = ContextPacker().pack(
        bundle_id="ctx-rerank-rejected-distinct",
        items=(replace(rejected, text=evidence.text),),
        token_budget=200,
        query="How many weddings have I attended this year?",
    )
    assert packed.bundle.diagnostics["distinct_set_items_selected"] == 0


def test_reserved_projection_survives_generic_missing_relation_to_prepack() -> None:
    query = (
        "How many different cuisines have I learned to cook or tried out "
        "in the past few months?"
    )
    evidence = _item(
        "reserved-member",
        "source-a\nuser: I learned to make a curry in a class on Indian cuisine.",
        score=0.985,
        source="source-a",
    )
    evidence = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )
    ranked = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "provenance": {
                "deterministic_rerank_reasons": [
                    "relation_requirement_missing_relation",
                ],
            },
        },
    )

    restored, diagnostics = restore_distinct_set_evidence_items(
        (),
        query=query,
        evidence_items=(evidence,),
        ranked_items=(ranked,),
    )
    guarded, guard_diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=restored,
    )
    packed = ContextPacker().pack(
        bundle_id="ctx-reserved-distinct-member",
        items=guarded,
        token_budget=200,
        query=query,
    )

    assert diagnostics["distinct_set_evidence_items_readded"] == 1
    assert guarded == restored
    assert guard_diagnostics["requirement_guard_relation_mismatch_drop_count"] == 0
    assert [item.item_id for item in packed.bundle.items] == ["reserved-member"]
    assert packed.bundle.diagnostics["distinct_set_items_selected"] == 1


def test_reserved_projection_does_not_override_relation_object_mismatch() -> None:
    query = "How many different cuisines have I learned to cook or tried out?"
    evidence = _item(
        "wrong-object",
        "source-a\nuser: I learned to make a curry in a class on Indian cuisine.",
        score=0.985,
        source="source-a",
    )
    evidence = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "score_signals": {"keyword_aggregation_distinct_member_support": 1},
        },
    )
    ranked = replace(
        evidence,
        diagnostics={
            **(evidence.diagnostics or {}),
            "provenance": {
                "deterministic_rerank_reasons": [
                    "relation_requirement_object_mismatch",
                ],
            },
        },
    )

    restored, diagnostics = restore_distinct_set_evidence_items(
        (),
        query=query,
        evidence_items=(evidence,),
        ranked_items=(ranked,),
    )

    assert restored == ()
    assert diagnostics["distinct_set_evidence_items_rejected_by_rerank"] == 1


def _candidate(candidate_id: str, source: str, member: str) -> DistinctSetMemberCandidate:
    return DistinctSetMemberCandidate(
        candidate_id=candidate_id,
        source_family=source,
        member_ids=(member,),
    )


def _item(item_id: str, text: str, *, score: float, source: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="synthetic", source_id=source),),
        diagnostics={
            "memory_scope_id": "scope",
            "retrieval_source": "keyword_aggregation_chunks",
            "retrieval_sources": ["keyword_aggregation_chunks"],
        },
    )
