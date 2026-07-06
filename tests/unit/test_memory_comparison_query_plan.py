from __future__ import annotations

from infinity_context_server.memory_comparison_query_plan import (
    QueryPlanCandidate,
    QueryPlannerV2,
)


def test_query_planner_caps_fanout_and_preserves_recommended_evidence_families() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate("temporal_support", "caroline date time", priority=40),
            _candidate("original_question", "What did Caroline research?", priority=0),
            _candidate(
                "expanded_focus",
                "What did Caroline research?\nSearch focus: entities: caroline",
                priority=10,
            ),
            _candidate(
                "compact_relation",
                "caroline research researching look check",
                priority=30,
            ),
            _candidate(
                "multi_hop_support",
                "What did Caroline research? supporting evidence caroline",
                priority=50,
            ),
        ),
        fallback_query="What did Caroline research?",
        recommended_role_families=(
            "base_query",
            "expanded_focus",
            "relation_compact",
            "temporal_support",
        ),
    )

    assert plan.queries == (
        "What did Caroline research?",
        "caroline research researching look check",
        "caroline date time",
    )
    diagnostics = plan.to_diagnostics()
    assert diagnostics["schema_version"] == "query_plan.v2"
    assert diagnostics["selected_roles"] == [
        "original_question",
        "compact_relation",
        "temporal_support",
    ]
    assert diagnostics["dropped_roles"] == [
        "expanded_focus",
        "multi_hop_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
        "temporal_support",
    ]
    assert diagnostics["missing_recommended_role_families"] == [
        "expanded_focus"
    ]
    assert diagnostics["fanout_integrity"]["bounded"] is True
    assert diagnostics["fanout_integrity"]["fanout_limit_hit"] is True
    assert diagnostics["fanout_integrity"]["max_selected_query_token_count"] == 5
    assert diagnostics["leakage_guard"]["answer_terms_allowed"] is False


def test_query_planner_dedupes_equivalent_queries() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate("original_question", "What did Caroline research?", priority=0),
            _candidate(
                "duplicate_original",
                " What   did Caroline research? ",
                priority=5,
            ),
            _candidate(
                "compact_relation",
                "caroline research researching look check",
                priority=30,
            ),
        ),
        fallback_query="What did Caroline research?",
    )

    assert plan.queries == (
        "What did Caroline research?",
        "caroline research researching look check",
    )
    assert plan.duplicate_roles == ("duplicate_original",)
    assert plan.to_diagnostics()["duplicate_roles"] == ["duplicate_original"]


def test_query_planner_groups_community_membership_as_relation_compact() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate(
                "original_question",
                "Is Alex part of the LGBTQ community?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "community_membership_support",
                "alex lgbtq community member joined pride",
                priority=30,
                query_type="lexical",
            ),
        ),
        fallback_query="Is Alex part of the LGBTQ community?",
        recommended_role_families=("base_query", "relation_compact"),
    )

    diagnostics = plan.to_diagnostics()

    assert diagnostics["selected_roles"] == [
        "original_question",
        "community_membership_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_preserves_query_type_diversity() -> None:
    plan = QueryPlannerV2(max_queries=3, max_queries_per_type=2).plan(
        (
            _candidate(
                "original_question",
                "Would Caroline pursue writing?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "Would Caroline pursue writing?\nSearch focus: entities: caroline",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "multi_hop_support",
                "Would Caroline pursue writing? supporting evidence caroline",
                priority=20,
                query_type="semantic",
            ),
            _candidate(
                "compact_relation",
                "caroline writing career option counseling",
                priority=30,
                query_type="lexical",
            ),
        ),
        fallback_query="Would Caroline pursue writing?",
    )

    assert plan.queries == (
        "Would Caroline pursue writing?",
        "Would Caroline pursue writing?\nSearch focus: entities: caroline",
        "caroline writing career option counseling",
    )
    diagnostics = plan.to_diagnostics()
    assert diagnostics["selected_type_counts"] == {"semantic": 2, "lexical": 1}
    assert diagnostics["candidate_type_counts"] == {"semantic": 3, "lexical": 1}
    assert diagnostics["dropped_type_limit_roles"] == ["multi_hop_support"]
    assert diagnostics["fanout_integrity"]["type_limit_hit"] is True


def test_query_planner_can_select_multi_hop_bridge_with_compact_query() -> None:
    plan = QueryPlannerV2(max_queries=4, max_queries_per_type=3).plan(
        (
            _candidate(
                "original_question",
                "Why did Caroline choose the adoption agency?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "Why did Caroline choose the adoption agency?\nSearch focus: entities",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "compact_relation",
                "caroline adoption chose reason cause fit value",
                priority=30,
                query_type="lexical",
            ),
            _candidate(
                "multi_hop_bridge",
                "caroline adoption chose reason cause because decision",
                priority=45,
                query_type="lexical",
            ),
            _candidate(
                "multi_hop_support",
                "Why did Caroline choose the adoption agency? supporting evidence caroline",
                priority=50,
                query_type="semantic",
            ),
        ),
        fallback_query="Why did Caroline choose the adoption agency?",
    )

    assert plan.queries == (
        "Why did Caroline choose the adoption agency?",
        "Why did Caroline choose the adoption agency?\nSearch focus: entities",
        "caroline adoption chose reason cause fit value",
        "caroline adoption chose reason cause because decision",
    )
    diagnostics = plan.to_diagnostics()
    assert diagnostics["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "compact_relation",
        "multi_hop_bridge",
    ]
    assert diagnostics["dropped_roles"] == ["multi_hop_support"]


def test_query_planner_uses_fallback_when_candidates_are_empty() -> None:
    plan = QueryPlannerV2(max_queries=3).plan((), fallback_query="Where is it?")

    assert plan.queries == ("Where is it?",)
    assert plan.selected[0].role == "fallback_original"
    assert plan.applied is False
    assert plan.to_diagnostics()["max_queries_per_type"] == 2


def test_query_planner_reports_empty_candidates_and_multi_family_roles() -> None:
    plan = QueryPlannerV2(max_queries=2).plan(
        (
            _candidate("empty_visual", "   ", priority=0),
            _candidate(
                "visual_temporal_support",
                "melanie image date caption",
                priority=10,
                query_type="lexical",
            ),
        ),
        fallback_query="When did Melanie share the image?",
        recommended_role_families=("visual_support", "temporal_support"),
    )

    diagnostics = plan.to_diagnostics()
    assert diagnostics["selected_role_families"] == [
        "visual_support",
        "temporal_support",
    ]
    assert diagnostics["missing_recommended_role_families"] == []
    assert diagnostics["role_family_counts"] == {
        "temporal_support": 1,
        "visual_support": 1,
    }
    assert diagnostics["fanout_integrity"]["empty_query_candidate_count"] == 1


def test_query_planner_preserves_location_support_family() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate(
                "original_question",
                "Where did Caroline move from?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "Where did Caroline move from?\nSearch focus: entities: caroline",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "compact_relation",
                "caroline move moved home country relocated came",
                priority=30,
            ),
            _candidate(
                "location_support",
                "caroline move moved home country relocated came origin from city",
                priority=37,
            ),
        ),
        fallback_query="Where did Caroline move from?",
        recommended_role_families=(
            "base_query",
            "relation_compact",
            "location_support",
        ),
    )

    diagnostics = plan.to_diagnostics()
    assert diagnostics["selected_roles"] == [
        "original_question",
        "compact_relation",
        "location_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
        "relation_compact",
        "location_support",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_type_limit_replacement_preserves_relation_support() -> None:
    plan = QueryPlannerV2(max_queries=3, max_queries_per_type=1).plan(
        (
            _candidate(
                "original_question",
                "Where did Caroline move from?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "Where did Caroline move from?\nSearch focus: entities: caroline",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "compact_relation",
                "caroline move moved home country relocated came",
                priority=30,
            ),
            _candidate(
                "location_support",
                "caroline move moved home country relocated came origin from city",
                priority=37,
            ),
        ),
        fallback_query="Where did Caroline move from?",
        recommended_role_families=(
            "base_query",
            "relation_compact",
            "location_support",
        ),
    )

    diagnostics = plan.to_diagnostics()

    assert diagnostics["selected_roles"] == [
        "original_question",
        "location_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
        "location_support",
    ]
    assert diagnostics["dropped_roles"] == [
        "expanded_focus",
        "compact_relation",
    ]
    assert diagnostics["selected_type_counts"] == {"semantic": 1, "lexical": 1}
    assert diagnostics["dropped_type_limit_roles"] == ["expanded_focus"]
    assert diagnostics["replaced_type_limit_roles"] == ["compact_relation"]
    assert diagnostics["type_limit_replacement_roles"] == ["location_support"]
    assert diagnostics["fanout_integrity"]["type_limit_hit"] is True
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_preserves_value_support_family() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate(
                "original_question",
                "What was the deposit amount?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "What was the deposit amount?\nSearch focus: entities: mia",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "compact_relation",
                "mia ceramics class deposit registration",
                priority=30,
            ),
            _candidate(
                "value_support",
                "mia ceramics class deposit amount price dollar value",
                priority=37,
            ),
        ),
        fallback_query="What was the deposit amount?",
        recommended_role_families=(
            "base_query",
            "value_support",
        ),
    )

    diagnostics = plan.to_diagnostics()

    assert diagnostics["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "value_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "expanded_focus",
        "value_support",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_maps_relation_support_roles_to_compact_family() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate(
                "original_question",
                "Who did Alex tell about the delay?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "communication_support",
                "alex tell told mention delay maria",
                priority=30,
            ),
        ),
        fallback_query="Who did Alex tell about the delay?",
        recommended_role_families=("base_query", "relation_compact"),
    )

    diagnostics = plan.to_diagnostics()
    assert diagnostics["selected_roles"] == [
        "original_question",
        "communication_support",
    ]
    assert diagnostics["role_family_counts"] == {
        "base_query": 1,
        "relation_compact": 1,
    }
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_preserves_preference_and_causal_support_families() -> None:
    plan = QueryPlannerV2(max_queries=4, max_queries_per_type=3).plan(
        (
            _candidate(
                "original_question",
                "Why does Alex prefer tea?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "Why does Alex prefer tea?\nSearch focus: entities: alex",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "causal_support",
                "alex reason because cause prefer tea",
                priority=30,
            ),
            _candidate(
                "preference_support",
                "alex prefer tea like preferred",
                priority=34,
            ),
            _candidate(
                "multi_hop_bridge",
                "alex prefer tea reason because decision",
                priority=45,
            ),
        ),
        fallback_query="Why does Alex prefer tea?",
        recommended_role_families=(
            "base_query",
            "relation_compact",
            "preference_support",
            "causal_support",
            "multi_hop",
        ),
    )

    diagnostics = plan.to_diagnostics()

    assert diagnostics["selected_roles"] == [
        "original_question",
        "causal_support",
        "preference_support",
        "multi_hop_bridge",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "relation_compact",
        "causal_support",
        "relation_compact",
        "preference_support",
        "multi_hop",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def test_query_planner_preserves_commonality_support_family() -> None:
    plan = QueryPlannerV2(max_queries=3).plan(
        (
            _candidate(
                "original_question",
                "What do Alex and Riley have in common?",
                priority=0,
                query_type="semantic",
            ),
            _candidate(
                "expanded_focus",
                "What do Alex and Riley have in common?\nSearch focus: entities",
                priority=10,
                query_type="semantic",
            ),
            _candidate(
                "commonality_support",
                "alex riley common shared both mutual place activity event",
                priority=36,
            ),
        ),
        fallback_query="What do Alex and Riley have in common?",
        recommended_role_families=("base_query", "commonality_support"),
    )

    diagnostics = plan.to_diagnostics()

    assert diagnostics["selected_roles"] == [
        "original_question",
        "expanded_focus",
        "commonality_support",
    ]
    assert diagnostics["selected_role_families"] == [
        "base_query",
        "expanded_focus",
        "commonality_support",
    ]
    assert diagnostics["missing_recommended_role_families"] == []


def _candidate(
    role: str,
    query: str,
    *,
    priority: int,
    query_type: str = "lexical",
) -> QueryPlanCandidate:
    return QueryPlanCandidate(
        role=role,
        query=query,
        priority=priority,
        query_type=query_type,
        reason_codes=(role,),
    )
