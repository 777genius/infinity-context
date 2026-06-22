from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import best_query_relevance


def test_query_decomposition_splits_compound_event_artifact_query() -> None:
    plan = build_query_decomposition_plan(
        "What changed after the call with Alex about Atlas and what text was in the screenshot?"
    )

    reasons = [item.reason for item in plan.decompositions]
    queries = [item.query.casefold() for item in plan.decompositions]
    assert reasons.count("decomposition_clause") == 2
    assert "decomposition_event_context" in reasons
    assert "decomposition_temporal_change" in reasons
    assert "decomposition_artifact_evidence" in reasons
    assert any("alex atlas what text was in the screenshot" in query for query in queries)
    assert any("changed updated current previous" in query for query in queries)
    assert any("screenshot image video audio document ocr" in query for query in queries)
    assert plan.diagnostics()["query_decomposition_status"] == "available"


def test_query_decomposition_handles_russian_event_artifact_query() -> None:
    plan = build_query_decomposition_plan(
        "Что изменилось после созвона с алексом по Атласу и что было на скриншоте?"
    )

    queries = [item.query.casefold() for item in plan.decompositions]
    assert any("алекс" in query and "атлас" in query for query in queries)
    assert any("changed updated current previous" in query for query in queries)
    assert any("artifact file screenshot image video audio" in query for query in queries)


def test_query_decomposition_expands_relative_time_queries() -> None:
    plan = build_query_decomposition_plan("What did Alex say two hours ago?")

    relative = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_relative_time"
    )

    assert "alex" in relative.query.casefold()
    assert "hours_ago" in relative.query
    assert "transcript notes meeting call" in relative.query
    assert "decomposition_relative_time" in plan.diagnostics()[
        "query_decomposition_reasons"
    ]


def test_query_decomposition_adds_after_event_sequence_query() -> None:
    plan = build_query_decomposition_plan("What did Alex decide after the Atlas call?")

    sequence = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_event_sequence"
    )

    assert "alex" in sequence.query.casefold()
    assert "atlas" in sequence.query.casefold()
    assert "after following later next timeline" in sequence.query
    assert "meeting call conversation event" in sequence.query


def test_query_decomposition_adds_before_event_sequence_query() -> None:
    plan = build_query_decomposition_plan("What was Alex thinking before the review?")

    sequence = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_event_sequence"
    )

    assert sequence.query.casefold().startswith("alex ")
    assert "before earlier prior previous timeline" in sequence.query
    assert "meeting call conversation event" in sequence.query


def test_query_decomposition_is_bounded_and_deduplicated() -> None:
    plan = build_query_decomposition_plan(
        "What changed after the call with Alex about Atlas and what changed after "
        "the call with Alex about Atlas and show source and screenshot and video?"
    )

    queries = [item.query.casefold() for item in plan.decompositions]
    assert len(plan.decompositions) <= 6
    assert len(queries) == len(set(queries))
    assert plan.diagnostics()["query_decomposition_count"] == len(plan.decompositions)


def test_query_expansion_plan_uses_decompositions_for_retrieval_queries() -> None:
    plan = build_query_expansion_plan(
        "What changed after the meeting with Alex and what was written in the screenshot?"
    )

    retrieval_reasons = [item.reason for item in plan.retrieval_queries]
    assert retrieval_reasons[0] == "original_query"
    assert "decomposition_temporal_change" in retrieval_reasons
    assert "decomposition_artifact_evidence" in retrieval_reasons
    assert "change_over_time_bridge" in retrieval_reasons
    assert plan.diagnostics()["query_decomposition_count"] > 0


def test_query_expansion_plan_uses_relative_time_decomposition() -> None:
    plan = build_query_expansion_plan("What did Alex say previous week?")

    retrieval_reasons = [item.reason for item in plan.retrieval_queries]
    assert "decomposition_relative_time" in retrieval_reasons


def test_best_query_relevance_uses_decomposed_artifact_query() -> None:
    plan = build_query_expansion_plan(
        "What changed after the call with Alex about Atlas and what was written in the screenshot?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Screenshot OCR detected text: Atlas launch deadline moved after "
            "the Alex call."
        ),
    )

    assert reason == "decomposition_artifact_evidence"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_event_sequence_decomposition() -> None:
    plan = build_query_expansion_plan("What did Alex decide after the Atlas call?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "After the Atlas call, Alex shared the next decision and follow up "
            "outcome in the meeting notes."
        ),
    )

    assert reason == "decomposition_event_sequence"
    assert relevance.distinctive_term_hits >= 5


def test_query_decomposition_adds_inference_support_query() -> None:
    plan = build_query_decomposition_plan("Would Melanie be considered an ally?")

    inference = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_inference_support"
    )

    assert inference.query.casefold().startswith("melanie ")
    assert "supporting evidence likely would considered" in inference.query
    assert "support supportive encouraging" in inference.query


def test_query_decomposition_keeps_salient_terms_for_inference_queries() -> None:
    plan = build_query_decomposition_plan(
        "Would Caroline pursue writing as a career option?"
    )

    inference = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_inference_support"
    )
    current_goal = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_current_preference_or_goal"
    )

    assert inference.query.casefold().startswith("caroline ")
    assert "writing" in inference.query.casefold()
    assert "supporting evidence likely would considered" in inference.query
    assert "current goal future plan" in current_goal.query


def test_query_decomposition_adds_attribute_aggregation_query() -> None:
    plan = build_query_decomposition_plan("What items has Melanie bought?")

    aggregation = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_attribute_aggregation"
    )

    assert aggregation.query.casefold().startswith("melanie ")
    assert "items" in aggregation.query.casefold()
    assert "bought purchased got new" in aggregation.query


def test_query_decomposition_keeps_existing_activity_bridge_unshadowed() -> None:
    plan = build_query_decomposition_plan("What activities does Melanie partake in?")

    assert "decomposition_attribute_aggregation" not in {
        item.reason for item in plan.decompositions
    }
    activity = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_activity_participation"
    )
    assert activity.query.casefold().startswith("melanie ")
    assert "painting swimming pottery camping" in activity.query
    assert "family kids" in activity.query


def test_query_decomposition_adds_current_goal_for_career_path_typo() -> None:
    plan = build_query_decomposition_plan(
        "What career path has Caroline decided to persue?"
    )

    current_goal = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_current_preference_or_goal"
    )

    assert "caroline" in current_goal.query.casefold()
    assert "current career path goal decided pursue" in current_goal.query
    assert "education options counseling counselor mental health" in current_goal.query


def test_query_decomposition_does_not_add_current_goal_noise_to_music_preference() -> None:
    plan = build_query_decomposition_plan(
        'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    )

    assert "decomposition_current_preference_or_goal" not in {
        item.reason for item in plan.decompositions
    }


def test_query_decomposition_adds_evidence_reason_query() -> None:
    plan = build_query_decomposition_plan(
        "Why would Project Atlas be considered blocked?"
    )

    reason = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_evidence_reason"
    )

    assert "project" in reason.query.casefold()
    assert "atlas" in reason.query.casefold()
    assert "reason evidence because observed" in reason.query
    assert "source citation quote explanation" in reason.query


def test_query_decomposition_adds_russian_evidence_reason_query() -> None:
    plan = build_query_decomposition_plan(
        "Почему Алекс считается владельцем проекта Атлас?"
    )

    reason = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_evidence_reason"
    )

    assert "алекс" in reason.query.casefold()
    assert "атлас" in reason.query.casefold()
    assert "reason evidence because observed" in reason.query


def test_query_decomposition_adds_identity_attribute_query() -> None:
    plan = build_query_decomposition_plan("What is Caroline's identity?")

    identity = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_identity_attribute"
    )

    assert identity.query.casefold().startswith("caroline ")
    assert "identity gender pronouns transgender" in identity.query
    assert "true self accepted belongs" in identity.query


def test_query_decomposition_adds_relationship_status_query() -> None:
    plan = build_query_decomposition_plan("What is Caroline's relationship status?")

    relationship = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_relationship_status"
    )

    assert relationship.query.casefold().startswith("caroline ")
    assert "relationship status single parent" in relationship.query
    assert "dating breakup friends family mentors" in relationship.query


def test_best_query_relevance_uses_identity_attribute_decomposition() -> None:
    plan = build_query_expansion_plan("What is Caroline's gender identity?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline shared her pronouns and said her true self felt accepted "
            "in the community support group."
        ),
    )

    assert reason == "decomposition_identity_attribute"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_relationship_status_decomposition() -> None:
    plan = build_query_expansion_plan("What is Caroline's dating status?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline mentioned dating after a breakup and leaning on friends, "
            "family, and mentors as her support system."
        ),
    )

    assert reason == "decomposition_relationship_status"
    assert relevance.distinctive_term_hits >= 5


def test_query_decomposition_adds_comparison_preference_query() -> None:
    plan = build_query_decomposition_plan(
        "Would Melanie be more interested in a national park or a theme park?"
    )

    comparison = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_comparison_preference"
    )

    assert comparison.query.casefold().startswith("melanie ")
    assert "comparison preference choice option" in comparison.query
    assert "more less rather prefer" in comparison.query


def test_best_query_relevance_uses_inference_support_decomposition() -> None:
    plan = build_query_expansion_plan("Would Melanie be considered an ally?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie is supportive, encouraging, and helps Caroline feel accepted.",
    )

    assert reason in {"ally_support_bridge", "decomposition_inference_support"}
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_evidence_reason_decomposition() -> None:
    plan = build_query_expansion_plan("Why would Project Atlas be considered blocked?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Project Atlas reason evidence showed the blocker because Alex "
            "observed a missing invoice owner in the source quote."
        ),
    )

    assert reason == "decomposition_evidence_reason"
    assert relevance.distinctive_term_hits >= 5
