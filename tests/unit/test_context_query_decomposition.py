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


def test_query_decomposition_keeps_compound_person_clauses_separate() -> None:
    plan = build_query_decomposition_plan(
        "What did Alex say about Atlas, and what did Maria decide?"
    )

    clause_queries = [
        item.query.casefold()
        for item in plan.decompositions
        if item.reason == "decomposition_clause"
    ]

    assert "what did alex say about atlas" in clause_queries
    assert "what did maria decide" in clause_queries
    assert not any(query.startswith("maria what did alex") for query in clause_queries)
    assert not any(query.startswith("alex and what did maria") for query in clause_queries)


def test_query_decomposition_does_not_split_compound_person_or_role_subjects() -> None:
    person_pair = build_query_decomposition_plan("What did Alex and Maria talk about?")
    role_pair = build_query_decomposition_plan(
        "How long have Mel and her husband been married?"
    )

    person_clauses = [
        item.query.casefold()
        for item in person_pair.decompositions
        if item.reason == "decomposition_clause"
    ]
    role_clauses = [
        item.query.casefold()
        for item in role_pair.decompositions
        if item.reason == "decomposition_clause"
    ]

    assert not any(query == "what did alex" for query in person_clauses)
    assert not any(query == "maria talk about" for query in person_clauses)
    assert "how long have mel" not in role_clauses
    assert "mel her husband been married" not in role_clauses


def test_query_decomposition_handles_russian_event_artifact_query() -> None:
    plan = build_query_decomposition_plan(
        "Что изменилось после созвона с алексом по Атласу и что было на скриншоте?"
    )

    queries = [item.query.casefold() for item in plan.decompositions]
    assert any("алекс" in query and "атлас" in query for query in queries)
    assert any("changed updated current previous" in query for query in queries)
    assert any("artifact file screenshot image video audio" in query for query in queries)


def test_query_decomposition_treats_attachments_as_artifacts() -> None:
    english = build_query_decomposition_plan("Find the Atlas attachment recording")
    russian = build_query_decomposition_plan("Найди вложение с записью по Атласу")

    assert "decomposition_artifact_evidence" in {item.reason for item in english.decompositions}
    assert "decomposition_artifact_evidence" in {item.reason for item in russian.decompositions}


def test_query_decomposition_adds_food_recipe_inventory_context() -> None:
    recipe_plan = build_query_decomposition_plan("What recipes has Riley made?")
    favorite_plan = build_query_decomposition_plan("What are Riley's favorite desserts?")

    recipe_inventory = next(
        item
        for item in recipe_plan.decompositions
        if item.reason == "decomposition_inventory_list"
    )
    favorite_inventory = next(
        item
        for item in favorite_plan.decompositions
        if item.reason == "decomposition_inventory_list"
    )

    assert "recipes recipe homemade made baked" in recipe_inventory.query
    assert "coconut milk dairy-free ice cream" in recipe_inventory.query
    assert "favorite desserts" in favorite_inventory.query
    assert "icecream" in favorite_inventory.query


def test_query_decomposition_adds_sport_activity_inventory_context() -> None:
    plan = build_query_decomposition_plan("What sports does John like besides basketball?")

    reasons = {item.reason for item in plan.decompositions}
    participation = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_activity_participation"
    )
    inventory = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_inventory_list"
    )

    assert "decomposition_activity_participation" in reasons
    assert "decomposition_inventory_list" in reasons
    assert "sports sport game team court scored surfing surfboard waves" in participation.query
    assert "position jersey jerseys season opener" in participation.query
    assert "basketball" in inventory.query


def test_query_decomposition_adds_collectible_object_context() -> None:
    plan = build_query_decomposition_plan(
        "What similar sports collectible do Tim and John own?"
    )

    collectible = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_collectible_object"
    )

    assert "collectible memorabilia keepsake" in collectible.query
    assert "signed autographed autograph" in collectible.query
    assert "reminder bond friendship appreciation" in collectible.query


def test_query_decomposition_expands_relative_time_queries() -> None:
    plan = build_query_decomposition_plan("What did Alex say two hours ago?")
    future_plan = build_query_decomposition_plan("What action items are due next week?")

    relative = next(
        item for item in plan.decompositions if item.reason == "decomposition_relative_time"
    )
    future_relative = next(
        item for item in future_plan.decompositions if item.reason == "decomposition_relative_time"
    )

    assert "alex" in relative.query.casefold()
    assert "hours_ago" in relative.query
    assert "transcript notes meeting call" in relative.query
    assert "next_week" in future_relative.query
    assert "decomposition_relative_time" in plan.diagnostics()["query_decomposition_reasons"]


def test_query_decomposition_adds_recency_for_relative_time_message_actions() -> None:
    told = build_query_decomposition_plan("What did Alex tell me an hour ago?")
    said = build_query_decomposition_plan("What did Alex say last week?")
    activity = build_query_decomposition_plan("What did Melanie do last week?")

    told_recency = next(
        item
        for item in told.decompositions
        if item.reason == "decomposition_conversation_recency"
    )
    said_recency = next(
        item
        for item in said.decompositions
        if item.reason == "decomposition_conversation_recency"
    )

    assert "alex" in told_recency.query.casefold()
    assert "hour ago" in told_recency.query
    assert "latest recent newest current conversation call" in told_recency.query
    assert "last week" in said_recency.query.casefold()
    assert "decomposition_conversation_recency" not in {
        item.reason for item in activity.decompositions
    }


def test_query_decomposition_covers_conversational_event_wording() -> None:
    english = build_query_decomposition_plan("What did Alex decide after the Atlas DM?")
    talk = build_query_decomposition_plan("Who did Alex talk to about Project Atlas?")
    meet = build_query_decomposition_plan("Who did Alex meet with about Atlas?")
    short_call = build_query_decomposition_plan("Who did Alex call?")
    topic = build_query_decomposition_plan("What did Alex and Maria talk about?")
    topic_discuss_with = build_query_decomposition_plan("What did Alex discuss with Maria?")
    topic_conversation_with = build_query_decomposition_plan(
        "What was the conversation with Maria about?"
    )
    topic_possessive_conversation = build_query_decomposition_plan(
        "What was Alex's conversation with Maria about?"
    )
    topic_discussed_in_call = build_query_decomposition_plan(
        "What was discussed during the Atlas call?"
    )
    russian = build_query_decomposition_plan(
        "Что Мария решила после переписки с Сергеем по Атласу?"
    )
    russian_talk = build_query_decomposition_plan("С кем Алекс говорил про Atlas?")
    russian_short_talk = build_query_decomposition_plan("С кем Алекс говорил?")
    russian_topic = build_query_decomposition_plan("О чем Алекс и Мария говорили?")
    russian_topic_discuss = build_query_decomposition_plan("Что Алекс и Мария обсуждали?")
    latest = build_query_decomposition_plan("What was my latest call with Alex about?")
    russian_latest = build_query_decomposition_plan("Что было на последнем созвоне с Алексом?")
    relative_recent = build_query_decomposition_plan(
        "What did I discuss with Alex two hours ago?"
    )
    russian_relative_recent = build_query_decomposition_plan(
        "Что я обсуждал с Алексом час назад?"
    )
    russian_message_recent = build_query_decomposition_plan("Что Алекс написал вчера?")

    english_context = next(
        item for item in english.decompositions if item.reason == "decomposition_event_context"
    )
    english_sequence = next(
        item for item in english.decompositions if item.reason == "decomposition_event_sequence"
    )
    talk_context = next(
        item for item in talk.decompositions if item.reason == "decomposition_event_context"
    )
    talk_counterparty = next(
        item
        for item in talk.decompositions
        if item.reason == "decomposition_conversation_counterparty"
    )
    meet_context = next(
        item for item in meet.decompositions if item.reason == "decomposition_event_context"
    )
    meet_counterparty = next(
        item
        for item in meet.decompositions
        if item.reason == "decomposition_conversation_counterparty"
    )
    short_call_counterparty = next(
        item
        for item in short_call.decompositions
        if item.reason == "decomposition_conversation_counterparty"
    )
    topic_context = next(
        item for item in topic.decompositions if item.reason == "decomposition_event_context"
    )
    topic_focus = next(
        item
        for item in topic.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    topic_discuss_with_focus = next(
        item
        for item in topic_discuss_with.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    topic_conversation_with_focus = next(
        item
        for item in topic_conversation_with.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    topic_possessive_conversation_focus = next(
        item
        for item in topic_possessive_conversation.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    topic_discussed_in_call_focus = next(
        item
        for item in topic_discussed_in_call.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    russian_context = next(
        item for item in russian.decompositions if item.reason == "decomposition_event_context"
    )
    russian_sequence = next(
        item for item in russian.decompositions if item.reason == "decomposition_event_sequence"
    )
    russian_talk_context = next(
        item
        for item in russian_talk.decompositions
        if item.reason == "decomposition_event_context"
    )
    russian_talk_counterparty = next(
        item
        for item in russian_talk.decompositions
        if item.reason == "decomposition_conversation_counterparty"
    )
    russian_short_talk_counterparty = next(
        item
        for item in russian_short_talk.decompositions
        if item.reason == "decomposition_conversation_counterparty"
    )
    russian_topic_focus = next(
        item
        for item in russian_topic.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    russian_topic_discuss_focus = next(
        item
        for item in russian_topic_discuss.decompositions
        if item.reason == "decomposition_conversation_topic"
    )
    latest_focus = next(
        item
        for item in latest.decompositions
        if item.reason == "decomposition_conversation_recency"
    )
    russian_latest_focus = next(
        item
        for item in russian_latest.decompositions
        if item.reason == "decomposition_conversation_recency"
    )
    relative_recent_focus = next(
        item
        for item in relative_recent.decompositions
        if item.reason == "decomposition_conversation_recency"
    )
    russian_relative_recent_focus = next(
        item
        for item in russian_relative_recent.decompositions
        if item.reason == "decomposition_conversation_recency"
    )
    russian_message_recent_focus = next(
        item
        for item in russian_message_recent.decompositions
        if item.reason == "decomposition_conversation_recency"
    )

    assert "chat message dm transcript" in english_context.query
    assert "meeting call chat message conversation event" in english_sequence.query
    assert "atlas" in english_sequence.query.casefold()
    assert "alex" in talk_context.query.casefold()
    assert "project" in talk_context.query.casefold()
    assert "atlas" in talk_context.query.casefold()
    assert "event conversation meeting call chat message" in talk_context.query
    assert "counterparty participant with to from talked spoke" in talk_counterparty.query
    assert "atlas" in meet_context.query.casefold()
    assert "counterparty participant with to from talked spoke" in meet_counterparty.query
    assert short_call_counterparty.query.casefold().startswith("alex ")
    assert "maria" in topic_context.query.casefold()
    assert "conversation topic subject about discussed" in topic_focus.query
    assert "conversation topic subject about discussed" in topic_discuss_with_focus.query
    assert "conversation topic subject about discussed" in topic_conversation_with_focus.query
    assert "conversation topic subject about discussed" in (
        topic_possessive_conversation_focus.query
    )
    assert "conversation topic subject about discussed" in topic_discussed_in_call_focus.query
    assert "сергеем" in russian_context.query.casefold()
    assert "атлас" in russian_context.query.casefold()
    assert "chat message dm transcript" in russian_context.query
    assert "сергеем" in russian_sequence.query.casefold()
    assert "атлас" in russian_sequence.query.casefold()
    assert "алекс" in russian_talk_context.query.casefold()
    assert "atlas" in russian_talk_context.query.casefold()
    assert "counterparty participant with to from talked spoke" in russian_talk_counterparty.query
    assert russian_short_talk_counterparty.query.casefold().startswith("алекс ")
    assert "conversation topic subject about discussed" in russian_topic_focus.query
    assert "conversation topic subject about discussed" in russian_topic_discuss_focus.query
    assert "latest recent newest current conversation call" in latest_focus.query
    assert "temporal event" in latest_focus.query
    assert "latest recent newest current conversation call" in russian_latest_focus.query
    assert "latest recent newest current conversation call" in relative_recent_focus.query
    assert "latest recent newest current conversation call" in (
        russian_relative_recent_focus.query
    )
    assert "алекс" in russian_message_recent_focus.query.casefold()
    assert "написал ответил сказал сообщил" in russian_message_recent_focus.query


def test_query_decomposition_covers_relocation_life_event_origin() -> None:
    english = build_query_decomposition_plan("Where did Caroline move from 4 years ago?")
    russian = build_query_decomposition_plan("Откуда Мария переехала четыре года назад?")

    english_context = next(
        item for item in english.decompositions if item.reason == "decomposition_relocation_context"
    )
    russian_context = next(
        item for item in russian.decompositions if item.reason == "decomposition_relocation_context"
    )

    assert english_context.query.casefold().startswith("caroline ")
    assert "from origin previous home country city" in english_context.query
    assert russian_context.query.casefold().startswith("мария ")
    assert "from origin previous home country city" in russian_context.query


def test_query_decomposition_does_not_add_origin_noise_for_relocation_destination() -> None:
    english = build_query_decomposition_plan("Where did Alex move to?")
    russian = build_query_decomposition_plan("Куда Мария переехала?")
    english_reasons = {item.reason for item in english.decompositions}
    russian_reasons = {item.reason for item in russian.decompositions}
    english_destination = next(
        item
        for item in english.decompositions
        if item.reason == "decomposition_relocation_destination"
    )
    russian_destination = next(
        item
        for item in russian.decompositions
        if item.reason == "decomposition_relocation_destination"
    )

    assert "decomposition_relocation_destination" in english_reasons
    assert "decomposition_relocation_destination" in russian_reasons
    assert "decomposition_relocation_context" not in english_reasons
    assert "decomposition_relocation_context" not in russian_reasons
    assert english_destination.query.casefold().startswith("alex ")
    assert "to destination new current home country city" in english_destination.query
    assert russian_destination.query.casefold().startswith("мария ")
    assert "to destination new current home country city" in russian_destination.query


def test_query_decomposition_does_not_treat_book_suggestion_from_as_relocation() -> None:
    plan = build_query_decomposition_plan("What book did Melanie read from Caroline's suggestion?")

    reasons = {item.reason for item in plan.decompositions}
    assert "decomposition_relocation_context" not in reasons
    assert "decomposition_clause" not in reasons


def test_query_decomposition_routes_travel_country_lists_as_inventory_not_relocation() -> None:
    english = build_query_decomposition_plan("What European countries has Maria been to?")
    russian = build_query_decomposition_plan("Какие страны Мария посещала?")

    english_reasons = {item.reason for item in english.decompositions}
    russian_reasons = {item.reason for item in russian.decompositions}
    english_inventory = next(
        item for item in english.decompositions if item.reason == "decomposition_inventory_list"
    )
    russian_inventory = next(
        item for item in russian.decompositions if item.reason == "decomposition_inventory_list"
    )

    assert "decomposition_relocation_context" not in english_reasons
    assert "decomposition_relocation_context" not in russian_reasons
    assert "country countries europe european england spain" in english_inventory.query
    assert "solo trip travel visited went" in english_inventory.query
    assert "мария" in russian_inventory.query.casefold()
    assert "country countries europe european england spain" in russian_inventory.query


def test_query_decomposition_adds_country_destination_context_for_meeting_questions() -> None:
    plan = build_query_decomposition_plan(
        "Which country do Calvin and Dave want to meet in?"
    )
    destination = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_country_destination"
    )

    assert "calvin" in destination.query
    assert "dave" in destination.query
    assert "country city destination place trip travel visit meet meeting" in (
        destination.query
    )
    assert "show around town flight upcoming plan" in destination.query


def test_query_decomposition_preserves_country_destination_month_year_anchor() -> None:
    plan = build_query_decomposition_plan(
        "Which country was Avery visiting in May 2023?"
    )
    destination = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_country_destination"
    )

    assert "avery" in destination.query
    assert "may 2023" in destination.query
    assert "country city destination place trip travel visit" in destination.query


def test_query_decomposition_adds_inventory_list_for_broad_list_slots() -> None:
    cases = [
        (
            "What areas of the U.S. has John been to or is planning to go to?",
            "place area country state city coast destination",
        ),
        (
            "What shelters does Maria volunteer at?",
            "volunteer volunteered volunteering shelter",
        ),
        (
            "What causes does John feel passionate about supporting?",
            "cause causes passionate support supporting",
        ),
        (
            "What types of pottery have Melanie and her kids made?",
            "type kind made finished created project",
        ),
    ]

    for query, expected_tail in cases:
        inventory = next(
            item
            for item in build_query_decomposition_plan(query).decompositions
            if item.reason == "decomposition_inventory_list"
        )

        assert expected_tail in inventory.query
        assert not inventory.query.endswith((" p", " pain"))


def test_query_decomposition_adds_inventory_for_where_place_lists_without_relocation() -> None:
    plan = build_query_decomposition_plan("Where has Maria made friends?")
    relocation = build_query_decomposition_plan("Where did Caroline move from 4 years ago?")

    reasons = {item.reason for item in plan.decompositions}
    inventory = next(
        item for item in plan.decompositions if item.reason == "decomposition_inventory_list"
    )

    assert "decomposition_inventory_list" in reasons
    assert "decomposition_relocation_context" not in reasons
    assert "place friends shelter church gym community welcoming people" in inventory.query
    assert "fellow volunteers joined made met" in inventory.query
    assert "decomposition_inventory_list" not in {
        item.reason for item in relocation.decompositions
    }


def test_query_decomposition_adds_people_inventory_for_who_met_helped_questions() -> None:
    english = build_query_decomposition_plan(
        "Who has Maria met and helped while volunteering?"
    )
    russian = build_query_decomposition_plan("Кому Мария помогала во время волонтерства?")
    recommendation = build_query_decomposition_plan(
        "Who did Caroline recommend Becoming Nicole to?"
    )

    english_inventory = next(
        item for item in english.decompositions if item.reason == "decomposition_inventory_list"
    )
    russian_inventory = next(
        item for item in russian.decompositions if item.reason == "decomposition_inventory_list"
    )

    assert "people person names met helped worked with friend customer" in (
        english_inventory.query
    )
    assert "people person names met helped worked with friend customer" in (
        russian_inventory.query
    )
    assert "decomposition_inventory_list" not in {
        item.reason for item in recommendation.decompositions
    }


def test_query_decomposition_keeps_social_support_out_of_people_inventory() -> None:
    english = build_query_decomposition_plan(
        "Who supports Caroline when she has a negative experience?"
    )
    direct = build_query_decomposition_plan("Who supports Caroline?")
    russian = build_query_decomposition_plan("Кто поддерживает Каролину?")
    technical = build_query_decomposition_plan("Who supports the OpenAI provider integration?")

    assert "decomposition_inventory_list" not in {
        item.reason for item in english.decompositions
    }
    assert "decomposition_inventory_list" not in {
        item.reason for item in direct.decompositions
    }
    assert "decomposition_inventory_list" not in {
        item.reason for item in russian.decompositions
    }
    assert "decomposition_inventory_list" in {
        item.reason for item in technical.decompositions
    }


def test_query_decomposition_adds_recommendation_source_query() -> None:
    source_plan = build_query_decomposition_plan(
        "What book did Melanie read from Caroline's suggestion?"
    )
    recipient_plan = build_query_decomposition_plan(
        "Who did Caroline recommend Becoming Nicole to?"
    )
    russian_plan = build_query_decomposition_plan(
        "По чьему совету Мария прочитала книгу?"
    )

    source = next(
        item
        for item in source_plan.decompositions
        if item.reason == "decomposition_recommendation_source"
    )
    recipient = next(
        item
        for item in recipient_plan.decompositions
        if item.reason == "decomposition_recommendation_source"
    )
    russian = next(
        item
        for item in russian_plan.decompositions
        if item.reason == "decomposition_recommendation_source"
    )

    assert "melanie" in source.query.casefold()
    assert "caroline" in source.query.casefold()
    assert "source actor recipient to from because of" in source.query
    assert "recommend it definitely would" in source.query
    assert "should get should start" in source.query
    assert "caroline" in recipient.query.casefold()
    assert "becoming" in recipient.query.casefold()
    assert "nicole" in recipient.query.casefold()
    assert "who whom whose" in recipient.query
    assert "мария" in russian.query.casefold()
    assert "прочитала" in russian.query.casefold()
    assert "recommendation suggestion advice" in russian.query


def test_query_decomposition_covers_activity_life_event_questions() -> None:
    plan = build_query_decomposition_plan("What LGBTQ+ events has Caroline participated in?")

    reasons = {item.reason for item in plan.decompositions}
    event_context = next(
        item for item in plan.decompositions if item.reason == "decomposition_event_context"
    )

    assert "decomposition_event_context" in reasons
    assert "decomposition_lgbtq_pride_event" in reasons
    assert "decomposition_lgbtq_support_group_event" in reasons
    assert "decomposition_lgbtq_school_speech_event" in reasons
    assert "decomposition_attribute_aggregation" in reasons
    assert event_context.query.casefold().startswith("caroline ")
    assert "event conversation meeting call chat message dm transcript" in event_context.query

    pride = next(
        item for item in plan.decompositions if item.reason == "decomposition_lgbtq_pride_event"
    )
    support = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_lgbtq_support_group_event"
    )
    school = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_lgbtq_school_speech_event"
    )
    assert "pride parade" in pride.query
    assert "support group" in support.query
    assert "school event speech" in school.query


def test_query_decomposition_adds_after_event_sequence_query() -> None:
    plan = build_query_decomposition_plan("What did Alex decide after the Atlas call?")

    sequence = next(
        item for item in plan.decompositions if item.reason == "decomposition_event_sequence"
    )

    assert "alex" in sequence.query.casefold()
    assert "atlas" in sequence.query.casefold()
    assert "after following later next timeline" in sequence.query
    assert "meeting call chat message conversation event" in sequence.query


def test_query_decomposition_adds_after_conversation_sequence_query() -> None:
    plan = build_query_decomposition_plan(
        "What did Alex decide after talking with Sam about Atlas?"
    )

    sequence = next(
        item for item in plan.decompositions if item.reason == "decomposition_event_sequence"
    )

    assert sequence.query.casefold().startswith("alex ")
    assert "sam" in sequence.query.casefold()
    assert "atlas" in sequence.query.casefold()
    assert "after following later next timeline" in sequence.query


def test_query_decomposition_treats_since_event_as_after_sequence() -> None:
    plan = build_query_decomposition_plan("What changed since the Atlas call?")

    sequence = next(
        item for item in plan.decompositions if item.reason == "decomposition_event_sequence"
    )

    assert "atlas" in sequence.query.casefold()
    assert "after following later next timeline" in sequence.query
    assert "meeting call chat message conversation event" in sequence.query


def test_query_decomposition_does_not_treat_generic_after_phrases_as_event_sequence() -> None:
    after_work = build_query_decomposition_plan("How does Melanie unwind after work?")
    after_gaming = build_query_decomposition_plan(
        "What alternative career might Nate consider after gaming?"
    )

    assert "decomposition_event_sequence" not in {
        item.reason for item in after_work.decompositions
    }
    assert "decomposition_event_sequence" not in {
        item.reason for item in after_gaming.decompositions
    }


def test_query_decomposition_adds_before_event_sequence_query() -> None:
    plan = build_query_decomposition_plan("What was Alex thinking before the review?")

    sequence = next(
        item for item in plan.decompositions if item.reason == "decomposition_event_sequence"
    )

    assert sequence.query.casefold().startswith("alex ")
    assert "before earlier prior previous timeline" in sequence.query
    assert "meeting call chat message conversation event" in sequence.query


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


def test_query_decomposition_treats_quote_and_provenance_as_source_evidence() -> None:
    quote_plan = build_query_decomposition_plan(
        "Show the quote supporting Project Atlas being blocked."
    )
    provenance_plan = build_query_decomposition_plan(
        "What provenance supports the Project Atlas blocker?"
    )

    quote_source = next(
        item
        for item in quote_plan.decompositions
        if item.reason == "decomposition_source_evidence"
    )
    provenance_source = next(
        item
        for item in provenance_plan.decompositions
        if item.reason == "decomposition_source_evidence"
    )

    assert "project" in quote_source.query.casefold()
    assert "atlas" in quote_source.query.casefold()
    assert "source citation evidence quote excerpt" in quote_source.query
    assert "reference provenance" in provenance_source.query


def test_best_query_relevance_uses_decomposed_artifact_query() -> None:
    plan = build_query_expansion_plan(
        "What changed after the call with Alex about Atlas and what was written in the screenshot?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=("Screenshot OCR detected text: Atlas launch deadline moved after the Alex call."),
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


def test_best_query_relevance_uses_quote_source_evidence_decomposition() -> None:
    plan = build_query_expansion_plan("Show the quote for Project Atlas source.")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Project Atlas source quote citation evidence excerpt reference "
            "provenance: Alex selected the provider."
        ),
    )

    assert reason == "decomposition_source_evidence"
    assert relevance.distinctive_term_hits >= 5


def test_query_decomposition_adds_inference_support_query() -> None:
    plan = build_query_decomposition_plan("Would Melanie be considered an ally?")

    inference = next(
        item for item in plan.decompositions if item.reason == "decomposition_inference_support"
    )

    assert inference.query.casefold().startswith("melanie ")
    assert "supporting evidence likely would considered" in inference.query
    assert "support supportive encouraging" in inference.query


def test_query_decomposition_adds_community_membership_evidence_query() -> None:
    plan = build_query_decomposition_plan(
        "Would Melanie be considered a member of the LGBTQ community?"
    )
    ally = build_query_decomposition_plan(
        "Would Melanie be considered an ally to the transgender community?"
    )

    membership = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_community_membership_evidence"
    )

    assert membership.query.casefold().startswith("melanie ")
    assert "self identification identify identified identifies" in membership.query
    assert "member part belong belongs belonging lgbtq queer community" in membership.query
    assert "decomposition_community_membership_evidence" not in {
        item.reason for item in ally.decompositions
    }


def test_query_decomposition_adds_ally_support_evidence_without_identity_noise() -> None:
    plan = build_query_decomposition_plan(
        "Would Melanie be considered an ally to the transgender community?"
    )

    ally = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_ally_support_evidence"
    )
    reasons = {item.reason for item in plan.decompositions}

    assert ally.query.casefold().startswith("melanie ")
    assert "ally allies supportive support acceptance encouraging" in ally.query
    assert "transition transgender trans lgbtq community" in ally.query
    assert "decomposition_identity_attribute" not in reasons
    assert "decomposition_inference_support" in reasons


def test_query_decomposition_adds_counterfactual_evidence_query() -> None:
    plan = build_query_decomposition_plan("Would Caroline support Alex joining the pride group?")

    counterfactual = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_counterfactual_evidence"
    )

    assert counterfactual.query.casefold().startswith("caroline ")
    assert "alex" in counterfactual.query.casefold()
    assert "counterfactual hypothetical would likely past behavior" in counterfactual.query
    assert "preference trait supporting evidence" in counterfactual.query


def test_query_decomposition_adds_support_role_fit_query() -> None:
    plan = build_query_decomposition_plan("Would Caroline be a good mentor for Alex?")

    support_role = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_support_role_fit"
    )

    assert support_role.query.casefold().startswith("caroline ")
    assert "alex" in support_role.query.casefold()
    assert "support role fit mentor mentoring guidance advice" in support_role.query
    assert "listened comfort empathy patient helped" in support_role.query


def test_query_decomposition_adds_absence_contrast_query() -> None:
    plan = build_query_decomposition_plan(
        "What pet did I mention named Luna instead of a hamster?"
    )

    contrast = next(
        item for item in plan.decompositions if item.reason == "decomposition_absence_contrast"
    )

    assert "luna" in contrast.query.casefold()
    assert "hamster" in contrast.query.casefold()
    assert "mentioned did not mention absent instead rather than" in contrast.query
    assert "pet cat dog hamster evidence" in contrast.query


def test_query_decomposition_keeps_salient_terms_for_inference_queries() -> None:
    plan = build_query_decomposition_plan("Would Caroline pursue writing as a career option?")

    inference = next(
        item for item in plan.decompositions if item.reason == "decomposition_inference_support"
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
    assert "career option counseling counselor mental health jobs" in current_goal.query
    assert "next steps figure out" in current_goal.query
    assert "decomposition_support_role_fit" not in {
        item.reason for item in plan.decompositions
    }


def test_query_decomposition_adds_support_role_for_helping_shelter_query() -> None:
    plan = build_query_decomposition_plan("Would Maria be good helping at the shelter?")

    support_role = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_support_role_fit"
    )

    assert support_role.query.casefold().startswith("maria ")
    assert "shelter" in support_role.query.casefold()
    assert "volunteer counseling counselor listened comfort empathy" in support_role.query


def test_query_decomposition_does_not_turn_considered_attribute_into_goal_noise() -> None:
    religious = build_query_decomposition_plan("Would Caroline be considered religious?")
    membership = build_query_decomposition_plan(
        "Would Melanie be considered a member of the LGBTQ community?"
    )

    for plan in (religious, membership):
        reasons = {item.reason for item in plan.decompositions}

        assert "decomposition_inference_support" in reasons
        assert "decomposition_current_preference_or_goal" not in reasons
        assert "decomposition_comparison_preference" not in reasons


def test_query_decomposition_adds_attribute_aggregation_query() -> None:
    plan = build_query_decomposition_plan("What items has Melanie bought?")

    aggregation = next(
        item for item in plan.decompositions if item.reason == "decomposition_attribute_aggregation"
    )

    assert aggregation.query.casefold().startswith("melanie ")
    assert "items" in aggregation.query.casefold()
    assert "bought purchased got new" in aggregation.query


def test_query_decomposition_adds_quantity_count_query() -> None:
    plan = build_query_decomposition_plan("How many concerts has Alex attended?")

    quantity = next(
        item for item in plan.decompositions if item.reason == "decomposition_quantity_count"
    )

    assert quantity.query.casefold().startswith("alex ")
    assert "concerts" in quantity.query.casefold()
    assert "count number total quantity" in quantity.query
    assert "once twice couple several multiple" in quantity.query


def test_query_decomposition_adds_temporal_answer_query() -> None:
    plan = build_query_decomposition_plan("When did I review the launch notes?")

    temporal = next(
        item for item in plan.decompositions if item.reason == "decomposition_temporal_answer"
    )

    assert "review" in temporal.query.casefold()
    assert "launch" in temporal.query.casefold()
    assert "when date day time session date weekday" in temporal.query


def test_query_decomposition_adds_knowledge_update_current_query() -> None:
    plan = build_query_decomposition_plan("What did I decide to use?")

    update = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_knowledge_update_current"
    )

    assert "current latest active final decided chose selected switched" in update.query
    assert "valid not stale superseded old" in update.query


def test_query_decomposition_adds_knowledge_update_current_query_for_current_state() -> None:
    english = build_query_decomposition_plan("What is the current Atlas provider?")
    english_valid = build_query_decomposition_plan("Which Atlas provider is still valid?")
    final_decision = build_query_decomposition_plan("What is the final Atlas decision?")
    source_of_truth = build_query_decomposition_plan(
        "What is the canonical source of truth for Atlas?"
    )
    chosen_provider = build_query_decomposition_plan("Which Atlas provider was chosen?")
    russian_provider = build_query_decomposition_plan("Какой сейчас провайдер у Atlas?")
    russian_final = build_query_decomposition_plan("Какое финальное решение по Atlas?")
    russian_model = build_query_decomposition_plan("Какая текущая модель Atlas?")

    plans = (
        english,
        english_valid,
        final_decision,
        source_of_truth,
        chosen_provider,
        russian_provider,
        russian_final,
        russian_model,
    )

    for plan in plans:
        update = next(
            item
            for item in plan.decompositions
            if item.reason == "decomposition_knowledge_update_current"
        )
        assert "current latest active final decided chose selected switched" in update.query
        assert "valid not stale superseded old" in update.query


def test_query_decomposition_adds_knowledge_update_previous_query() -> None:
    plan = build_query_decomposition_plan("Which Atlas provider is no longer valid?")

    previous = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_knowledge_update_previous"
    )

    assert "atlas" in previous.query.casefold()
    assert "previous old stale outdated superseded" in previous.query
    assert "no longer valid not current" in previous.query


def test_query_decomposition_adds_state_transition_query() -> None:
    switched = build_query_decomposition_plan("What did Atlas switch from LocalAI to?")
    replaced = build_query_decomposition_plan("Which provider replaced LocalAI for Atlas?")
    russian = build_query_decomposition_plan("Что заменило LocalAI в Атласе?")
    switch_setting = build_query_decomposition_plan("Which switch setting did Alex mention?")

    switched_transition = next(
        item
        for item in switched.decompositions
        if item.reason == "decomposition_state_transition"
    )
    replaced_transition = next(
        item
        for item in replaced.decompositions
        if item.reason == "decomposition_state_transition"
    )
    russian_transition = next(
        item for item in russian.decompositions if item.reason == "decomposition_state_transition"
    )

    assert "atlas" in switched_transition.query.casefold()
    assert "localai" in switched_transition.query.casefold()
    assert "state transition changed switched replaced" in switched_transition.query
    assert "previous old current new active final" in switched_transition.query
    assert "provider" in replaced_transition.query.casefold()
    assert "атласе" in russian_transition.query.casefold()
    assert "decomposition_state_transition" not in {
        item.reason for item in switch_setting.decompositions
    }


def test_query_decomposition_adds_commonality_query_for_two_people() -> None:
    plan = build_query_decomposition_plan(
        "What hobbies do Caroline and Melanie have in common?"
    )

    commonality = next(
        item for item in plan.decompositions if item.reason == "decomposition_commonality"
    )

    assert "caroline" in commonality.query.casefold()
    assert "melanie" in commonality.query.casefold()
    assert "common shared both mutual" in commonality.query
    assert "interests hobbies activities" in commonality.query


def test_query_decomposition_adds_russian_commonality_query_for_two_people() -> None:
    plan = build_query_decomposition_plan("Что Алиса и Мария обе любят?")

    commonality = next(
        item for item in plan.decompositions if item.reason == "decomposition_commonality"
    )

    assert "алиса" in commonality.query.casefold()
    assert "мария" in commonality.query.casefold()
    assert "common shared both mutual" in commonality.query


def test_query_decomposition_does_not_make_historical_decision_current() -> None:
    plan = build_query_decomposition_plan("What did Alex decide after the Atlas call?")

    assert "decomposition_knowledge_update_current" not in {
        item.reason for item in plan.decompositions
    }


def test_query_decomposition_does_not_make_general_choice_answer_current() -> None:
    plan = build_query_decomposition_plan("What did Morgan choose for the garden project?")

    assert "decomposition_knowledge_update_current" not in {
        item.reason for item in plan.decompositions
    }


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
    assert "painting swimming swim pottery class camping" in activity.query
    assert "family kids" in activity.query
    assert "fam weekend unplug hang" in activity.query


def test_query_decomposition_adds_current_goal_for_career_path_typo() -> None:
    plan = build_query_decomposition_plan("What career path has Caroline decided to persue?")

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
    plan = build_query_decomposition_plan("Why would Project Atlas be considered blocked?")

    reason = next(
        item for item in plan.decompositions if item.reason == "decomposition_evidence_reason"
    )

    assert "project" in reason.query.casefold()
    assert "atlas" in reason.query.casefold()
    assert "reason evidence because observed" in reason.query
    assert "source citation quote explanation" in reason.query


def test_query_decomposition_adds_emotion_cause_query_for_belonging_paraphrases() -> None:
    plan = build_query_decomposition_plan("What gave Caroline a sense of belonging?")
    russian = build_query_decomposition_plan("Как Каролина почувствовала себя принятой?")

    emotion = next(
        item for item in plan.decompositions if item.reason == "decomposition_emotion_cause"
    )
    russian_emotion = next(
        item
        for item in russian.decompositions
        if item.reason == "decomposition_emotion_cause"
    )

    assert emotion.query.casefold().startswith("caroline ")
    assert "sense" in emotion.query.casefold()
    assert "belonging at home community welcomed" in emotion.query
    assert "pride parade support group" in emotion.query
    assert russian_emotion.query.casefold().startswith("каролина ")
    assert "accepted acceptance belonged" in russian_emotion.query


def test_query_decomposition_adds_gotcha_failure_query() -> None:
    watch_out = build_query_decomposition_plan(
        "What should I watch out for in Atlas deployment?"
    )
    went_wrong = build_query_decomposition_plan("What went wrong with Atlas Docker?")
    russian = build_query_decomposition_plan("Какие подводные камни у Атласа?")
    issue_number = build_query_decomposition_plan("Which issue number did Alex mention?")

    watch_out_gotcha = next(
        item
        for item in watch_out.decompositions
        if item.reason == "decomposition_gotcha_failure"
    )
    went_wrong_gotcha = next(
        item
        for item in went_wrong.decompositions
        if item.reason == "decomposition_gotcha_failure"
    )
    russian_gotcha = next(
        item for item in russian.decompositions if item.reason == "decomposition_gotcha_failure"
    )

    assert "atlas" in watch_out_gotcha.query.casefold()
    assert "gotcha pitfall caveat known issue" in watch_out_gotcha.query
    assert "workaround root cause troubleshooting" in watch_out_gotcha.query
    assert "docker" in went_wrong_gotcha.query.casefold()
    assert "атласа" in russian_gotcha.query.casefold()
    assert "decomposition_gotcha_failure" not in {
        item.reason for item in issue_number.decompositions
    }


def test_query_decomposition_adds_russian_evidence_reason_query() -> None:
    plan = build_query_decomposition_plan("Почему Алекс считается владельцем проекта Атлас?")

    reason = next(
        item for item in plan.decompositions if item.reason == "decomposition_evidence_reason"
    )

    assert "алекс" in reason.query.casefold()
    assert "атлас" in reason.query.casefold()
    assert "reason evidence because observed" in reason.query


def test_query_decomposition_adds_identity_attribute_query() -> None:
    plan = build_query_decomposition_plan("What is Caroline's identity?")

    identity = next(
        item for item in plan.decompositions if item.reason == "decomposition_identity_attribute"
    )

    assert identity.query.casefold().startswith("caroline ")
    assert "identity gender pronouns transgender" in identity.query
    assert "true self accepted belongs" in identity.query


def test_query_decomposition_adds_relationship_status_query() -> None:
    plan = build_query_decomposition_plan("What is Caroline's relationship status?")
    russian = build_query_decomposition_plan("Алекс и Мария друзья?")
    russian_connected = build_query_decomposition_plan("Как Алекс связан с Марией?")
    friend_inventory = build_query_decomposition_plan("Где Мария нашла друзей?")

    relationship = next(
        item for item in plan.decompositions if item.reason == "decomposition_relationship_status"
    )
    russian_relationship = next(
        item
        for item in russian.decompositions
        if item.reason == "decomposition_relationship_status"
    )
    connected_relationship = next(
        item
        for item in russian_connected.decompositions
        if item.reason == "decomposition_relationship_status"
    )

    assert relationship.query.casefold().startswith("caroline ")
    assert "relationship status single parent" in relationship.query
    assert "partner spouse husband wife married dating" in relationship.query
    assert "not dating breakup divorced separated" in relationship.query
    assert "friends family kids children" not in relationship.query
    assert russian_relationship.query.casefold().startswith("алекс мария ")
    assert "отношения статус друзья дружба" in russian_relationship.query
    assert connected_relationship.query.casefold().startswith("алекс марией ")
    assert "отношения статус друзья дружба" in connected_relationship.query
    assert "decomposition_relationship_status" not in {
        item.reason for item in friend_inventory.decompositions
    }


def test_query_decomposition_adds_action_role_query() -> None:
    plan = build_query_decomposition_plan("What did Alex promise Maria after the Atlas call?")
    nominal_plan = build_query_decomposition_plan(
        "What decision did Caroline make after the interview?"
    )
    requested_recipient_plan = build_query_decomposition_plan(
        "Who did Caroline recommend Becoming Nicole to?"
    )
    recommended_that_plan = build_query_decomposition_plan(
        "Who recommended that Melanie read Becoming Nicole?"
    )
    recommend_object_plan = build_query_decomposition_plan(
        "What book did Caroline recommend Melanie read?"
    )
    direct_recipient_plan = build_query_decomposition_plan(
        "Who did Alex tell about the Atlas delay?"
    )
    direct_message_plan = build_query_decomposition_plan(
        "Who did Alex message about the Atlas delay?"
    )
    ask_to_task_plan = build_query_decomposition_plan(
        "Who did Alex ask to send the Atlas invoice?"
    )
    passive_actor_plan = build_query_decomposition_plan(
        "Who was told about the Atlas delay by Alex?"
    )
    introduce_plan = build_query_decomposition_plan("Who introduced Maria to Alex?")
    heard_from_plan = build_query_decomposition_plan(
        "Who did John hear inspiring stories from?"
    )
    help_plan = build_query_decomposition_plan(
        "Who helped Maria with the Atlas migration?"
    )

    action = next(
        item for item in plan.decompositions if item.reason == "decomposition_action_role"
    )
    followup = next(
        item for item in plan.decompositions if item.reason == "decomposition_followup_task"
    )
    nominal_action = next(
        item
        for item in nominal_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    requested_recipient_action = next(
        item
        for item in requested_recipient_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    recommended_that_action = next(
        item
        for item in recommended_that_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    recommended_that_source = next(
        item
        for item in recommended_that_plan.decompositions
        if item.reason == "decomposition_recommendation_source"
    )
    recommend_object_action = next(
        item
        for item in recommend_object_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    recommend_object_source = next(
        item
        for item in recommend_object_plan.decompositions
        if item.reason == "decomposition_recommendation_source"
    )
    direct_recipient_action = next(
        item
        for item in direct_recipient_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    direct_message_action = next(
        item
        for item in direct_message_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    ask_to_task_action = next(
        item
        for item in ask_to_task_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    passive_actor_action = next(
        item
        for item in passive_actor_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    introduce_action = next(
        item
        for item in introduce_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    heard_from_action = next(
        item
        for item in heard_from_plan.decompositions
        if item.reason == "decomposition_action_role"
    )
    help_action = next(
        item
        for item in help_plan.decompositions
        if item.reason == "decomposition_action_role"
    )

    assert "alex" in action.query.casefold()
    assert "maria" in action.query.casefold()
    assert "atlas" in action.query.casefold()
    assert "actor recipient speaker" in action.query
    assert "outcome commitment next step" in action.query
    assert "owner responsible assignee commitment" in followup.query
    assert "due date deadline" in followup.query
    assert "caroline" in nominal_action.query.casefold()
    assert "decision" in nominal_action.query.casefold()
    assert "caroline" in requested_recipient_action.query.casefold()
    assert "becoming" in requested_recipient_action.query.casefold()
    assert "actor recipient speaker" in requested_recipient_action.query
    assert "melanie" in recommended_that_action.query.casefold()
    assert "becoming" in recommended_that_action.query.casefold()
    assert "actor recipient speaker" in recommended_that_action.query
    assert "source actor recipient" in recommended_that_source.query
    assert "caroline" in recommend_object_action.query.casefold()
    assert "melanie" in recommend_object_action.query.casefold()
    assert "actor recipient speaker" in recommend_object_action.query
    assert "source actor recipient" in recommend_object_source.query
    assert "alex" in direct_recipient_action.query.casefold()
    assert "atlas" in direct_recipient_action.query.casefold()
    assert "actor recipient speaker" in direct_recipient_action.query
    assert "alex" in direct_message_action.query.casefold()
    assert "atlas" in direct_message_action.query.casefold()
    assert "actor recipient speaker" in direct_message_action.query
    assert "alex" in ask_to_task_action.query.casefold()
    assert "atlas" in ask_to_task_action.query.casefold()
    assert "invoice" in ask_to_task_action.query.casefold()
    assert "actor recipient speaker" in ask_to_task_action.query
    assert "alex" in passive_actor_action.query.casefold()
    assert "atlas" in passive_actor_action.query.casefold()
    assert "actor recipient speaker" in passive_actor_action.query
    assert "maria" in introduce_action.query.casefold()
    assert "alex" in introduce_action.query.casefold()
    assert "actor recipient speaker" in introduce_action.query
    assert "john" in heard_from_action.query.casefold()
    assert "stories" in heard_from_action.query.casefold()
    assert "actor recipient speaker" in heard_from_action.query
    assert "maria" in help_action.query.casefold()
    assert "atlas" in help_action.query.casefold()
    assert "actor recipient speaker" in help_action.query


def test_query_decomposition_adds_deadline_commitment_query() -> None:
    plan = build_query_decomposition_plan("When is the Atlas launch deadline after the call?")
    overdue_plan = build_query_decomposition_plan("Which Atlas tasks are overdue?")

    deadline = next(
        item for item in plan.decompositions if item.reason == "decomposition_deadline_commitment"
    )
    overdue = next(
        item
        for item in overdue_plan.decompositions
        if item.reason == "decomposition_deadline_commitment"
    )

    assert "atlas" in deadline.query.casefold()
    assert "deadline due date target date" in deadline.query
    assert "deliverable overdue upcoming commitment" in deadline.query
    assert "atlas" in overdue.query.casefold()
    assert "overdue upcoming commitment" in overdue.query


def test_query_decomposition_adds_followup_task_query() -> None:
    plan = build_query_decomposition_plan("What follow up tasks did Alex assign after Atlas?")
    owner_plan = build_query_decomposition_plan("Who is responsible for the Atlas invoice?")
    assigned_plan = build_query_decomposition_plan("Who is assigned to the Atlas invoice?")
    need_plan = build_query_decomposition_plan("What does Alex need to do after Atlas?")
    must_plan = build_query_decomposition_plan("What must Alex do after Atlas?")
    supposed_plan = build_query_decomposition_plan("What is Alex supposed to do after Atlas?")
    russian_need_plan = build_query_decomposition_plan("Что нужно сделать по Атласу?")

    followup = next(
        item for item in plan.decompositions if item.reason == "decomposition_followup_task"
    )
    owner_followup = next(
        item for item in owner_plan.decompositions if item.reason == "decomposition_followup_task"
    )
    assigned_followup = next(
        item
        for item in assigned_plan.decompositions
        if item.reason == "decomposition_followup_task"
    )
    need_followup = next(
        item for item in need_plan.decompositions if item.reason == "decomposition_followup_task"
    )
    must_followup = next(
        item for item in must_plan.decompositions if item.reason == "decomposition_followup_task"
    )
    supposed_followup = next(
        item
        for item in supposed_plan.decompositions
        if item.reason == "decomposition_followup_task"
    )
    russian_need_followup = next(
        item
        for item in russian_need_plan.decompositions
        if item.reason == "decomposition_followup_task"
    )

    assert "alex" in followup.query.casefold()
    assert "atlas" in followup.query.casefold()
    assert "action item task todo follow up next step" in followup.query
    assert "owner responsible assignee commitment" in followup.query
    assert "atlas" in owner_followup.query.casefold()
    assert "owner responsible assignee commitment" in owner_followup.query
    assert "atlas" in assigned_followup.query.casefold()
    assert "owner responsible assignee commitment" in assigned_followup.query
    assert "atlas" in need_followup.query.casefold()
    assert "owner responsible assignee commitment" in need_followup.query
    assert "atlas" in must_followup.query.casefold()
    assert "owner responsible assignee commitment" in must_followup.query
    assert "atlas" in supposed_followup.query.casefold()
    assert "owner responsible assignee commitment" in supposed_followup.query
    assert "атлас" in russian_need_followup.query.casefold()
    assert "owner responsible assignee commitment" in russian_need_followup.query


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
        item for item in plan.decompositions if item.reason == "decomposition_comparison_preference"
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


def test_best_query_relevance_uses_counterfactual_evidence_decomposition() -> None:
    plan = build_query_expansion_plan("Would Caroline support Alex joining the pride group?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline's past behavior shows she is supportive and encouraging. "
            "She mentioned pride groups, acceptance, and helping Alex feel welcome."
        ),
    )

    assert reason == "decomposition_counterfactual_evidence"
    assert relevance.distinctive_term_hits >= 3


def test_best_query_relevance_uses_absence_contrast_decomposition() -> None:
    plan = build_query_expansion_plan("What pet did I mention named Luna instead of a hamster?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="My cat Luna needs a new carrier.",
    )

    assert reason == "decomposition_absence_contrast"
    assert relevance.unique_term_hits >= 2


def test_best_query_relevance_uses_recommendation_source_decomposition() -> None:
    plan = build_query_expansion_plan("Who did Caroline recommend Becoming Nicole to?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline suggested the book Becoming Nicole to Melanie, and Melanie "
            "followed the recommendation after the conversation."
        ),
    )

    assert reason == "decomposition_recommendation_source"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_recommendation_advice_list_shapes() -> None:
    plan = build_query_expansion_plan("What recommendations has Joanna given to Nate?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D23:26 Joanna: Sure! For one, you should get a couch that can "
            "sit multiple people. Also invest in a weighted blanket and "
            "some dimmable lights."
        ),
    )

    assert reason == "decomposition_recommendation_source"
    assert relevance.distinctive_term_hits >= 3


def test_best_query_relevance_uses_conversation_counterparty_decomposition() -> None:
    plan = build_query_expansion_plan("Who did Alex talk to about Project Atlas?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Alex talked with Sam about Project Atlas rollout and the invoice "
            "approval plan."
        ),
    )

    assert reason == "decomposition_conversation_counterparty"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_conversation_topic_decomposition() -> None:
    plan = build_query_expansion_plan("What did Alex and Maria talk about?")
    discuss_with_plan = build_query_expansion_plan("What did Alex discuss with Maria?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Alex and Maria talked about Project Atlas, invoice approval, and "
            "the launch plan."
        ),
    )

    assert reason == "decomposition_conversation_topic"
    assert relevance.distinctive_term_hits >= 4

    _, discuss_reason, discuss_relevance = best_query_relevance(
        discuss_with_plan,
        text=(
            "Alex discussed Project Atlas, invoice approval, and the launch "
            "plan with Maria."
        ),
    )

    assert discuss_reason == "decomposition_conversation_topic"
    assert discuss_relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_quantity_count_decomposition() -> None:
    plan = build_query_expansion_plan("How many concerts has Alex attended?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="D8:4 Alex attended three concerts this year and went twice with Maria.",
    )

    assert reason == "decomposition_quantity_count"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_temporal_answer_decomposition() -> None:
    plan = build_query_expansion_plan("When did I review the launch notes?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "temporal_session date: 2023/05/30 (Tue) 18:00\n"
            "user: I reviewed the launch notes."
        ),
    )

    assert reason == "decomposition_temporal_answer"
    assert relevance.unique_term_hits >= 5


def test_best_query_relevance_uses_knowledge_update_current_decomposition() -> None:
    plan = build_query_expansion_plan("Which provider did I decide to use?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "I switched away from Pinecone. Qdrant is the current retrieval "
            "provider I selected."
        ),
    )

    assert reason in {
        "current_recommendation_bridge",
        "decomposition_knowledge_update_current",
    }
    assert relevance.unique_term_hits >= 5


def test_best_query_relevance_uses_current_state_knowledge_update_decomposition() -> None:
    plan = build_query_expansion_plan("What is the current Atlas provider?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Atlas selected provider remains valid, active, and current: OpenAI.",
    )

    assert reason in {
        "current_state_temporal_bridge",
        "decomposition_knowledge_update_current",
    }
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_final_decision_knowledge_update_decomposition() -> None:
    plan = build_query_expansion_plan("What is the final Atlas decision?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Atlas final source of truth: OpenAI is the selected active provider.",
    )

    assert reason in {
        "current_state_temporal_bridge",
        "decomposition_knowledge_update_current",
    }
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_knowledge_update_previous_decomposition() -> None:
    plan = build_query_expansion_plan("Which Atlas provider is no longer valid?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Atlas used LocalAI before, but it is no longer valid and was "
            "replaced by the current provider."
        ),
    )

    assert reason in {
        "decomposition_knowledge_update_previous",
        "stale_state_temporal_bridge",
    }
    assert relevance.unique_term_hits >= 5


def test_best_query_relevance_uses_commonality_decomposition() -> None:
    plan = build_query_expansion_plan("What hobbies do Caroline and Melanie have in common?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Caroline and Melanie share camping and painting as common hobbies "
            "they both enjoy."
        ),
    )

    assert reason in {
        "commonality_interest_bridge",
        "decomposition_commonality",
    }
    assert relevance.unique_term_hits >= 5


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


def test_best_query_relevance_uses_emotion_cause_decomposition_for_paraphrases() -> None:
    cases = (
        (
            "What gave Caroline a sense of belonging?",
            "The LGBTQ pride parade made Caroline feel at home in the community.",
        ),
        (
            "What made Caroline feel proud and powerful?",
            "Giving her school speech about her transgender journey was empowering.",
        ),
    )

    for query, text in cases:
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "decomposition_emotion_cause"
        assert relevance.distinctive_term_hits >= 3


def test_query_decomposition_adds_kind_type_descriptor_query() -> None:
    plan = build_query_decomposition_plan(
        "What type of venue did John and his girlfriend choose for their wedding ceremony?"
    )

    descriptor = next(
        item
        for item in plan.decompositions
        if item.reason == "decomposition_kind_type_descriptor"
    )

    assert descriptor.query.casefold().startswith("john ")
    assert "venue girlfriend choose wedding ceremony" in descriptor.query
    assert "kind type category genre style form format" in descriptor.query


def test_query_decomposition_does_not_treat_professional_acceptance_as_emotion() -> None:
    plan = build_query_decomposition_plan(
        "What kind of professional experience did Gina get accepted for on May 23, 2023?"
    )

    reasons = {item.reason for item in plan.decompositions}

    assert "decomposition_kind_type_descriptor" in reasons
    assert "decomposition_emotion_cause" not in reasons


def test_best_query_relevance_uses_kind_type_descriptor_decomposition() -> None:
    cases = (
        (
            "What type of training was the workshop Audrey signed up for in May 2023?",
            "Audrey signed up for obedience training at the workshop in May 2023.",
        ),
        (
            "What kind of flooring is Jon looking for in his dance studio?",
            "Jon is looking for sprung wood flooring in his dance studio.",
        ),
        (
            "What kind of online group did John join?",
            "John joined a service-focused online support group last week.",
        ),
    )

    for query, text in cases:
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "decomposition_kind_type_descriptor"
        assert relevance.distinctive_term_hits >= 4


def test_query_decomposition_adds_food_inventory_for_kind_type_food_questions() -> None:
    cases = (
        "What kind of food did Maria have on her dinner spread iwth her mother?",
        "What kind of meal did John and his family make together in the photo shared by John?",
        "What kind of frosting did Joanna use on the cake she made recently in May 2022?",
    )

    for query in cases:
        plan = build_query_decomposition_plan(query)
        inventory = next(
            item
            for item in plan.decompositions
            if item.reason == "decomposition_inventory_list"
        )

        assert "dinner spread plate meal food dish ingredients" in inventory.query
        assert "filling frosting cooked prepared" in inventory.query


def test_best_query_relevance_uses_food_inventory_for_food_descriptor_evidence() -> None:
    cases = (
        (
            "What kind of food did Maria have on her dinner spread iwth her mother?",
            "Maria had pasta, salad, and roasted vegetables on her dinner spread with her mother.",
        ),
        (
            "What kind of meal did John and his family make together in the photo shared by John?",
            "John and his family made homemade pizza together in the photo he shared.",
        ),
        (
            "What kind of frosting did Joanna use on the cake she made recently in May 2022?",
            "Joanna used cream cheese frosting on the cake she made in May 2022.",
        ),
    )

    for query, text in cases:
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "decomposition_inventory_list"
        assert relevance.distinctive_term_hits >= 4


def test_query_decomposition_adds_impact_and_content_topic_queries() -> None:
    impact = build_query_decomposition_plan(
        "What kind of impact does Joanna hope to have with her writing?"
    )
    content = build_query_decomposition_plan(
        "What kind of content did Joanna share that someone wrote her a letter about?"
    )

    impact_query = next(
        item for item in impact.decompositions if item.reason == "decomposition_impact_effect"
    )
    content_query = next(
        item
        for item in content.decompositions
        if item.reason == "decomposition_content_topic"
    )

    assert "impact effect affected influenced inspired" in impact_query.query
    assert "positive impact made a difference" in impact_query.query
    assert "content topic focus blog post article writing" in content_query.query
    assert "readers letter response inspired" in content_query.query


def test_best_query_relevance_uses_impact_and_content_topic_decompositions() -> None:
    cases = (
        (
            "What kind of impact does Joanna hope to have with her writing?",
            (
                "Joanna hopes her writing will inspire readers and have a "
                "positive impact on people."
            ),
            "decomposition_impact_effect",
        ),
        (
            "What kind of impact does Dave's blog on car mods have on people?",
            "Dave's car mods blog inspired people to start their own DIY projects.",
            "decomposition_impact_effect",
        ),
        (
            "What kind of content did Joanna share that someone wrote her a letter about?",
            (
                "Joanna shared a blog post about her screenplay writing, and "
                "someone wrote her a letter."
            ),
            "decomposition_content_topic",
        ),
    )

    for query, text, expected_reason in cases:
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == expected_reason
        assert relevance.distinctive_term_hits >= 4


def test_query_decomposition_adds_sport_team_attribute_query() -> None:
    cases = (
        "Which team did John sign with on 21 May, 2023?",
        "What position does John play on his basketball team?",
        (
            "What schools did John play basketball in and how many years was he "
            "with his team during high school?"
        ),
    )

    for query in cases:
        plan = build_query_decomposition_plan(query)
        sport_team = next(
            item
            for item in plan.decompositions
            if item.reason == "decomposition_sport_team_attribute"
        )

        assert "sports team basketball position jersey school high school" in sport_team.query
        assert "signed sign contract roster" in sport_team.query


def test_query_decomposition_avoids_broad_sport_team_attribute_query() -> None:
    cases = (
        "What happened to Melanie's son on their road trip?",
        "When did Gina team up with a local artist for some cool designs?",
        "What board games has Nate played?",
        "What instruments does Melanie play?",
    )

    for query in cases:
        plan = build_query_decomposition_plan(query)

        assert "decomposition_sport_team_attribute" not in {
            item.reason for item in plan.decompositions
        }


def test_best_query_relevance_uses_sport_team_attribute_decomposition() -> None:
    cases = (
        (
            "Which team did John sign with on 21 May, 2023?",
            "John signed with the Chicago Bulls basketball team on 21 May, 2023.",
        ),
        (
            "What position does John play on his basketball team?",
            "John plays point guard on his basketball team.",
        ),
        (
            (
                "What schools did John play basketball in and how many years was he "
                "with his team during high school?"
            ),
            (
                "John played basketball at Lincoln High and Central High for "
                "four years with his team."
            ),
        ),
    )

    for query, text in cases:
        plan = build_query_expansion_plan(query)

        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "decomposition_sport_team_attribute"
        assert relevance.distinctive_term_hits >= 5
