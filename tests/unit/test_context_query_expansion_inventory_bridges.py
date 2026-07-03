from infinity_context_core.application.context_query_expansion import build_query_expansion_plan
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_expansion_covers_children_name_inventory() -> None:
    plan = build_query_expansion_plan("What are the names of Alex's children?")

    bridge = _expansion_query(plan, "children_name_inventory_bridge")

    assert bridge.startswith("Alex ")
    assert "children child kids kid names named called" in bridge
    assert "son daughter" in bridge


def test_query_expansion_covers_childhood_possession_inventory() -> None:
    plan = build_query_expansion_plan("What items did Alex mention having as a child?")

    bridge = _expansion_query(plan, "childhood_possession_inventory_bridge")

    assert bridge.startswith("Alex ")
    assert "childhood child kid kids when younger" in bridge
    assert "possession object item keepsake toy memento" in bridge


def test_query_expansion_covers_repeated_test_attempts() -> None:
    plan = build_query_expansion_plan("What test has Alex taken multiple times?")

    bridge = _expansion_query(plan, "repeated_test_attempt_bridge")

    assert bridge.startswith("Alex ")
    assert "test tests exam assessment" in bridge
    assert "multiple times repeated retook" in bridge


def test_query_expansion_skips_repeated_test_bridge_for_technical_queries() -> None:
    plan = build_query_expansion_plan("Which CI tests failed multiple times?")

    assert "repeated_test_attempt_bridge" not in {
        expansion.reason for expansion in plan.expansions
    }


def test_query_expansion_covers_family_hardship_support() -> None:
    plan = build_query_expansion_plan(
        "Who gave Alex's family money when he was younger and things were tough?"
    )

    bridge = _expansion_query(plan, "family_hardship_support_bridge")

    assert bridge.startswith("Alex ")
    assert "family money problems financial hardship" in bridge
    assert "outside help helped support relative relatives" in bridge


def test_query_expansion_covers_shelter_fundraiser_event_lists() -> None:
    plan = build_query_expansion_plan(
        "What events is Riley planning for the homeless shelter fundraiser?"
    )

    bridge = _expansion_query(plan, "fundraiser_event_inventory_bridge")

    assert bridge.startswith("Riley ")
    assert "shelter fundraiser fundraising planned planning" in bridge
    assert "tournament cook-off poster booth game homeless" in bridge
    assert " event " not in f" {bridge} "
    assert " activity " not in f" {bridge} "


def test_query_expansion_covers_yoga_style_inventory() -> None:
    plan = build_query_expansion_plan("What types of yoga has Riley practiced?")

    bridge = _expansion_query(plan, "exercise_activity_inventory_bridge")

    assert bridge.startswith("Riley ")
    assert "yoga type types style styles practiced" in bridge
    assert "class classes started starting trying tried" in bridge


def test_query_expansion_skips_yoga_inventory_for_delay_questions() -> None:
    plan = build_query_expansion_plan("Why did Riley put off yoga?")
    reasons = {expansion.reason for expansion in plan.expansions}

    assert "yoga_delay_gaming_bridge" in reasons
    assert "exercise_activity_inventory_bridge" not in reasons


def test_query_expansion_prefers_specific_veterans_event_inventory() -> None:
    plan = build_query_expansion_plan(
        "What events for veterans has Riley participated in?"
    )
    reasons = {expansion.reason for expansion in plan.expansions}

    assert "veterans_event_inventory_bridge" in reasons
    assert "event_participation_bridge" not in reasons


def test_query_expansion_covers_outdoor_visual_group_responses() -> None:
    plan = build_query_expansion_plan(
        "What outdoor activities has Riley done with colleagues?"
    )
    reasons = {expansion.reason for expansion in plan.expansions}

    bridge = _expansion_query(plan, "outdoor_activity_inventory_bridge")

    assert "hobby_interest_bridge" not in reasons
    assert bridge.startswith("Riley ")
    assert "colleagues friends team group people" in bridge
    assert "photo image visual waterfall" in bridge


def test_query_expansion_covers_music_event_inventory_variants() -> None:
    singular = build_query_expansion_plan("What music event has John attended?")
    concert = build_query_expansion_plan("Which concerts did John attend?")

    singular_bridge = _expansion_query(singular, "music_event_inventory_bridge")
    concert_bridge = _expansion_query(concert, "music_event_inventory_bridge")

    assert singular_bridge.startswith("John ")
    assert concert_bridge.startswith("John ")
    assert "music events concert concerts festival festivals" in singular_bridge
    assert "music events concert concerts festival festivals" in concert_bridge


def test_best_query_relevance_uses_music_event_inventory_for_concert_questions() -> None:
    plan = build_query_expansion_plan("Which concerts did John attend?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="D8:12 John found a violin concert that everyone enjoyed.",
    )

    assert reason == "music_event_inventory_bridge"
    assert relevance.distinctive_term_hits >= 2


def _expansion_query(plan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion reason {reason!r}: {plan.expansions!r}")
