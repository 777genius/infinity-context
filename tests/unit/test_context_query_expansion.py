from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.use_cases.build_context import (
    _best_query_relevance,
    _keyword_chunk_score,
)


def test_query_expansion_preserves_identity_for_relocation_bridge() -> None:
    plan = build_query_expansion_plan("Where did Caroline move from 4 years ago?")

    assert plan.retrieval_queries[0].reason == "original_query"
    relocation = _expansion_query(plan, "relocation_origin_bridge")
    assert relocation.startswith("Caroline ")
    assert "home country roots" in relocation


def test_query_expansion_covers_low_overlap_ally_and_outdoor_questions() -> None:
    ally = build_query_expansion_plan(
        "Would Melanie be considered an ally to the transgender community?"
    )
    outdoor = build_query_expansion_plan(
        "Would Melanie be more interested in going to a national park or a theme park?"
    )

    assert _expansion_query(ally, "ally_support_bridge").startswith("Melanie ")
    assert "supportive support acceptance" in _expansion_query(
        ally,
        "ally_support_bridge",
    )
    assert _expansion_query(outdoor, "outdoor_preference_bridge").startswith(
        "Melanie "
    )
    assert "camping trip campfire meteor shower" in _expansion_query(
        outdoor,
        "outdoor_preference_bridge",
    )
    assert "meteor shower sky universe" in _expansion_query(
        outdoor,
        "outdoor_nature_memory_bridge",
    )


def test_query_expansion_is_bounded_and_deduplicated_by_reason() -> None:
    plan = build_query_expansion_plan(
        "Would Melanie support growing up, move from home, choose a national park "
        "or theme park, make a decision to adopt, be an ally to the transgender "
        "community, have political leaning, be religious, and destress?"
    )

    reasons = [expansion.reason for expansion in plan.expansions]
    assert len(plan.expansions) <= 8
    assert len(reasons) == len(set(reasons))
    assert reasons.count("outdoor_preference_bridge") == 1
    assert reasons.count("outdoor_nature_memory_bridge") <= 1


def test_query_expansion_covers_activity_location_and_destress_bridges() -> None:
    camped = build_query_expansion_plan("Where has Melanie camped?")
    activities = build_query_expansion_plan("What activities does Melanie partake in?")
    destress = build_query_expansion_plan("What does Melanie do to destress?")

    assert "mountains beach forest" in _expansion_query(
        camped,
        "camping_location_bridge",
    )
    assert "pottery camping painting swimming" in _expansion_query(
        activities,
        "activity_aggregation_bridge",
    )
    assert "running pottery class therapeutic" in _expansion_query(
        destress,
        "destress_activity_bridge",
    )


def test_query_expansion_covers_trait_and_adverse_trip_bridges() -> None:
    traits = build_query_expansion_plan(
        "What personality traits might Melanie say Caroline has?"
    )
    roadtrip = build_query_expansion_plan("Would Melanie go on another roadtrip soon?")

    assert "thoughtful authentic driven" in _expansion_query(
        traits,
        "personality_trait_bridge",
    )
    assert "thoughtful concern" in _expansion_query(
        traits,
        "personality_thoughtfulness_bridge",
    )
    assert "authentic real genuine" in _expansion_query(
        traits,
        "personality_authenticity_bridge",
    )
    assert "driven drive determined" in _expansion_query(
        traits,
        "personality_drive_bridge",
    )
    assert "accident scary scared bad start" in _expansion_query(
        roadtrip,
        "adverse_trip_bridge",
    )


def test_best_query_relevance_uses_expansion_for_low_overlap_evidence() -> None:
    plan = build_query_expansion_plan("Where did Caroline move from 4 years ago?")

    query, reason, relevance = _best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and reminds me of my roots."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "relocation_origin_bridge"
    assert relevance.distinctive_term_hits >= 2


def test_best_query_relevance_uses_specific_support_origin_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Caroline still want to pursue counseling as a career if she hadn't "
        "received support growing up?"
    )

    _, reason, relevance = _best_query_relevance(
        plan,
        text=(
            "D3:5 Caroline: I've been blessed with loads of love and support "
            "throughout this journey, and I want to pass it on to others. "
            "By sharing our stories, we can build a strong, supportive community "
            "of hope."
        ),
    )

    assert reason == "support_origin_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_support_career_motivation_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Caroline still want to pursue counseling as a career if she hadn't "
        "received support growing up?"
    )

    _, reason, relevance = _best_query_relevance(
        plan,
        text=(
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. I saw how counseling and support groups improved my life, "
            "so I started caring more about mental health. Now I'm passionate "
            "about creating a safe, inviting place for people to grow."
        ),
    )
    focused = score_query_relevance(
        query=_expansion_query(plan, "support_career_motivation_bridge"),
        text=(
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. I saw how counseling and support groups improved my life, "
            "so I started caring more about mental health. Now I'm passionate "
            "about creating a safe, inviting place for people to grow."
        ),
    )
    looser = score_query_relevance(
        query=_expansion_query(plan, "support_career_motivation_bridge"),
        text=(
            "D7:7 Caroline: I struggled with mental health, and support I got was "
            "really helpful. It made me realize how important it is for others to "
            "have a support system, so I started looking into counseling jobs."
        ),
    )

    assert reason == "support_career_motivation_bridge"
    assert relevance.distinctive_term_hits >= 10
    assert _keyword_chunk_score(
        focused,
        query_expansion_reason="support_career_motivation_bridge",
    ) > _keyword_chunk_score(
        looser,
        query_expansion_reason="support_career_motivation_bridge",
    )


def test_best_query_relevance_uses_trait_and_adverse_trip_bridges() -> None:
    traits = build_query_expansion_plan(
        "What personality traits might Melanie say Caroline has?"
    )
    roadtrip = build_query_expansion_plan("Would Melanie go on another roadtrip soon?")

    _, trait_reason, trait_relevance = _best_query_relevance(
        traits,
        text=(
            "D16:18 Melanie: Thank you for your concern, you're so thoughtful. "
            "D13:16 Melanie: You really care about being real and helping others. "
            "D7:4 Melanie: Your drive to help is awesome."
        ),
    )
    _, trip_reason, trip_relevance = _best_query_relevance(
        roadtrip,
        text=(
            "D18:1 Melanie: That roadtrip was insane and we were all freaked "
            "when my son got into an accident. D18:3 Melanie: Our trip got off "
            "to a bad start. I was really scared."
        ),
    )

    assert trait_reason == "personality_trait_bridge"
    assert trait_relevance.distinctive_term_hits >= 5
    assert trip_reason == "adverse_trip_bridge"
    assert trip_relevance.distinctive_term_hits >= 5


def test_trait_query_decomposition_targets_single_trait_turns() -> None:
    plan = build_query_expansion_plan(
        "What personality traits might Melanie say Caroline has?"
    )

    _, thoughtful_reason, thoughtful = _best_query_relevance(
        plan,
        text=(
            "D16:18 Melanie: The sign was just a precaution, but thank you for "
            "your concern, you're so thoughtful!"
        ),
    )
    _, authentic_reason, authentic = _best_query_relevance(
        plan,
        text=(
            "D13:16 Melanie: You really care about being real and helping others."
        ),
    )
    _, drive_reason, drive = _best_query_relevance(
        plan,
        text=(
            "D7:4 Melanie: Your drive to help is awesome! What's your plan to "
            "pitch in?"
        ),
    )

    assert thoughtful_reason == "personality_thoughtfulness_bridge"
    assert thoughtful.distinctive_term_hits >= 4
    assert authentic_reason == "personality_authenticity_bridge"
    assert authentic.distinctive_term_hits >= 4
    assert drive_reason == "personality_drive_bridge"
    assert drive.distinctive_term_hits >= 5


def test_best_query_relevance_uses_specific_outdoor_nature_memory_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Melanie be more interested in going to a national park or a theme park?"
    )

    _, reason, relevance = _best_query_relevance(
        plan,
        text=(
            "D10:14 Melanie: I'll always remember our camping trip last year "
            "when we saw the Perseid meteor shower. It was amazing watching "
            "the sky light up and feeling at one with the universe."
        ),
    )

    assert reason == "outdoor_nature_memory_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_keyword_chunk_score_separates_stronger_evidence_from_loose_match() -> None:
    query = (
        "Melanie camping trip campfire meteor shower nature outdoors"
    )
    strong = score_query_relevance(
        query=query,
        text=(
            "D10:12 D10:14 Melanie: Melanie's family tradition includes a "
            "camping trip where they roast marshmallows and tell stories around "
            "the campfire. Melanie and her family watched the Perseid meteor "
            "shower during a camping trip last year."
        ),
    )
    loose = score_query_relevance(
        query=query,
        text="D15:2 Melanie took her kids to a park and enjoyed seeing them outdoors.",
    )

    assert _keyword_chunk_score(
        strong,
        query_expansion_reason="outdoor_preference_bridge",
    ) > _keyword_chunk_score(
        loose,
        query_expansion_reason="outdoor_preference_bridge",
    )


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion reason: {reason}")
