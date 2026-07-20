from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    match_query_anchor_intent,
    match_query_anchor_intent_to_text,
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


def _anchor(
    *,
    kind: MemoryAnchorKind,
    label: str,
    anchor_id: str = "anchor_test",
) -> MemoryAnchor:
    now = datetime(2026, 6, 20, tzinfo=UTC)
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId("space_context_query_intent"),
        memory_scope_id=MemoryScopeId("memory_scope_context_query_intent"),
        kind=kind,
        normalized_key=label.casefold(),
        label=label,
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(kind, label),
        now=now,
    )


def test_query_anchor_intent_extracts_lowercase_ru_event_hints() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")

    assert intent.diagnostics()["query_anchor_hint_count"] == 5
    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"hours_ago", "hours_ago:1:hour"}
    assert intent.event_type_keys() == {"group:call", "sozvon"}


def test_query_anchor_intent_extracts_word_number_relative_week_hints() -> None:
    english = build_query_anchor_intent("call with Alex about Atlas two weeks ago")
    russian = build_query_anchor_intent("созвон с Алексом по Атласу две недели назад")
    month = build_query_anchor_intent("call with Alex about Atlas two months ago")
    russian_month = build_query_anchor_intent("созвон с Алексом по Атласу два месяца назад")
    year = build_query_anchor_intent("call with Alex about Atlas four years ago")
    russian_year = build_query_anchor_intent("созвон с Алексом по Атласу четыре года назад")

    assert english.temporal_keys() == {"weeks_ago", "weeks_ago:2:week"}
    assert russian.temporal_keys() == {"weeks_ago", "weeks_ago:2:week"}
    assert month.temporal_keys() == {"months_ago", "months_ago:2:month"}
    assert russian_month.temporal_keys() == {"months_ago", "months_ago:2:month"}
    assert year.temporal_keys() == {"years_ago", "years_ago:4:year"}
    assert russian_year.temporal_keys() == {"years_ago", "years_ago:4:year"}


def test_query_anchor_intent_extracts_future_relative_time_hints() -> None:
    tomorrow = build_query_anchor_intent("Project Atlas deadline tomorrow")
    next_week = build_query_anchor_intent("Which Atlas task is due next week?")
    next_month = build_query_anchor_intent("Что назначено по Атласу в следующем месяце?")

    assert tomorrow.temporal_keys() == {"tomorrow", "tomorrow:1:day"}
    assert next_week.temporal_keys() == {"next_week", "next_week:1:week"}
    assert next_month.temporal_keys() == {"next_month", "next_month:1:month"}
    assert "atlas" not in next_week.keys_for_kind(MemoryAnchorKind.PERSON)


def test_query_anchor_intent_matches_activity_duration_and_recurrence_keys() -> None:
    duration = build_query_anchor_intent("Has Maria volunteered for three years?")
    duration_anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Volunteered with Maria for three years",
    )
    duration_mismatch = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Volunteered with Maria for four years",
        anchor_id="anchor_duration_mismatch",
    )

    duration_match = match_query_anchor_intent(duration, duration_anchor)

    assert duration.keys_for_kind(MemoryAnchorKind.PERSON) == {"maria"}
    assert duration.temporal_keys() == {"duration_for", "duration_for:3:year"}
    assert duration_match is not None
    assert "query_event_temporal_match" in duration_match.reasons
    assert "duration_for:3:year" in duration_match.matched_keys
    assert match_query_anchor_intent(duration, duration_mismatch) is None

    recurrence = build_query_anchor_intent("Does Maria volunteer every weekend?")
    recurrence_anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Volunteers with Maria every weekend",
        anchor_id="anchor_recurrence",
    )
    recurrence_mismatch = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Volunteers with Maria every week",
        anchor_id="anchor_recurrence_mismatch",
    )

    recurrence_match = match_query_anchor_intent(recurrence, recurrence_anchor)

    assert recurrence.temporal_keys() == {"recurrence_every", "recurrence_every:1:weekend"}
    assert recurrence_match is not None
    assert "query_event_temporal_match" in recurrence_match.reasons
    assert "recurrence_every:1:weekend" in recurrence_match.matched_keys
    assert match_query_anchor_intent(recurrence, recurrence_mismatch) is None


def test_query_anchor_intent_adds_activity_state_event_type_hints() -> None:
    duration = build_query_anchor_intent("How long has Maria lived in Sweden?")
    duration_match = match_query_anchor_intent_to_text(
        duration,
        "Maria has lived in Sweden for three years and still calls it home.",
    )

    assert duration.keys_for_kind(MemoryAnchorKind.PERSON) == {"maria"}
    assert "sweden" not in duration.keys_for_kind(MemoryAnchorKind.PERSON)
    assert "sweden" not in duration.keys_for_kind(MemoryAnchorKind.PROJECT)
    assert duration.event_type_keys() == {"group:activity", "lived"}
    assert duration_match is not None
    assert "query_event_type_match" in duration_match.reasons
    assert "group:activity" in duration_match.matched_keys

    recurrence = build_query_anchor_intent("How often does Maria volunteer at the shelter?")
    recurrence_match = match_query_anchor_intent_to_text(
        recurrence,
        "Maria volunteers at the homeless shelter every weekend.",
    )

    assert recurrence.event_type_keys() == {"group:activity", "volunteer"}
    assert recurrence_match is not None
    assert "query_event_type_match" in recurrence_match.reasons
    assert "group:activity" in recurrence_match.matched_keys


def test_query_anchor_intent_does_not_promote_relative_time_words_as_people() -> None:
    english = build_query_anchor_intent("call with two weeks ago about Atlas")
    russian = build_query_anchor_intent("созвон с две недели назад по Атласу")

    assert "two" not in english.keys_for_kind(MemoryAnchorKind.PERSON)
    assert "dve" not in russian.keys_for_kind(MemoryAnchorKind.PERSON)
    assert english.temporal_keys() == {"weeks_ago", "weeks_ago:2:week"}
    assert russian.temporal_keys() == {"weeks_ago", "weeks_ago:2:week"}


def test_query_anchor_intent_groups_conversational_event_synonyms() -> None:
    english = build_query_anchor_intent("alex spoke about atlas two weeks ago")
    english_anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Chatted with Alex about Atlas 2 weeks ago",
    )

    english_match = match_query_anchor_intent(english, english_anchor)

    assert english.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert english.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert english.event_type_keys() == {"group:message", "spoke"}
    assert english_match is not None
    assert "query_event_type_match" in english_match.reasons
    assert "group:message" in english_match.matched_keys

    russian = build_query_anchor_intent("мария общалась с сергеем по атласу час назад")
    russian_anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Переписывалась с Сергеем по Атласу час назад",
    )

    russian_match = match_query_anchor_intent(russian, russian_anchor)

    assert russian.keys_for_kind(MemoryAnchorKind.PERSON) == {"sergei"}
    assert russian.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert russian.event_type_keys() == {"group:message", "obschalas"}
    assert russian_match is not None
    assert "query_event_type_match" in russian_match.reasons
    assert "group:message" in russian_match.matched_keys


def test_query_anchor_intent_groups_relocation_life_events() -> None:
    english = build_query_anchor_intent("Where did Caroline move from 4 years ago?")
    english_match = match_query_anchor_intent_to_text(
        english,
        "Caroline moved from Sweden 4 years ago before settling in Canada.",
    )

    assert english.keys_for_kind(MemoryAnchorKind.PERSON) == {"caroline"}
    assert english.event_type_keys() == {"group:relocation", "move"}
    assert english.temporal_keys() == {"years_ago", "years_ago:4:year"}
    assert english_match is not None
    assert set(english_match.reasons) >= {
        "query_event_participant_match",
        "query_event_type_match",
        "query_event_temporal_match",
    }
    assert "group:relocation" in english_match.matched_keys

    russian = build_query_anchor_intent("Откуда Мария переехала четыре года назад?")
    russian_match = match_query_anchor_intent_to_text(
        russian,
        "Мария переехала из Киева четыре года назад и потом жила в Варшаве.",
    )

    assert russian.keys_for_kind(MemoryAnchorKind.PERSON) == {"mariya"}
    assert "otkuda mariya" not in russian.keys_for_kind(MemoryAnchorKind.PERSON)
    assert russian.event_type_keys() == {"group:relocation", "pereehala"}
    assert russian.temporal_keys() == {"years_ago", "years_ago:4:year"}
    assert russian_match is not None
    assert "group:relocation" in russian_match.matched_keys


def test_query_anchor_intent_keeps_relocation_origin_without_exact_temporal_anchor() -> None:
    intent = build_query_anchor_intent("Where did Caroline move from 4 years ago?")
    origin_text = (
        "D3:13 Caroline: My friends, family and mentors are my rocks and "
        "have made all the difference. I have known these friends for 4 years, "
        "since I moved from my home country."
    )
    roots_text = (
        "D4:3 Caroline: This necklace is super special to me - a gift from my "
        "grandma in my home country, Sweden. It is like a reminder of my roots."
    )
    decoy_text = (
        "D17:3 Caroline: I started looking into adoption agencies and reading "
        "about what it takes to adopt a child. I talked to my family and friends "
        "about it, and they were all very supportive."
    )

    assert query_anchor_intent_text_conflicts(intent, origin_text) is False
    assert query_anchor_intent_text_conflicts(intent, roots_text) is False
    assert query_anchor_intent_text_conflicts(intent, decoy_text) is True


def test_query_anchor_intent_groups_plural_interviews_and_last_weekday() -> None:
    intent = build_query_anchor_intent("interviews last Friday")

    assert intent.event_type_keys() == {"group:workshop", "interviews"}
    assert intent.temporal_keys() == {"last_friday", "last_friday:1:weekday"}


def test_query_anchor_intent_groups_activity_life_events() -> None:
    intent = build_query_anchor_intent("What LGBTQ+ events has Caroline participated in?")
    match = match_query_anchor_intent_to_text(
        intent,
        "D1:3 Caroline: I went to a LGBTQ support group yesterday and felt powerful.",
    )

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"caroline"}
    assert intent.event_type_keys() == {"group:activity", "participated"}
    assert match is not None
    assert set(match.reasons) >= {
        "query_event_type_match",
        "query_person_identity_match",
    }
    assert "group:activity" in match.matched_keys


def test_query_anchor_intent_accepts_activity_event_paraphrase_text() -> None:
    intent = build_query_anchor_intent("What LGBTQ+ events has Caroline participated in?")
    text = (
        "D3:1 Caroline: I wanted to tell you about my school event last week. "
        "I talked about my transgender journey and encouraged students to get "
        "involved in the LGBTQ community."
    )

    assert query_anchor_intent_text_conflicts(intent, text) is False
    assert match_query_anchor_intent_to_text(intent, text) is not None


def test_query_anchor_intent_does_not_promote_to_as_project() -> None:
    intent = build_query_anchor_intent("What events has Caroline participated in to help children?")
    text = (
        "D9:2 Caroline: Last weekend I joined a mentorship program for LGBTQ youth. "
        "It is rewarding to help the community."
    )

    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == frozenset()
    assert query_anchor_intent_text_conflicts(intent, text) is False
    assert match_query_anchor_intent_to_text(intent, text) is not None


def test_query_anchor_intent_ignores_auxiliary_and_determiner_anchor_noise() -> None:
    intent = build_query_anchor_intent("What was discussed in the community counseling workshop?")
    text = (
        "D4:7 Jordan: I went to a community counseling workshop recently. "
        "It was enlightening. They talked about different therapeutic methods "
        "and how to support people."
    )

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset()
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == frozenset()
    assert query_anchor_intent_text_conflicts(intent, text) is False
    assert match_query_anchor_intent_to_text(intent, text) is not None


def test_query_anchor_intent_groups_plural_activity_questions() -> None:
    intent = build_query_anchor_intent("How many hikes has Joanna been on?")
    match = match_query_anchor_intent_to_text(
        intent,
        "D14:19 Joanna: Yep, I'm hiking with buddies this weekend.",
    )

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"joanna"}
    assert intent.event_type_keys() == {"group:activity", "hikes"}
    assert match is not None
    assert "group:activity" in match.matched_keys


def test_query_anchor_intent_does_not_promote_pronoun_participant_hints() -> None:
    intent = build_query_anchor_intent("What does Melanie do with her family on hikes?")

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"melanie"}


def test_query_anchor_lookup_keys_include_storage_and_canonical_variants() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")

    keys = {
        (lookup.kind.value, lookup.normalized_key) for lookup in query_anchor_lookup_keys(intent)
    }

    assert ("person", "алекс") in keys
    assert ("person", "aleks") in keys
    assert ("project", "атлас") in keys
    assert ("project", "atlas") in keys
    assert ("event", "созвон с алексом час назад") in keys
    assert ("event", "sozvon s aleks chas nazad") in keys
    assert all("event temporal" not in normalized_key for _, normalized_key in keys)


def test_query_anchor_intent_strips_question_modal_prefix_from_person() -> None:
    intent = build_query_anchor_intent("Would Melanie be considered an ally?")

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"melanie"}
    assert all(
        "would melanie" not in hint.canonical_key
        for hint in intent.hints
        if hint.kind == MemoryAnchorKind.PERSON
    )


def test_query_anchor_intent_ignores_russian_question_words_as_people() -> None:
    intent = build_query_anchor_intent("Что сказано про V1_DOCUMENT_SCOPE_MARKER?")

    assert "chto" not in intent.keys_for_kind(MemoryAnchorKind.PERSON)
    assert "что" not in intent.keys_for_kind(MemoryAnchorKind.PERSON)


def test_query_anchor_intent_ignores_russian_temporal_noise_in_text_match() -> None:
    intent = build_query_anchor_intent("Что решил Алекс после созвона по Атласу?")
    text = "После созвона по Атласу Алекс решил перейти на OpenAI для запуска."

    match = match_query_anchor_intent_to_text(intent, text)

    assert query_anchor_intent_text_conflicts(intent, text) is False
    assert match is not None
    assert "query_project_identity_match" in match.reasons
    assert "atlas" in match.matched_keys


def test_query_anchor_intent_matches_text_entity_evidence() -> None:
    intent = build_query_anchor_intent("Would Melanie be considered an ally?")

    match = match_query_anchor_intent_to_text(
        intent,
        "Melanie is supportive, encouraging, and helps Caroline feel accepted.",
    )

    assert match is not None
    assert match.reasons == ("query_person_identity_match",)
    assert match.matched_keys == ("melanie",)


def test_query_anchor_intent_text_match_rejects_wrong_person_same_project() -> None:
    intent = build_query_anchor_intent("What did Alex say about Project Atlas?")

    match = match_query_anchor_intent_to_text(
        intent,
        "Dana discussed Project Atlas launch notes yesterday.",
    )

    assert match is None


def test_query_anchor_intent_matches_text_event_identity() -> None:
    intent = build_query_anchor_intent("call Alex about Atlas last week")

    match = match_query_anchor_intent_to_text(
        intent,
        "Call with Alex about Atlas last week confirmed the launch decision.",
    )

    assert match is not None
    assert set(match.reasons) >= {
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_type_match",
        "query_event_temporal_match",
    }
    assert set(match.matched_keys) >= {"aleks", "atlas", "group:call", "last_week"}


def test_query_anchor_intent_treats_conversation_as_broad_event_type() -> None:
    intent = build_query_anchor_intent("latest conversation with Alex")

    match = match_query_anchor_intent_to_text(
        intent,
        "Call with Alex covered Project Atlas migration risks.",
    )

    assert query_anchor_intent_text_conflicts(intent, "Call with Alex covered Atlas.") is False
    assert match is not None
    assert "query_event_participant_match" in match.reasons


def test_query_anchor_intent_text_match_rejects_wrong_event_time() -> None:
    intent = build_query_anchor_intent("call Alex about Atlas last week")

    match = match_query_anchor_intent_to_text(
        intent,
        "Call with Alex about Atlas yesterday confirmed the launch decision.",
    )

    assert match is None


def test_query_anchor_intent_matches_cross_language_event_identity() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas 1 hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert match is not None
    assert match.score_boost == 0.09
    assert match.reasons == (
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_type_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {
        "aleks",
        "atlas",
        "group:call",
        "hours_ago:1:hour",
    }


def test_query_anchor_intent_matches_lowercase_direct_event_actor() -> None:
    intent = build_query_anchor_intent("call alex about atlas last week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas last week",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"last_week", "last_week:1:week"}
    assert match is not None
    assert match.reasons == (
        "query_event_identity_match",
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_type_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {
        "aleks",
        "atlas",
        "group:call",
        "last_week:1:week",
    }


def test_query_anchor_intent_matches_lowercase_actor_before_message_event() -> None:
    intent = build_query_anchor_intent("alex wrote about atlas hour ago")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Wrote with Alex about Atlas hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"hours_ago", "hours_ago:1:hour"}
    assert match is not None
    assert match.reasons == (
        "query_event_identity_match",
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_type_match",
        "query_event_temporal_match",
    )


def test_query_anchor_intent_matches_word_number_relative_time() -> None:
    intent = build_query_anchor_intent("alex said about atlas two hours ago")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Told with Alex about Atlas 2 hours ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.temporal_keys() == {"hours_ago", "hours_ago:2:hour"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "hours_ago:2:hour" in match.matched_keys


def test_query_anchor_intent_matches_previous_week_temporal_phrase() -> None:
    intent = build_query_anchor_intent("call alex about atlas previous week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas last week",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.temporal_keys() == {"last_week", "last_week:1:week"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "last_week:1:week" in match.matched_keys


def test_query_anchor_intent_matches_future_workflow_temporal_phrase() -> None:
    intent = build_query_anchor_intent("Which Atlas task is due next week?")

    match = match_query_anchor_intent_to_text(
        intent,
        "Project Atlas deadline next week is to send the launch checklist.",
    )

    assert intent.temporal_keys() == {"next_week", "next_week:1:week"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "query_event_project_match" in match.reasons


def test_query_anchor_intent_matches_absolute_date_workflow_temporal_phrase() -> None:
    intent = build_query_anchor_intent("Which Atlas deadline is on 15.08.2026?")

    match = match_query_anchor_intent_to_text(
        intent,
        "Project Atlas deadline 2026-08-15 is to send the launch checklist.",
    )

    assert intent.temporal_keys() == {"date_2026_08_15"}
    assert match is not None
    assert "query_event_temporal_match" in match.reasons
    assert "query_event_project_match" in match.reasons


def test_query_anchor_intent_matches_lowercase_actor_before_said_event() -> None:
    intent = build_query_anchor_intent("alex said about atlas yesterday")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Told with Alex about Atlas yesterday",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"yesterday", "yesterday:1:day"}
    assert intent.event_type_keys() == {"group:message", "said"}
    assert match is not None
    assert "query_event_type_match" in match.reasons
    assert set(match.matched_keys) >= {"aleks", "atlas", "group:message"}


def test_query_anchor_intent_matches_partial_day_temporal_only_event_query() -> None:
    intent = build_query_anchor_intent("with alex about atlas this morning")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Alex about Atlas this morning",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks"}
    assert intent.keys_for_kind(MemoryAnchorKind.PROJECT) == {"atlas"}
    assert intent.temporal_keys() == {"today_morning", "today_morning:0:part_of_day"}
    assert intent.event_type_keys() == frozenset()
    assert match is not None
    assert match.reasons == (
        "query_event_participant_match",
        "query_event_project_match",
        "query_event_temporal_match",
    )
    assert set(match.matched_keys) >= {"aleks", "atlas", "today_morning:0:part_of_day"}


def test_query_anchor_intent_rejects_wrong_event_participant() -> None:
    intent = build_query_anchor_intent("созвон с алексом в атласе час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Call with Sam about Atlas 1 hour ago",
    )

    assert match_query_anchor_intent(intent, anchor) is None


def test_query_anchor_intent_rejects_wrong_explicit_event_type() -> None:
    intent = build_query_anchor_intent("call with alex about atlas last week")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="Chat with Alex about Atlas last week",
    )

    assert match_query_anchor_intent(intent, anchor) is None


def test_query_anchor_intent_matches_cross_language_message_event_type() -> None:
    intent = build_query_anchor_intent("переписывался с алексом по атласу час назад")
    anchor = _anchor(
        kind=MemoryAnchorKind.EVENT,
        label="DM with Alex about Atlas 1 hour ago",
    )

    match = match_query_anchor_intent(intent, anchor)

    assert intent.event_type_keys() == {"group:message", "perepisyvalsya"}
    assert match is not None
    assert "query_event_type_match" in match.reasons
    assert set(match.matched_keys) >= {"aleks", "atlas", "group:message"}


def test_query_anchor_intent_groups_russian_message_event_verbs() -> None:
    cases = (
        ("алекс ответил по атласу вчера", "otvetil", "Алекс"),
        ("мария сообщила по атласу вчера", "soobschila", "Мария"),
        ("дана скинула по атласу вчера", "skinula", "Дана"),
        ("сергей прислал по атласу вчера", "prislal", "Сергей"),
        ("ирина отправила по атласу вчера", "otpravila", "Ирина"),
    )

    for query, event_key, participant in cases:
        anchor = _anchor(
            kind=MemoryAnchorKind.EVENT,
            label=f"DM with {participant} about Atlas yesterday",
        )
        intent = build_query_anchor_intent(query)
        match = match_query_anchor_intent(intent, anchor)

        assert intent.event_type_keys() == {"group:message", event_key}
        assert match is not None
        assert "query_event_type_match" in match.reasons
        assert "group:message" in match.matched_keys


def test_query_anchor_intent_rejects_wrong_project_anchor() -> None:
    intent = build_query_anchor_intent("what did Alex say about project Apollo")
    atlas = _anchor(kind=MemoryAnchorKind.PROJECT, label="Project Atlas")
    apollo = _anchor(
        kind=MemoryAnchorKind.PROJECT,
        label="Project Apollo",
        anchor_id="anchor_apollo",
    )

    assert match_query_anchor_intent(intent, atlas) is None
    match = match_query_anchor_intent(intent, apollo)
    assert match is not None
    assert match.reasons == ("query_project_identity_match",)


def test_first_person_occupational_role_titles_are_not_person_hints() -> None:
    questions = (
        "How many people did I lead in my role as Senior Software Engineer?",
        "I work as a Principal Data Scientist and lead researchers.",
        "I am a Customer Success Representative with four direct reports.",
        "I'm currently a Product Owner on the platform team.",
        "As a Staff Platform Architect, I lead four engineers.",
        "Engineering Manager was my role before the promotion.",
        "Senior Software Engineer was my previous role.",
        "Scrum Master is my current role; what changed?",
        "How many reports did I have in my Director of Product role?",
        "My role, Vice President of Engineering, started last year.",
        "My role is “Chief Technology Officer”; how many people report to me?",
        "My role is VP of Engineering; what changed?",
        "I am the Chief of Staff.",
        "My role is Human Resources Business Partner.",
        "My current position: Lead UX Researcher—how many studies do I own?",
    )

    for question in questions:
        intent = build_query_anchor_intent(question)

        assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset(), question


def test_first_person_role_filter_preserves_named_people_and_possessives() -> None:
    named = build_query_anchor_intent(
        "How did Dana's scope change in my Senior Software Engineer role?"
    )
    punctuated = build_query_anchor_intent(
        'I work as a "Director of Product"; what did Dana recommend to Alex?'
    )
    possessive_title = build_query_anchor_intent(
        "What did Alex say about my role as Dana's manager?"
    )
    self_description = build_query_anchor_intent(
        "I am a Senior Software Engineer with Dana on the incident review."
    )
    following_clause = build_query_anchor_intent(
        "I work as an Engineering Manager and Dana handles recruiting"
    )

    assert named.keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}
    assert punctuated.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks", "dana"}
    assert possessive_title.keys_for_kind(MemoryAnchorKind.PERSON) == {"aleks", "dana"}
    assert self_description.keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}
    assert following_clause.keys_for_kind(MemoryAnchorKind.PERSON) == {"dana"}


def test_role_descriptors_do_not_create_text_identity_conflicts() -> None:
    role_only = build_query_anchor_intent(
        "How many engineers did I lead when I started my new role as "
        "Senior Software Engineer, and how many do I lead now?"
    )

    assert (
        query_anchor_intent_text_conflicts(
            role_only,
            "Before: In my role as Staff Platform Engineer, I led four engineers.",
        )
        is False
    )
    assert (
        query_anchor_intent_text_conflicts(
            role_only,
            "Now: I lead five engineers.",
        )
        is False
    )

    named = build_query_anchor_intent(
        "How many engineers did Dana lead in my role as Senior Software Engineer?"
    )

    assert (
        query_anchor_intent_text_conflicts(
            named,
            "Dana: In my role as Staff Platform Engineer, I led four engineers.",
        )
        is False
    )
    assert (
        query_anchor_intent_text_conflicts(
            named,
            "Morgan: In my role as Staff Platform Engineer, I led four engineers.",
        )
        is True
    )


def test_role_filter_does_not_exempt_non_first_person_title_phrases() -> None:
    third_person = build_query_anchor_intent(
        "What did Alex say about Jordan's role as Senior Software Engineer?"
    )
    person_wording = build_query_anchor_intent(
        "Was Senior Software Engineer the person who met Dana?"
    )
    generic_role = build_query_anchor_intent(
        "What did Alex say about the role of Senior Software Engineer?"
    )
    relationship = build_query_anchor_intent("I am a friend of Senior Software Engineer Dana.")
    unrelated_as = build_query_anchor_intent(
        "I watched as Engineering Manager Morgan presented the roadmap."
    )

    assert third_person.keys_for_kind(MemoryAnchorKind.PERSON) == {
        "aleks",
        "engineer",
        "senior software",
    }
    assert person_wording.keys_for_kind(MemoryAnchorKind.PERSON) == {
        "dana",
        "senior software engineer",
    }
    assert generic_role.keys_for_kind(MemoryAnchorKind.PERSON) == {
        "aleks",
        "engineer",
        "senior software",
    }
    assert relationship.keys_for_kind(MemoryAnchorKind.PERSON) == {
        "engineer dana",
        "senior software",
    }
    assert unrelated_as.keys_for_kind(MemoryAnchorKind.PERSON) == {
        "engineering manager",
        "morgan",
    }


def test_unrelated_as_clause_reports_named_person_identity_conflict() -> None:
    dana = build_query_anchor_intent("What did Dana present?")

    assert (
        query_anchor_intent_text_conflicts(
            dana,
            "I work as an Engineering Manager and Dana handles recruiting.",
        )
        is False
    )
    assert (
        query_anchor_intent_text_conflicts(
            dana,
            "I watched as Engineering Manager Morgan presented the roadmap.",
        )
        is True
    )
    assert query_anchor_intent_text_conflicts(dana, "Dana presented the roadmap.") is False
