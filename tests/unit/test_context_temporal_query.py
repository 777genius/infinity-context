from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
    temporal_query_boost_signal,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_temporal_query_intent_detects_current_and_stale_exclusion() -> None:
    intent = build_temporal_query_intent(
        "Устаревшее не учитывать, что сейчас актуально по проекту Атлас?"
    )
    not_stale = build_temporal_query_intent("Only include memory that is not stale")
    not_deprecated = build_temporal_query_intent("Do not include deprecated Atlas notes")
    currently = build_temporal_query_intent("What is Alex doing currently?")
    right_now = build_temporal_query_intent("What is Alex working on right now?")
    at_the_moment = build_temporal_query_intent("What is the Atlas status at the moment?")
    russian_moment = build_temporal_query_intent("Что по Атласу на данный момент?")
    important_moment = build_temporal_query_intent("What was Alex's important moment?")

    assert intent.prefers_current is True
    assert intent.excludes_stale is True
    assert intent.include_superseded_review is False
    assert not_stale.excludes_stale is True
    assert not_stale.requests_previous is False
    assert not_stale.include_superseded_review is False
    assert not_deprecated.excludes_stale is True
    assert not_deprecated.requests_previous is False
    assert not_deprecated.include_superseded_review is False
    assert currently.prefers_current is True
    assert right_now.prefers_current is True
    assert at_the_moment.prefers_current is True
    assert russian_moment.prefers_current is True
    assert important_moment.prefers_current is False
    assert intent.diagnostics()["temporal_query_intent_reasons"] == [
        "prefers_current",
        "excludes_stale",
    ]


def test_temporal_query_intent_detects_latest_event_queries() -> None:
    english_latest = build_temporal_query_intent("What was the latest conversation with Alex?")
    english_first = build_temporal_query_intent("What was the first conversation with Alex?")
    english_recent = build_temporal_query_intent("What happened in the recent sync?")
    english_last_call = build_temporal_query_intent("What happened in the last call?")
    english_previous_session = build_temporal_query_intent(
        "What did Alex say in the previous session?"
    )
    english_next_meeting = build_temporal_query_intent("When is the next meeting?")
    russian_next_meeting = build_temporal_query_intent("Когда следующая встреча с Алексом?")
    russian_last_call = build_temporal_query_intent("Что было на последнем созвоне с Алексом?")
    russian_recent_meeting = build_temporal_query_intent(
        "Что обсуждали на недавней встрече с Алексом?"
    )
    russian_fresh_chat = build_temporal_query_intent("Что было в свежем чате по Атласу?")

    assert english_latest.prefers_current is True
    assert english_first.requests_earliest_event is True
    assert english_first.prefers_current is False
    assert english_first.requests_recent_event is False
    assert english_recent.prefers_current is True
    assert english_last_call.prefers_current is True
    assert english_previous_session.prefers_current is True
    assert english_next_meeting.prefers_current is False
    assert english_next_meeting.requests_upcoming is True
    assert russian_next_meeting.requests_upcoming is True
    assert english_previous_session.requests_previous is False
    assert russian_last_call.prefers_current is True
    assert russian_recent_meeting.prefers_current is True
    assert russian_fresh_chat.prefers_current is True
    assert russian_last_call.relative_time_hints == ()
    assert russian_recent_meeting.relative_time_hints == ()


def test_temporal_query_intent_detects_still_and_no_longer_update_language() -> None:
    still_valid = build_temporal_query_intent("Which Atlas provider is still valid?")
    still_recommended = build_temporal_query_intent("What option remains recommended?")
    no_longer_valid = build_temporal_query_intent("Which Atlas provider is no longer valid?")
    no_longer_use = build_temporal_query_intent("Which provider should I no longer use?")
    russian_current = build_temporal_query_intent("Какой провайдер все еще актуален?")
    russian_previous = build_temporal_query_intent("Какой провайдер больше не использовать?")

    assert still_valid.prefers_current is True
    assert still_valid.requests_previous is False
    assert still_recommended.prefers_current is True
    assert no_longer_valid.prefers_current is False
    assert no_longer_valid.requests_previous is True
    assert no_longer_valid.include_superseded_review is True
    assert no_longer_use.prefers_current is False
    assert no_longer_use.requests_previous is True
    assert russian_current.prefers_current is True
    assert russian_previous.requests_previous is True


def test_temporal_query_intent_detects_current_recommendation_queries() -> None:
    should_use = build_temporal_query_intent("Which provider should I use?")
    recommended = build_temporal_query_intent("What is the recommended provider?")
    decided = build_temporal_query_intent("Which provider did I decide to use?")
    generic_decision = build_temporal_query_intent("What did I decide to use?")
    final_decision = build_temporal_query_intent("What is the final Atlas decision?")
    source_of_truth = build_temporal_query_intent(
        "What is the canonical source of truth for Atlas?"
    )
    chosen_provider = build_temporal_query_intent("Which Atlas provider was chosen?")
    russian = build_temporal_query_intent("Какой провайдер лучше использовать?")
    russian_final = build_temporal_query_intent("Какое финальное решение по Атлас?")
    russian_selected = build_temporal_query_intent("Какой выбранный провайдер для Атлас?")
    book_recommendation = build_temporal_query_intent(
        "Who recommended Becoming Nicole to Melanie?"
    )
    historical_decision = build_temporal_query_intent("What did Alex decide after the Atlas call?")

    assert should_use.prefers_current is True
    assert recommended.prefers_current is True
    assert decided.prefers_current is True
    assert generic_decision.prefers_current is True
    assert final_decision.prefers_current is True
    assert source_of_truth.prefers_current is True
    assert chosen_provider.prefers_current is True
    assert russian.prefers_current is True
    assert russian_final.prefers_current is True
    assert russian_selected.prefers_current is True
    assert book_recommendation.prefers_current is False
    assert historical_decision.prefers_current is False


def test_temporal_query_intent_detects_change_and_previous_state() -> None:
    changed = build_temporal_query_intent("What changed after the meeting with Alex?")
    previous = build_temporal_query_intent("What was the previous Atlas plan before the call?")
    prior_plan = build_temporal_query_intent("What was the prior Atlas plan before the call?")
    old_plan = build_temporal_query_intent("What was the old Atlas plan?")
    stale = build_temporal_query_intent("Which memory is stale for Atlas?")
    outdated = build_temporal_query_intent("Which Atlas note is outdated?")
    obsolete = build_temporal_query_intent("Which Atlas note is obsolete?")
    deprecated = build_temporal_query_intent("Which Atlas policy is deprecated?")
    expired = build_temporal_query_intent("Which Atlas token is expired?")
    switched = build_temporal_query_intent("What did Atlas switch from LocalAI to?")
    replaced = build_temporal_query_intent("Which provider replaced LocalAI for Atlas?")
    russian_replaced = build_temporal_query_intent("Что заменило LocalAI в Атласе?")
    switch_setting = build_temporal_query_intent("Which switch setting did Alex mention?")
    age = build_temporal_query_intent("How old is Alex?")
    old_friend = build_temporal_query_intent("Who is Alex's old friend from school?")
    old_endpoint = build_temporal_query_intent("CONTEXT_SUPERSEDED_REVIEW_MARKER old endpoint")

    assert changed.requests_change is True
    assert changed.after_event is True
    assert changed.include_superseded_review is True
    assert previous.requests_previous is True
    assert previous.before_event is True
    assert previous.include_superseded_review is True
    assert prior_plan.requests_previous is True
    assert prior_plan.before_event is True
    assert prior_plan.include_superseded_review is True
    assert old_plan.requests_previous is True
    assert old_plan.include_superseded_review is True
    assert stale.requests_previous is True
    assert stale.include_superseded_review is True
    assert outdated.requests_previous is True
    assert outdated.include_superseded_review is True
    assert obsolete.requests_previous is True
    assert obsolete.include_superseded_review is True
    assert deprecated.requests_previous is True
    assert deprecated.include_superseded_review is True
    assert expired.requests_previous is True
    assert expired.include_superseded_review is True
    assert switched.requests_change is True
    assert switched.include_superseded_review is True
    assert replaced.requests_change is True
    assert replaced.include_superseded_review is True
    assert russian_replaced.requests_change is True
    assert russian_replaced.include_superseded_review is True
    assert switch_setting.requests_change is False
    assert switch_setting.include_superseded_review is False
    assert age.requests_previous is False
    assert age.include_superseded_review is False
    assert old_friend.requests_previous is False
    assert old_friend.include_superseded_review is False
    assert old_endpoint.requests_previous is False
    assert old_endpoint.include_superseded_review is False


def test_temporal_query_intent_detects_since_and_until_event_sequences() -> None:
    since_call = build_temporal_query_intent("What changed since the Atlas call?")
    since_last_week = build_temporal_query_intent("What changed since last week?")
    until_review = build_temporal_query_intent("What did Alex decide until the review?")
    until_last_week = build_temporal_query_intent("What did Alex decide until last week?")
    during_review = build_temporal_query_intent(
        "What did we decide during the Atlas review?"
    )
    russian_during_call = build_temporal_query_intent(
        "Что Алекс решил во время созвона по Атласу?"
    )
    russian_during_meeting = build_temporal_query_intent(
        "Что Алекс решил в ходе встречи по Атласу?"
    )
    after_roadtrip = build_temporal_query_intent("What happened after the roadtrip?")
    after_work = build_temporal_query_intent("How does Melanie unwind after work?")
    after_gaming = build_temporal_query_intent(
        "What alternative career might Nate consider after gaming?"
    )
    russian_since = build_temporal_query_intent("Что изменилось с момента созвона по Атласу?")
    russian_until = build_temporal_query_intent("Что было вплоть до ревью?")
    russian_after_work = build_temporal_query_intent("Как Мелани расслабляется после работы?")
    causal_since = build_temporal_query_intent("Since Alex is busy, what is current?")
    after_talking = build_temporal_query_intent(
        "What did Alex decide after talking with Sam about Atlas?"
    )
    after_speaking = build_temporal_query_intent(
        "What did Alex decide after speaking with Sam about Atlas?"
    )
    after_messaging = build_temporal_query_intent(
        "What did Alex decide after messaging Sam about Atlas?"
    )
    russian_after_talk = build_temporal_query_intent(
        "Что Алекс решил после разговора с Сергеем по Атласу?"
    )
    after_source_turn = build_temporal_query_intent("What did Riley mention after D12:4?")
    before_source_turn = build_temporal_query_intent(
        "What did Riley mention before source turn D12:4?"
    )
    after_source_ref = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    after_hyphenated_source_ref = build_temporal_query_intent(
        "What did Riley mention after source_turn_refs:D12-4?"
    )
    before_source_reference = build_temporal_query_intent(
        "What did Riley mention before source reference "
        "locomo:conv-1:session_12:D12:4:turn?"
    )

    assert since_call.after_event is True
    assert since_call.requests_change is True
    assert since_last_week.after_event is True
    assert since_last_week.relative_time_hints == ("last_week",)
    assert after_roadtrip.after_event is True
    assert after_work.after_event is False
    assert after_gaming.after_event is False
    assert russian_since.after_event is True
    assert russian_since.requests_change is True
    assert until_review.before_event is True
    assert during_review.during_event is True
    assert during_review.event_sequence_terms == ("atlas",)
    assert russian_during_call.during_event is True
    assert russian_during_call.event_sequence_terms == ("атласу",)
    assert russian_during_meeting.during_event is True
    assert russian_during_meeting.event_sequence_terms == ("атласу",)
    assert russian_until.before_event is True
    assert until_last_week.before_event is True
    assert until_last_week.relative_time_hints == ("last_week",)
    assert russian_after_work.after_event is False
    assert causal_since.after_event is False
    assert causal_since.before_event is False
    assert after_talking.after_event is True
    assert after_talking.event_sequence_terms == ("sam", "atlas")
    assert after_speaking.after_event is True
    assert after_speaking.event_sequence_terms == ("sam", "atlas")
    assert after_messaging.after_event is True
    assert after_messaging.event_sequence_terms == ("sam", "atlas")
    assert russian_after_talk.after_event is True
    assert russian_after_talk.event_sequence_terms == ("сергеем", "атласу")
    assert after_source_turn.after_event is True
    assert after_source_turn.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert before_source_turn.before_event is True
    assert before_source_turn.source_turn_sequence.before_turns[0].label() == "D12:4"
    assert after_source_ref.after_event is True
    assert after_source_ref.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert after_hyphenated_source_ref.after_event is True
    assert after_hyphenated_source_ref.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert before_source_reference.before_event is True
    assert before_source_reference.source_turn_sequence.before_turns[0].label() == "D12:4"


def test_temporal_query_intent_detects_relative_time_hints() -> None:
    last_week = build_temporal_query_intent("What did Alex say last week?")
    previous_week = build_temporal_query_intent("What did Alex say previous week?")
    prior_week = build_temporal_query_intent("What did Alex say prior week?")
    hours_ago = build_temporal_query_intent("What did Alex say 2 hours ago?")
    word_hours_ago = build_temporal_query_intent("What did Alex say two hours ago?")
    word_weeks_ago = build_temporal_query_intent("What did Alex say two weeks ago?")
    last_month = build_temporal_query_intent("What did Alex decide last month?")
    this_week = build_temporal_query_intent("What did Alex decide this week?")
    earlier_this_week = build_temporal_query_intent("What did Alex decide earlier this week?")
    tomorrow = build_temporal_query_intent("What is due tomorrow?")
    next_week = build_temporal_query_intent("What is due next week?")
    this_month = build_temporal_query_intent("What did Alex decide this month?")
    next_month = build_temporal_query_intent("What is due next month?")
    this_quarter = build_temporal_query_intent("What did Alex decide this quarter?")
    next_quarter = build_temporal_query_intent("What is due next quarter?")
    exact_date = build_temporal_query_intent("What is due on 2026-08-15?")
    local_exact_date = build_temporal_query_intent("Что нужно сделать 15.08.2026?")
    last_friday = build_temporal_query_intent("What happened last Friday?")
    last_night = build_temporal_query_intent("What did Alex say last night?")
    last_weekend = build_temporal_query_intent("What did Melanie do last weekend?")
    this_weekend = build_temporal_query_intent("What is Alex doing this weekend?")
    two_weekends_ago = build_temporal_query_intent("What did Melanie do two weekends ago?")
    word_months_ago = build_temporal_query_intent("What did Alex decide two months ago?")
    last_quarter = build_temporal_query_intent("What did Alex decide last quarter?")
    years_ago = build_temporal_query_intent("Where did Caroline move from 4 years ago?")
    this_year = build_temporal_query_intent("What changed for Atlas this year?")
    russian = build_temporal_query_intent("Что Алекс сказал на прошлой неделе?")
    russian_last_night = build_temporal_query_intent("Что Алекс сказал прошлой ночью?")
    russian_word_weeks = build_temporal_query_intent("Что Алекс сказал две недели назад?")
    russian_months = build_temporal_query_intent("Что Алекс решил два месяца назад?")
    russian_years = build_temporal_query_intent("Что Алекс решил четыре года назад?")
    russian_this_week = build_temporal_query_intent("Что Алекс решил на этой неделе?")
    russian_tomorrow = build_temporal_query_intent("Что нужно сделать завтра?")
    russian_next_week = build_temporal_query_intent("Что нужно сделать на следующей неделе?")
    russian_next_month = build_temporal_query_intent("Что нужно сделать в следующем месяце?")
    russian_this_quarter = build_temporal_query_intent("Что Алекс решил в этом квартале?")
    russian_next_year = build_temporal_query_intent("Что запланировано на следующий год?")
    russian_this_year = build_temporal_query_intent("Что изменилось в этом году?")

    assert last_week.relative_time_hints == ("last_week",)
    assert previous_week.relative_time_hints == ("last_week",)
    assert previous_week.requests_previous is False
    assert previous_week.include_superseded_review is False
    assert prior_week.relative_time_hints == ("last_week",)
    assert prior_week.requests_previous is False
    assert prior_week.include_superseded_review is False
    assert hours_ago.relative_time_hints == ("hours_ago",)
    assert word_hours_ago.relative_time_hints == ("hours_ago",)
    assert word_weeks_ago.relative_time_hints == ("weeks_ago",)
    assert last_month.relative_time_hints == ("last_month",)
    assert this_week.relative_time_hints == ("this_week",)
    assert earlier_this_week.relative_time_hints == ("this_week",)
    assert tomorrow.relative_time_hints == ("tomorrow",)
    assert next_week.relative_time_hints == ("next_week",)
    assert this_month.relative_time_hints == ("this_month",)
    assert next_month.relative_time_hints == ("next_month",)
    assert this_quarter.relative_time_hints == ("this_quarter",)
    assert next_quarter.relative_time_hints == ("next_quarter",)
    assert exact_date.relative_time_hints == ("date_2026_08_15",)
    assert local_exact_date.relative_time_hints == ("date_2026_08_15",)
    assert last_friday.relative_time_hints == ("last_friday",)
    assert last_night.relative_time_hints == ("last_night",)
    assert last_weekend.relative_time_hints == ("last_weekend",)
    assert this_weekend.relative_time_hints == ("this_weekend",)
    assert two_weekends_ago.relative_time_hints == ("weekends_ago",)
    assert word_months_ago.relative_time_hints == ("months_ago",)
    assert last_quarter.relative_time_hints == ("last_quarter",)
    assert years_ago.relative_time_hints == ("years_ago",)
    assert this_year.relative_time_hints == ("this_year",)
    assert russian.relative_time_hints == ("last_week",)
    assert russian_last_night.relative_time_hints == ("last_night",)
    assert russian_word_weeks.relative_time_hints == ("weeks_ago",)
    assert russian_months.relative_time_hints == ("months_ago",)
    assert russian_years.relative_time_hints == ("years_ago",)
    assert russian_this_week.relative_time_hints == ("this_week",)
    assert russian_tomorrow.relative_time_hints == ("tomorrow",)
    assert russian_next_week.relative_time_hints == ("next_week",)
    assert russian_next_month.relative_time_hints == ("next_month",)
    assert russian_this_quarter.relative_time_hints == ("this_quarter",)
    assert russian_next_year.relative_time_hints == ("next_year",)
    assert russian_this_year.relative_time_hints == ("this_year",)
    assert "relative_time_hint" in last_week.diagnostics()["temporal_query_intent_reasons"]
    assert last_week.diagnostics()["temporal_query_relative_time_hints"] == ["last_week"]


def test_temporal_query_intent_detects_broad_range_hints_and_date_boundaries() -> None:
    june = build_temporal_query_intent("What happened in June 2023?")
    summer = build_temporal_query_intent("Where was Jolene during summer 2022?")
    weekend = build_temporal_query_intent("What did Audrey do over the weekend?")
    before_date = build_temporal_query_intent("What did Audrey do before 4th October, 2023?")
    after_date = build_temporal_query_intent("What changed after 2023-10-04?")

    assert june.temporal_range_hints == ("month_2023_06", "month_06")
    assert summer.temporal_range_hints == ("season_2022_summer",)
    assert weekend.temporal_range_hints == ("weekend",)
    assert before_date.before_date == "2023-10-04"
    assert after_date.after_date == "2023-10-04"
    assert "temporal_range_hint" in june.diagnostics()["temporal_query_intent_reasons"]
    assert "before_date" in before_date.diagnostics()["temporal_query_intent_reasons"]


def test_temporal_query_boosts_active_replacement_for_change_query() -> None:
    intent = build_temporal_query_intent("What changed after the meeting?")
    active_replacement = _item(
        "active",
        score=0.8,
        retrieval_source="temporal_supersedes_relation",
        fact_status="active",
    )
    previous = _item(
        "previous",
        score=0.62,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
    )

    boosted = apply_temporal_query_intent_boosts(
        (active_replacement, previous),
        intent=intent,
    )

    assert boosted[0].score == 0.85
    assert boosted[0].diagnostics["score_signals"]["temporal_query_intent_boost"] == 0.05
    assert boosted[1].score == 0.655
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks what changed and item is previous state evidence"
    )


def test_temporal_query_boosts_previous_state_for_stale_query() -> None:
    intent = build_temporal_query_intent("Which memory is stale for Atlas?")
    current = _item(
        "current",
        score=0.8,
        retrieval_source="postgres_facts",
        fact_status="active",
    )
    stale = _item(
        "stale",
        score=0.78,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
    )

    boosted = apply_temporal_query_intent_boosts((current, stale), intent=intent)

    boosted_stale = next(item for item in boosted if item.item_id == "stale")
    boosted_current = next(item for item in boosted if item.item_id == "current")

    assert boosted_stale.score > boosted_current.score
    assert boosted_stale.score == 0.825
    assert boosted_stale.diagnostics["temporal_query_intent_reason"] == (
        "query asks for previous state evidence"
    )


def test_temporal_query_boosts_matching_event_temporal_hint() -> None:
    intent = build_temporal_query_intent("What did Alex say last week?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_week",
    )
    other = _item(
        "other",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="yesterday",
    )

    boosted = apply_temporal_query_intent_boosts((matched, other), intent=intent)

    assert boosted[0].score == 0.732
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time matches item event window"
    )
    assert boosted[1].score == 0.674
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query relative time conflicts with item event window"
    )


def test_temporal_query_boosts_matching_temporal_hint_alias() -> None:
    intent = build_temporal_query_intent("What did Alex say last week?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        temporal_hint_code="last_week",
    )

    boosted = apply_temporal_query_intent_boosts((matched,), intent=intent)

    assert boosted[0].score == 0.732
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time matches item event window"
    )


def test_temporal_query_boosts_matching_future_event_temporal_hint() -> None:
    intent = build_temporal_query_intent("What action items are due next week?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="next_week",
    )
    tomorrow = _item(
        "tomorrow",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="tomorrow",
    )

    boosted = apply_temporal_query_intent_boosts((matched, tomorrow), intent=intent)

    assert boosted[0].score == 0.732
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time matches item event window"
    )
    assert boosted[1].score == 0.694


def test_temporal_query_does_not_demote_exact_date_for_relative_future_query() -> None:
    intent = build_temporal_query_intent("What action items are due next week?")
    exact_date = _item(
        "exact_date",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="date_2026_08_15",
    )

    boosted = apply_temporal_query_intent_boosts((exact_date,), intent=intent)

    assert boosted[0].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[0].diagnostics


def test_temporal_query_boosts_upcoming_event_hints_without_date_terms() -> None:
    intent = build_temporal_query_intent("When is the next meeting with Alex?")
    upcoming = _item(
        "upcoming",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        event_temporal_hint_code="next_week",
    )
    previous = _item(
        "previous",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        event_temporal_hint_code="last_week",
    )
    undated = _item(
        "undated",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
    )

    boosted = apply_temporal_query_intent_boosts(
        (undated, previous, upcoming),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["upcoming"].score > by_id["undated"].score
    assert by_id["previous"].score < by_id["upcoming"].score
    assert by_id["upcoming"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for upcoming event and item has future event window"
    )
    assert by_id["previous"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for upcoming event and item has past event window"
    )


def test_temporal_query_boosts_matching_exact_date_event_temporal_hint() -> None:
    intent = build_temporal_query_intent("What action items are due on 15.08.2026?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="date_2026_08_15",
    )
    wrong_date = _item(
        "wrong_date",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="date_2026_08_16",
    )
    relative = _item(
        "relative",
        score=0.71,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="next_week",
    )

    boosted = apply_temporal_query_intent_boosts((matched, wrong_date, relative), intent=intent)

    assert boosted[0].score == 0.732
    assert boosted[1].score == 0.694
    assert boosted[2].score == 0.71
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time matches item event window"
    )
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query relative time conflicts with item event window"
    )
    assert "temporal_query_intent_reason" not in boosted[2].diagnostics


def test_temporal_query_treats_specific_weekday_as_contained_by_last_week() -> None:
    intent = build_temporal_query_intent("What happened last week?")
    friday = _item(
        "friday",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_friday",
    )
    weekend = _item(
        "weekend",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_weekend",
    )
    yesterday = _item(
        "yesterday",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="yesterday",
    )

    boosted = apply_temporal_query_intent_boosts(
        (friday, weekend, yesterday),
        intent=intent,
    )

    assert boosted[0].score == 0.718
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time contains item event window"
    )
    assert boosted[1].score == 0.718
    assert boosted[2].score == 0.694


def test_temporal_query_does_not_penalize_broader_week_for_specific_weekday_query() -> None:
    intent = build_temporal_query_intent("What happened last Friday?")
    friday = _item(
        "friday",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_friday",
    )
    week = _item(
        "week",
        score=0.71,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_week",
    )
    yesterday = _item(
        "yesterday",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="yesterday",
    )

    boosted = apply_temporal_query_intent_boosts((friday, week, yesterday), intent=intent)

    assert boosted[0].score == 0.732
    assert boosted[1].score == 0.71
    assert boosted[2].score == 0.694
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_treats_recent_windows_as_contained_by_current_periods() -> None:
    week_intent = build_temporal_query_intent("What happened this week?")
    month_intent = build_temporal_query_intent("What happened this month?")
    quarter_intent = build_temporal_query_intent("What happened this quarter?")
    year_intent = build_temporal_query_intent("What happened this year?")
    today = _item(
        "today",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="today",
    )
    hours_ago = _item(
        "hours_ago",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="hours_ago",
    )
    yesterday = _item(
        "yesterday",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="yesterday",
    )
    last_night = _item(
        "last_night",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_night",
    )
    this_week = _item(
        "this_week",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="this_week",
    )
    this_month = _item(
        "this_month",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="this_month",
    )
    last_week = _item(
        "last_week",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_week",
    )
    last_year = _item(
        "last_year",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_year",
    )

    week_boosted = apply_temporal_query_intent_boosts(
        (yesterday, last_night),
        intent=week_intent,
    )
    month_boosted = apply_temporal_query_intent_boosts(
        (today, hours_ago, this_week),
        intent=month_intent,
    )
    quarter_boosted = apply_temporal_query_intent_boosts(
        (this_month,),
        intent=quarter_intent,
    )
    year_boosted = apply_temporal_query_intent_boosts(
        (last_week, last_year),
        intent=year_intent,
    )

    assert week_boosted[0].score == 0.718
    assert week_boosted[1].score == 0.718
    assert month_boosted[0].score == 0.718
    assert month_boosted[1].score == 0.718
    assert month_boosted[2].score == 0.718
    assert quarter_boosted[0].score == 0.718
    assert year_boosted[0].score == 0.718
    assert year_boosted[1].score == 0.694
    assert month_boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query relative time contains item event window"
    )


def test_temporal_query_demotes_conflicting_event_temporal_hint() -> None:
    intent = build_temporal_query_intent("What did Alex say last week?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="last_week",
    )
    conflicting = _item(
        "conflicting",
        score=0.75,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_temporal_hint_code="yesterday",
    )
    unbounded = _item(
        "unbounded",
        score=0.71,
        retrieval_source="canonical_anchors",
        fact_status="active",
    )

    boosted = apply_temporal_query_intent_boosts(
        (matched, conflicting, unbounded),
        intent=intent,
    )

    assert boosted[0].score == 0.732
    assert boosted[1].score == 0.724
    assert boosted[2].score == 0.71
    assert boosted[0].score > boosted[1].score
    assert boosted[1].diagnostics["score_signals"]["temporal_query_intent_boost"] == -0.026
    assert "temporal_query_intent_reason" not in boosted[2].diagnostics


def test_temporal_query_range_evidence_beats_generic_temporal_mentions() -> None:
    intent = build_temporal_query_intent("What happened in June 2023?")
    specific = _item(
        "specific",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D4:2 In June 2023, Alex moved the Atlas launch review to Friday.",
    )
    generic = _item(
        "generic",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D5:2 Alex mentioned summer plans and a launch review.",
    )

    boosted = apply_temporal_query_intent_boosts((generic, specific), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["specific"].score > by_id["generic"].score
    assert by_id["specific"].diagnostics["temporal_query_intent_reason"] == (
        "query temporal range matches item text"
    )
    assert "temporal_query_intent_reason" not in by_id["generic"].diagnostics


def test_temporal_query_uses_metadata_date_for_season_range() -> None:
    intent = build_temporal_query_intent("Where was Jolene during summer 2022?")
    specific = _item(
        "specific",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        event_valid_from="2022-07-15",
        text="Jolene was in Portugal for the internship.",
    )
    generic = _item(
        "generic",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Jolene talked about summer travel in general.",
    )

    boosted = apply_temporal_query_intent_boosts((generic, specific), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["specific"].score > by_id["generic"].score
    assert by_id["specific"].diagnostics["temporal_query_intent_reason"] == (
        "query temporal range contains item metadata date"
    )


def test_temporal_query_uses_before_date_boundary_evidence() -> None:
    intent = build_temporal_query_intent(
        "What did Audrey do over the weekend before 4th October, 2023?"
    )
    specific = _item(
        "specific",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Over the weekend before 4th October, 2023, Audrey visited the gallery.",
    )
    generic = _item(
        "generic",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Audrey talked about weekend plans near the gallery.",
    )

    boosted = apply_temporal_query_intent_boosts((generic, specific), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["specific"].score > by_id["generic"].score
    assert by_id["specific"].diagnostics["temporal_query_intent_reason"] == (
        "query asks before date and item text matches boundary"
    )


def test_temporal_query_boosts_matching_after_event_direction() -> None:
    intent = build_temporal_query_intent("What did Alex decide after the Atlas call?")
    after_item = _item(
        "after",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="After the Atlas call, Alex decided to wait for invoice approval.",
    )
    before_item = _item(
        "before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Before the Atlas call, Alex was still considering launch options.",
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score > after_item.score
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item conflicts with direction"
    )


def test_temporal_query_prefers_ordered_afterward_evidence_over_unordered_mentions() -> None:
    intent = build_temporal_query_intent(
        "What did Jordan realize after the neighborhood event?"
    )
    ordered = _item(
        "ordered",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text=(
            "Jordan finished the neighborhood event. Afterward, he realized he "
            "missed training with the team."
        ),
    )
    unordered = _item(
        "unordered",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text=(
            "Jordan mentioned the neighborhood event and also realized he missed "
            "training with the team."
        ),
    )

    boosted = apply_temporal_query_intent_boosts((unordered, ordered), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.after_event is True
    assert intent.event_sequence_terms == ("neighborhood",)
    assert by_id["ordered"].score > by_id["unordered"].score
    assert by_id["ordered"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert by_id["unordered"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item only matches the event boundary"
    )


def test_temporal_query_does_not_stitch_unrelated_after_marker_to_event_mentions() -> None:
    intent = build_temporal_query_intent("What did Alex decide after the Atlas call?")
    ordered = _item(
        "ordered",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="After the Atlas call, Alex decided to wait for invoice approval.",
    )
    unrelated_after = _item(
        "unrelated_after",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text=(
            "After dinner, Alex discussed the Atlas call and decided to wait "
            "for invoice approval."
        ),
    )

    boosted = apply_temporal_query_intent_boosts((unrelated_after, ordered), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert by_id["ordered"].score > by_id["unrelated_after"].score
    assert by_id["ordered"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert by_id["unrelated_after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item only matches the event boundary"
    )


def test_temporal_query_requires_same_event_identity_for_direction_boost() -> None:
    intent = build_temporal_query_intent("What did Alex decide after the Atlas call?")
    atlas = _item(
        "atlas",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="After the Atlas call, Alex decided to wait for invoice approval.",
    )
    stripe = _item(
        "stripe",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="After the Stripe call, Alex decided to change billing retries.",
    )

    boosted = apply_temporal_query_intent_boosts((atlas, stripe), intent=intent)

    assert intent.event_sequence_terms == ("atlas",)
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics
    assert boosted[0].score == 0.726
    assert boosted[1].score == 0.72


def test_temporal_query_boosts_matching_during_event_context() -> None:
    intent = build_temporal_query_intent("What did Alex decide during the Atlas call?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="During the Atlas call, Alex decided to wait for invoice approval.",
    )
    distractor = _item(
        "distractor",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="During the Stripe call, Alex changed billing retries.",
    )

    boosted = apply_temporal_query_intent_boosts((matched, distractor), intent=intent)

    assert intent.during_event is True
    assert intent.event_sequence_terms == ("atlas",)
    assert boosted[0].score == 0.724
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for during-event context and item matches event"
    )
    assert boosted[1].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_boosts_matching_russian_during_event_context() -> None:
    intent = build_temporal_query_intent("Что Алекс решил во время созвона по Атласу?")
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Во время созвона по Атласу Алекс выбрал план запуска.",
    )
    distractor = _item(
        "distractor",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="После созвона по Атласу Алекс написал заметку.",
    )

    boosted = apply_temporal_query_intent_boosts((matched, distractor), intent=intent)

    assert intent.during_event is True
    assert intent.event_sequence_terms == ("атласу",)
    assert boosted[0].score == 0.724
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for during-event context and item matches event"
    )
    assert boosted[1].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_only_conflicts_same_event_identity() -> None:
    intent = build_temporal_query_intent("What did Alex decide after the Atlas call?")
    atlas_before = _item(
        "atlas_before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Before the Atlas call, Alex was still considering launch options.",
    )
    stripe_before = _item(
        "stripe_before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Before the Stripe call, Alex was still considering billing options.",
    )

    boosted = apply_temporal_query_intent_boosts((atlas_before, stripe_before), intent=intent)

    assert boosted[0].score == 0.696
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item conflicts with direction"
    )
    assert boosted[1].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_boosts_matching_since_event_direction() -> None:
    intent = build_temporal_query_intent("What changed since the Atlas call?")
    after_item = _item(
        "after",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Since the Atlas call, Alex changed the invoice approval plan.",
    )
    before_item = _item(
        "before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Before the Atlas call, Alex was still considering launch options.",
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score > after_item.score
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )


def test_temporal_query_prefers_since_evidence_over_boundary_window() -> None:
    intent = build_temporal_query_intent("What changed since last week?")
    since_item = _item(
        "since",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="Since last week, Atlas uses OpenAI for extraction.",
    )
    boundary_stale = _item(
        "boundary_stale",
        score=0.72,
        retrieval_source="superseded_review",
        fact_status="superseded",
        event_temporal_hint_code="last_week",
        text="Last week, Atlas still used LocalAI for extraction.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (boundary_stale, since_item),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert by_id["since"].score > by_id["boundary_stale"].score
    assert by_id["since"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert by_id["boundary_stale"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item only matches the boundary window"
    )


def test_temporal_query_matches_conversational_after_event_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Alex decide after talking with Sam about Atlas?"
    )
    matched = _item(
        "matched",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text=(
            "After talking with Sam about Atlas, Alex decided to wait for "
            "invoice approval."
        ),
    )
    distractor = _item(
        "distractor",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text=(
            "After talking with Priya about Stripe, Alex changed billing retries."
        ),
    )

    boosted = apply_temporal_query_intent_boosts((matched, distractor), intent=intent)

    assert intent.event_sequence_terms == ("sam", "atlas")
    assert boosted[0].score == 0.726
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert boosted[1].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_matches_russian_event_identity_for_direction_boost() -> None:
    intent = build_temporal_query_intent("Что Алекс решил после созвона по Атласу?")
    atlas = _item(
        "atlas",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="После созвона по Атласу Алекс выбрал новый план.",
    )
    beta = _item(
        "beta",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="После созвона по Бете Алекс изменил таймлайн.",
    )

    boosted = apply_temporal_query_intent_boosts((atlas, beta), intent=intent)

    assert intent.event_sequence_terms == ("атласу",)
    assert boosted[0].score == 0.726
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after-event sequence and item matches direction"
    )
    assert boosted[1].score == 0.72
    assert "temporal_query_intent_reason" not in boosted[1].diagnostics


def test_temporal_query_boosts_matching_russian_before_event_direction() -> None:
    intent = build_temporal_query_intent("Что Алекс думал до ревью?")
    before_item = _item(
        "before",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="До ревью Алекс хотел оставить старый план.",
    )
    after_item = _item(
        "after",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="После ревью Алекс выбрал новый план.",
    )

    boosted = apply_temporal_query_intent_boosts((before_item, after_item), intent=intent)

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before-event sequence and item matches direction"
    )
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before-event sequence and item conflicts with direction"
    )


def test_temporal_query_boosts_source_turn_after_boundary_order() -> None:
    intent = build_temporal_query_intent("What did Riley mention after D12:4?")
    after_item = _item(
        "after",
        score=0.7,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:5 Riley said the studio visit was confirmed.",
    )
    before_item = _item(
        "before",
        score=0.72,
        retrieval_source="canonical_anchors",
        fact_status="active",
        text="D12:3 Riley was still waiting on Morgan.",
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert boosted[1].score == 0.694
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn precedes boundary"
    )


def test_temporal_query_uses_source_refs_for_source_turn_before_boundary_order() -> None:
    intent = build_temporal_query_intent("What did Riley mention before D12:4?")
    before_item = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:3:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    after_item = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts((before_item, after_item), intent=intent)

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before source turn and item source turn precedes boundary"
    )
    assert boosted[1].score == 0.694
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before source turn and item source turn follows boundary"
    )


def test_temporal_query_boosts_full_source_ref_boundary_order() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after source ref locomo:conv-1:session_12:D12:4:turn?"
    )
    after_item = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:5:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    before_item = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="locomo:conv-1:session_12:D12:3:turn",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts((after_item, before_item), intent=intent)

    assert boosted[0].score == 0.74
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert boosted[1].score == 0.694
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn precedes boundary"
    )


def test_temporal_query_boosts_explicit_session_bridge_match() -> None:
    intent = build_temporal_query_intent("What did Alex decide in session 4?")
    matched = _item(
        "locomo:conv-1:session_4:D4:7:turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_4 turn D4:7 Alex decided to wait for invoice approval.",
    )
    different_session = _item(
        "locomo:conv-1:session_3:D3:7:turn",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_3 turn D3:7 Alex was still evaluating invoice options.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (4,)
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score == 0.734
    assert by_id["locomo:conv-1:session_3:D3:7:turn"].score == 0.702
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score > by_id[
        "locomo:conv-1:session_3:D3:7:turn"
    ].score
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item matches it"
    assert by_id["locomo:conv-1:session_3:D3:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item has a different session"


def test_temporal_query_extracts_dialogue_turn_session_hint() -> None:
    intent = build_temporal_query_intent("What did Riley mention around D12:4?")
    matched = _item(
        "turn_match",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D12:4 Riley mentioned the studio visit with Morgan.",
    )
    different_session = _item(
        "turn_decoy",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="D11:4 Riley mentioned the volunteer shift.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (12,)
    assert by_id["turn_match"].score > by_id["turn_decoy"].score
    assert by_id["turn_match"].diagnostics["score_signals"][
        "temporal_query_intent_boost"
    ] == 0.04


def test_temporal_query_boosts_written_ordinal_session_match() -> None:
    intent = build_temporal_query_intent("What did Alex decide in the fourth session?")
    matched = _item(
        "locomo:conv-1:session_4:D4:7:turn",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_4 turn D4:7 Alex decided to wait for invoice approval.",
    )
    different_session = _item(
        "locomo:conv-1:session_3:D3:7:turn",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="session_3 turn D3:7 Alex was still evaluating invoice options.",
    )

    boosted = apply_temporal_query_intent_boosts(
        (different_session, matched),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.session_ordinals == (4,)
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].score > by_id[
        "locomo:conv-1:session_3:D3:7:turn"
    ].score
    assert by_id["locomo:conv-1:session_4:D4:7:turn"].diagnostics[
        "temporal_query_intent_reason"
    ] == "query asks for an explicit session and item matches it"


def test_temporal_query_extracts_cardinal_word_after_session() -> None:
    intent = build_temporal_query_intent("What did Riley mention in session twelve?")

    assert intent.session_ordinals == (12,)


def test_temporal_query_does_not_treat_event_ordinals_as_session_ordinals() -> None:
    intent = build_temporal_query_intent("What was the first conversation with Sam?")

    assert intent.requests_earliest_event is True
    assert intent.session_ordinals == ()


def test_temporal_query_demotes_stale_when_query_excludes_stale() -> None:
    intent = build_temporal_query_intent("ignore stale notes, what is current?")
    current = _item(
        "current",
        score=0.8,
        retrieval_source="postgres_facts",
        fact_status="active",
    )
    stale = _item(
        "stale",
        score=0.62,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
    )

    boosted = apply_temporal_query_intent_boosts((current, stale), intent=intent)

    assert boosted[0].score == 0.818
    assert boosted[1].score == 0.5
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == ("query excludes stale memory")


def test_temporal_query_boost_signal_exposes_reusable_reason_code() -> None:
    intent = build_temporal_query_intent("Which Atlas provider is no longer valid?")
    stale = _item(
        "stale",
        score=0.62,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
    )

    signal = temporal_query_boost_signal(stale, intent=intent)

    assert signal.boost == 0.045
    assert signal.reason == "query asks for previous state evidence"
    assert signal.code == "previous_state_evidence"


def test_temporal_query_uses_plain_text_stale_state_without_metadata() -> None:
    intent = build_temporal_query_intent("Which Atlas provider is no longer valid?")
    active = _item(
        "active_provider",
        score=0.72,
        retrieval_source="postgres_facts",
        fact_status="active",
        text="Atlas provider remains valid and active: OpenAI.",
    )
    stale_text = _item(
        "stale_text_provider",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="",
        text="LocalAI is no longer valid for Atlas after the provider switch.",
    )

    boosted = apply_temporal_query_intent_boosts((active, stale_text), intent=intent)
    boosted_stale = next(item for item in boosted if item.item_id == "stale_text_provider")
    boosted_active = next(item for item in boosted if item.item_id == "active_provider")

    assert boosted_stale.score > boosted_active.score
    assert boosted_stale.diagnostics["temporal_query_intent_reason"] == (
        "query asks for previous state evidence"
    )
    assert (
        boosted_stale.diagnostics["score_signals"]["temporal_query_intent_boost"]
        == 0.042
    )


def test_temporal_query_demotes_plain_text_stale_state_for_current_query() -> None:
    intent = build_temporal_query_intent("Which Atlas provider is still valid?")
    active = _item(
        "active_provider",
        score=0.7,
        retrieval_source="postgres_facts",
        fact_status="active",
        text="Atlas provider remains valid and active: OpenAI.",
    )
    stale_text = _item(
        "stale_text_provider",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="",
        text="LocalAI is no longer valid for Atlas after the provider switch.",
    )

    boosted = apply_temporal_query_intent_boosts((active, stale_text), intent=intent)
    boosted_stale = next(item for item in boosted if item.item_id == "stale_text_provider")
    boosted_active = next(item for item in boosted if item.item_id == "active_provider")

    assert boosted_active.score > boosted_stale.score
    assert boosted_stale.diagnostics["temporal_query_intent_reason"] == (
        "query prefers current active memory and item has stale state markers"
    )


def test_temporal_query_prefers_active_for_current_decision_query() -> None:
    intent = build_temporal_query_intent("What did I decide to use?")
    active = _item(
        "active",
        score=0.7,
        retrieval_source="postgres_facts",
        fact_status="active",
    )
    superseded = _item(
        "superseded",
        score=0.72,
        retrieval_source="superseded_review",
        fact_status="superseded",
        review_only=True,
    )

    boosted = apply_temporal_query_intent_boosts((active, superseded), intent=intent)

    assert boosted[0].score > boosted[1].score
    assert boosted[0].diagnostics["temporal_query_intent_reason"] == (
        "query prefers current active memory"
    )
    assert boosted[1].diagnostics["temporal_query_intent_reason"] == (
        "query prefers current active memory and item is superseded"
    )


def test_source_turn_sequence_accepts_hyphenated_locomo_refs() -> None:
    intent = build_temporal_query_intent("What changed after source ref D12-4?")
    before = _item(
        "before",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Riley had not picked the venue yet.",
        source_id="source_turn_refs:D12-3",
    )
    after = _item(
        "after",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Riley picked the venue after the planning note.",
        source_id="source_turn_refs:D12-5",
    )

    boosted = apply_temporal_query_intent_boosts((before, after), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert by_id["after"].score > by_id["before"].score
    assert by_id["after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["before"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn precedes boundary"
    )


def test_source_turn_sequence_accepts_natural_session_turn_references() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after turn four in session twelve?"
    )
    underscored_intent = build_temporal_query_intent(
        "What did Riley mention after turn_4 in session_12?"
    )
    numbered_intent = build_temporal_query_intent(
        "What did Riley mention after turn no. four in session no. twelve?"
    )
    before = _item(
        "before",
        score=0.71,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn three: Riley was still waiting on Morgan.",
        source_id="locomo:conv-1:session_12",
    )
    after = _item(
        "after",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn five: Riley said the studio visit was confirmed.",
        source_id="locomo:conv-1:session_12",
    )

    boosted = apply_temporal_query_intent_boosts((before, after), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert underscored_intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert numbered_intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert by_id["after"].score > by_id["before"].score
    assert by_id["after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["before"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn precedes boundary"
    )


def test_source_turn_sequence_uses_natural_turn_refs_from_quote_preview() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention before source turn 4 from dialogue 12?"
    )
    before = ContextItem(
        item_id="before",
        item_type="fact",
        text="Riley was still waiting on Morgan.",
        score=0.7,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="Dialogue 12 turn 3: Riley was still waiting on Morgan.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )
    after = ContextItem(
        item_id="after",
        item_type="fact",
        text="Riley said the studio visit was confirmed.",
        score=0.72,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="conversation-summary",
                quote_preview="Dialogue 12 turn 5: Riley confirmed the visit.",
            ),
        ),
        diagnostics={"retrieval_source": "canonical_anchors"},
    )

    boosted = apply_temporal_query_intent_boosts((before, after), intent=intent)
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.before_turns[0].label() == "D12:4"
    assert by_id["before"].score > by_id["after"].score
    assert by_id["before"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before source turn and item source turn precedes boundary"
    )
    assert by_id["after"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for before source turn and item source turn follows boundary"
    )


def test_source_turn_sequence_keeps_natural_turn_scope_identity() -> None:
    intent = build_temporal_query_intent(
        "What did Riley mention after turn four in session twelve "
        "from conversation locomo:conv-1?"
    )
    matching_source = _item(
        "matching_source",
        score=0.7,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn five: Riley said the studio visit was confirmed.",
        source_id="locomo:conv-1:session_12",
    )
    different_source = _item(
        "different_source",
        score=0.72,
        retrieval_source="keyword_chunks",
        fact_status="active",
        text="Session twelve turn five: Riley mentioned a different visit.",
        source_id="locomo:conv-2:session_12",
    )

    boosted = apply_temporal_query_intent_boosts(
        (matching_source, different_source),
        intent=intent,
    )
    by_id = {item.item_id: item for item in boosted}

    assert intent.source_turn_sequence.after_turns[0].label() == "D12:4"
    assert intent.source_turn_sequence.has_source_identity is True
    assert by_id["matching_source"].score > by_id["different_source"].score
    assert by_id["matching_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for after source turn and item source turn follows boundary"
    )
    assert by_id["different_source"].diagnostics["temporal_query_intent_reason"] == (
        "query asks for source turn and item source identity differs"
    )


def _item(
    item_id: str,
    *,
    score: float,
    retrieval_source: str,
    fact_status: str,
    review_only: bool = False,
    event_temporal_hint_code: str | None = None,
    temporal_hint_code: str | None = None,
    event_valid_from: str | None = None,
    text: str | None = None,
    source_id: str | None = None,
) -> ContextItem:
    provenance = {"fact_status": fact_status}
    if event_temporal_hint_code:
        provenance["event_temporal_hint_code"] = event_temporal_hint_code
    if temporal_hint_code:
        provenance["temporal_hint_code"] = temporal_hint_code
    if event_valid_from:
        provenance["event_valid_from"] = event_valid_from
    return ContextItem(
        item_id=item_id,
        item_type="fact",
        text=text or item_id,
        score=score,
        source_refs=(SourceRef(source_type="fact", source_id=source_id or item_id),),
        diagnostics={
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "review_only": review_only,
            "score_signals": {"base_score": score},
            "provenance": provenance,
        },
    )
