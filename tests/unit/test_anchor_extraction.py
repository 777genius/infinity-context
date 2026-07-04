from infinity_context_core.application.anchor_extraction import (
    extract_observed_anchors,
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.domain.entities import MemoryAnchorKind


def test_anchor_extraction_ignores_document_metadata_as_people() -> None:
    anchors = extract_observed_anchors(
        "Content Dimensions Duration Format Streams Transcript Keyframes Page"
    )

    assert {
        (anchor.kind.value, anchor.normalized_key)
        for anchor in anchors
        if anchor.kind.value == "person"
    } == set()


def test_anchor_extraction_keeps_real_people_projects_and_events() -> None:
    anchors = extract_observed_anchors(
        "Alex shared Project Atlas notes from meeting last week about Qdrant."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    assert ("person", "alex") in keys
    assert ("project", "atlas") in keys
    assert ("project", "qdrant") in keys
    assert ("event", "meeting last week") in keys


def test_anchor_extraction_treats_technical_context_labels_as_projects() -> None:
    anchors = extract_observed_anchors(
        "Alice keeps Kubernetes manifests in helmfile overlays for project Atlas. "
        "Falcon migration notes mention Alice."
    )

    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "alice" in person_keys
    assert "atlas" in project_keys
    assert "kubernetes" in project_keys
    assert "falcon" in project_keys
    assert "kubernetes" not in person_keys
    assert "falcon" not in person_keys


def test_anchor_metadata_includes_bounded_alias_identity_terms() -> None:
    metadata = structured_anchor_metadata_for_label(
        MemoryAnchorKind.PERSON,
        "Alexander",
        aliases=("Alex", "Алекс", "Alexander"),
    )

    assert metadata["identity_key"] == "person:aleksander"
    assert metadata["person_canonical_key"] == "aleksander"
    assert metadata["alias_identity_terms"] == ["aleks"]


def test_anchor_extraction_ignores_temporal_leading_words_as_people() -> None:
    anchors = extract_observed_anchors(
        "Yesterday Alex met Dana about Project Atlas billing cutoff."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}
    assert ("person", "alex") in keys
    assert ("person", "dana") in keys
    assert ("project", "atlas") in keys
    assert "yesterday alex" not in person_keys
    assert "met with alex yesterday" in event_keys


def test_anchor_extraction_handles_russian_project_case_inflections() -> None:
    anchors = extract_observed_anchors("На прошлой неделе был созвон с Алексом по проекту Атлас.")

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}
    assert ("project", "атлас") in keys
    assert ("person", "алекс") in keys
    assert "атлас" not in person_keys
    assert "созвон с алексом на прошлой неделе" in event_keys


def test_anchor_extraction_ignores_command_verbs_as_people() -> None:
    anchors = extract_observed_anchors("Open the Docker backend logs and screenshot progress bar.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert "open" not in person_keys


def test_anchor_extraction_ignores_geographic_adjectives_as_people() -> None:
    anchors = extract_observed_anchors("What European countries has Maria been to?")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert "maria" in person_keys
    assert "european" not in person_keys

    intent = build_query_anchor_intent("What European countries has Maria been to?")
    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset({"maria"})


def test_anchor_extraction_strips_question_modal_prefix_from_person() -> None:
    anchors = extract_observed_anchors("Would Melanie be considered an ally?")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert "melanie" in person_keys
    assert "would melanie" not in person_keys


def test_anchor_extraction_keeps_full_question_modal_person_name() -> None:
    anchors = extract_observed_anchors("Would Melanie Cooper be considered an ally?")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert "melanie cooper" in person_keys
    assert "melanie" not in person_keys
    assert "cooper" not in person_keys

    intent = build_query_anchor_intent("Would Melanie Cooper be considered an ally?")
    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset({"melanie cooper"})


def test_anchor_extraction_avoids_surname_only_modal_event_subject() -> None:
    anchors = extract_observed_anchors("Should Alex Cooper join the robotics club?")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert "alex cooper" in person_keys
    assert "alex" not in person_keys
    assert "cooper" not in person_keys

    intent = build_query_anchor_intent("Should Alex Cooper join the robotics club?")
    assert intent.keys_for_kind(MemoryAnchorKind.PERSON) == frozenset({"aleks cooper"})


def test_anchor_extraction_ignores_russian_question_words_as_people() -> None:
    anchors = extract_observed_anchors("Что сказано про V1_DOCUMENT_SCOPE_MARKER?")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "chto" not in person_keys
    assert "что" not in person_keys


def test_anchor_extraction_handles_relocation_life_events_without_location_people() -> None:
    anchors = extract_observed_anchors(
        "Caroline moved from Sweden 4 years ago. Мария переехала из Киева четыре года назад."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    event_metadata = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "caroline" in person_keys
    assert "мария" in person_keys
    assert "sweden" not in person_keys
    assert "киева" not in person_keys
    assert event_metadata["moved with caroline 4 years ago"]["event_identity_terms"] == [
        "moved",
        "caroline",
        "years_ago:4:year",
    ]
    assert event_metadata["переехала с мария четыре года назад"]["event_identity_terms"] == [
        "pereehala",
        "mariya",
        "years_ago:4:year",
    ]


def test_anchor_extraction_suppresses_generic_relocation_origin_places_as_people() -> None:
    anchors = extract_observed_anchors(
        "Dana moved from France 3 years ago. "
        "Ольга переехала из Парижа три года назад. "
        "Email from Alex included the invoice."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}

    assert "dana" in person_keys
    assert "ольга" in person_keys
    assert "alex" in person_keys
    assert "france" not in person_keys
    assert "парижа" not in person_keys
    assert "email" not in person_keys
    assert "moved with dana 3 years ago" in event_keys
    assert "переехала с ольга три года назад" in event_keys


def test_anchor_extraction_structures_activity_life_events() -> None:
    anchors = extract_observed_anchors(
        "D1:3 Caroline: I went to a LGBTQ support group yesterday. "
        "D9:2 Caroline joined a mentorship program last weekend."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert events["went yesterday"]["event_identity_terms"] == [
        "went",
        "yesterday:1:day",
    ]
    assert events["joined with caroline last weekend"]["event_identity_terms"] == [
        "joined",
        "caroline",
        "last_weekend:1:weekend",
    ]


def test_anchor_extraction_structures_activity_duration_event_metadata() -> None:
    anchors = extract_observed_anchors(
        "Maria has volunteered at the homeless shelter for three years. "
        "Alex has lived in Sweden since 2021."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "maria" in person_keys
    assert "alex" in person_keys
    assert "sweden" not in person_keys

    volunteered = events["volunteered with maria for three years"]
    assert volunteered["event_participant_canonical_key"] == "maria"
    assert volunteered["event_duration_phrase"] == "for three years"
    assert volunteered["event_duration_hint_code"] == "duration_for"
    assert volunteered["event_duration_quantity"] == 3
    assert volunteered["event_duration_unit"] == "year"
    assert volunteered["event_identity_terms"] == [
        "volunteered",
        "maria",
        "duration_for:3:year",
    ]

    lived = events["lived with alex since 2021"]
    assert lived["event_participant_canonical_key"] == "aleks"
    assert lived["event_duration_phrase"] == "since 2021"
    assert lived["event_duration_hint_code"] == "duration_since_year"
    assert lived["event_duration_quantity"] == 2021
    assert lived["event_duration_unit"] == "year"
    assert lived["event_identity_terms"] == [
        "lived",
        "aleks",
        "duration_since_year:2021:year",
    ]


def test_anchor_extraction_structures_activity_recurrence_event_metadata() -> None:
    anchors = extract_observed_anchors(
        "Maria volunteers at the shelter every weekend. "
        "Алекс работает в Atlas два раза в неделю."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    volunteers = events["volunteers with maria every weekend"]
    assert volunteers["event_recurrence_phrase"] == "every weekend"
    assert volunteers["event_recurrence_hint_code"] == "recurrence_every"
    assert volunteers["event_recurrence_quantity"] == 1
    assert volunteers["event_recurrence_unit"] == "weekend"
    assert volunteers["event_identity_terms"] == [
        "volunteers",
        "maria",
        "recurrence_every:1:weekend",
    ]

    works = events["работает с алекс два раза в неделю"]
    assert works["event_participant_canonical_key"] == "aleks"
    assert works["event_recurrence_phrase"] == "два раза в неделю"
    assert works["event_recurrence_hint_code"] == "recurrence_per"
    assert works["event_recurrence_quantity"] == 2
    assert works["event_recurrence_unit"] == "week"
    assert works["event_identity_terms"] == [
        "rabotaet",
        "aleks",
        "recurrence_per:2:week",
    ]


def test_anchor_extraction_structures_last_weekday_events_without_weekday_person() -> None:
    anchors = extract_observed_anchors(
        "Caroline passed the adoption agency interviews last Friday."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "caroline" in person_keys
    assert "friday" not in person_keys
    assert events["interviews with caroline last friday"]["event_participant_label"] == ("caroline")
    assert (
        events["interviews with caroline last friday"]["event_participant_canonical_key"]
        == "caroline"
    )
    assert events["interviews with caroline last friday"]["event_identity_terms"] == [
        "interviews",
        "caroline",
        "last_friday:1:weekday",
    ]
    assert events["interviews last friday"]["event_temporal_hint_code"] == "last_friday"
    assert events["interviews last friday"]["event_temporal_unit"] == "weekday"
    assert events["interviews last friday"]["event_identity_terms"] == [
        "interviews",
        "last_friday:1:weekday",
    ]


def test_anchor_extraction_keeps_same_name_people_and_projects_separate() -> None:
    anchors = extract_observed_anchors("Alex wrote that Project Alex is a separate workspace.")

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    assert ("person", "alex") in keys
    assert ("project", "alex") in keys


def test_anchor_extraction_keeps_multi_token_project_names_without_description() -> None:
    anchors = extract_observed_anchors(
        "Project Atlas Mobile tracks onboarding copy. Project Atlas uses Qdrant chunks."
    )

    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    assert "atlas mobile" in project_keys
    assert "atlas" in project_keys
    assert "atlas mobile tracks" not in project_keys
    assert "atlas uses" not in project_keys


def test_anchor_extraction_promotes_capitalized_memory_subject_as_project_context() -> None:
    anchors = extract_observed_anchors("Alex owns Atlas document retrieval notes from the call.")

    by_key = {(anchor.kind.value, anchor.normalized_key): anchor for anchor in anchors}

    assert ("person", "alex") in by_key
    assert ("project", "atlas") in by_key
    assert by_key[("project", "atlas")].reason == "implicit project context"
    assert by_key[("project", "atlas")].metadata["project_canonical_key"] == "atlas"


def test_anchor_extraction_stops_project_labels_at_sentence_boundaries() -> None:
    anchors = extract_observed_anchors(
        "Алекс Project Atlas. Час назад я переписывался с Алексом по Project Atlas."
    )

    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    assert "atlas" in project_keys
    assert "atlas алекс" not in project_keys
    assert "atlas час" not in project_keys


def test_anchor_extraction_ignores_question_project_stopword_label() -> None:
    anchors = extract_observed_anchors("Which project is not blocked?")

    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    assert "is" not in project_keys
    assert project_keys == set()


def test_anchor_extraction_keeps_organizations_separate_from_people() -> None:
    anchors = extract_observed_anchors(
        "Alex shared OpenAI notes with company Acme Corp and GitHub team updates."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    assert ("person", "alex") in keys
    assert ("organization", "openai") in keys
    assert ("organization", "github") in keys
    assert ("organization", "acme corp") in keys
    assert "openai" not in person_keys
    assert "github" not in person_keys


def test_anchor_extraction_keeps_game_platforms_separate_from_people() -> None:
    anchors = extract_observed_anchors(
        "Nate plays Xenoblade Chronicles, and the image caption shows Nintendo game covers. "
        "Nate owns a Nintendo Switch console."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    organization_keys = {
        anchor.normalized_key for anchor in anchors if anchor.kind.value == "organization"
    }

    assert "nate" in person_keys
    assert "nintendo" in organization_keys
    assert "nintendo" not in person_keys
    assert "nintendo switch" not in person_keys
    assert "xenoblade chronicles" not in person_keys


def test_anchor_extraction_avoids_suffixed_organization_person_false_positives() -> None:
    anchors = extract_observed_anchors(
        "GitHub Actions failed for OpenAI evals. Acme Research LLC owns the rollout. "
        "The GitHub team reviewed OpenAI memory notes."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    organization_keys = {
        anchor.normalized_key for anchor in anchors if anchor.kind.value == "organization"
    }

    assert ("organization", "github") in keys
    assert ("organization", "openai") in keys
    assert ("organization", "acme research llc") in keys
    assert "acme research" not in person_keys
    assert "github actions" not in person_keys
    assert "reviewed openai memory notes" not in organization_keys


def test_anchor_extraction_suppresses_creative_work_title_and_author_people() -> None:
    anchors = extract_observed_anchors(
        "Melanie recommended Becoming Nicole by Amy Ellis Nutt to Caroline."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "melanie" in person_keys
    assert "caroline" in person_keys
    assert "becoming nicole" not in person_keys
    assert "amy ellis" not in person_keys
    assert "nutt" not in person_keys


def test_anchor_extraction_keeps_recommender_person_in_by_phrase() -> None:
    anchors = extract_observed_anchors("The book was recommended by Alex to Caroline.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "alex" in person_keys
    assert "caroline" in person_keys


def test_anchor_extraction_suppresses_song_title_and_composer_people() -> None:
    anchors = extract_observed_anchors(
        'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "melanie" in person_keys
    assert "four" not in person_keys
    assert "seasons" not in person_keys
    assert "vivaldi" not in person_keys


def test_anchor_extraction_suppresses_unquoted_classical_work_people() -> None:
    anchors = extract_observed_anchors(
        "Melanie likes The Four Seasons by Vivaldi and Bach concertos."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "melanie" in person_keys
    assert "four" not in person_keys
    assert "seasons" not in person_keys
    assert "vivaldi" not in person_keys
    assert "bach" not in person_keys


def test_anchor_extraction_suppresses_articled_movie_title_people() -> None:
    anchors = extract_observed_anchors("Caroline watched The Matrix with Alex.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "caroline" in person_keys
    assert "alex" in person_keys
    assert "matrix" not in person_keys


def test_anchor_extraction_suppresses_titled_book_author_people() -> None:
    anchors = extract_observed_anchors(
        "Would Caroline likely have Dr. Seuss books on her bookshelf?"
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "caroline" in person_keys
    assert "seuss" not in person_keys


def test_anchor_extraction_keeps_titled_real_person_without_book_context() -> None:
    anchors = extract_observed_anchors("Dr. Alex met Caroline about Project Atlas.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "alex" in person_keys
    assert "caroline" in person_keys


def test_anchor_extraction_suppresses_known_location_people() -> None:
    anchors = extract_observed_anchors(
        "Joanna took that pic on a hike last summer near Fort Wayne. "
        "Alex visited New York with Maria."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "joanna" in person_keys
    assert "alex" in person_keys
    assert "maria" in person_keys
    assert "fort wayne" not in person_keys
    assert "new york" not in person_keys


def test_anchor_extraction_keeps_location_name_when_used_as_person() -> None:
    anchors = extract_observed_anchors("Wayne called Alex yesterday.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}

    assert "wayne" in person_keys
    assert "alex" in person_keys


def test_anchor_extraction_keeps_numeric_temporal_event_labels() -> None:
    anchors = extract_observed_anchors(
        "Сохрани заметку из разговора 5 часов назад и chat 2 days ago."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    assert ("event", "разговора 5 часов назад") in keys
    assert ("event", "chat 2 days ago") in keys


def test_anchor_extraction_keeps_event_participants() -> None:
    anchors = extract_observed_anchors(
        "Call with Alex about Atlas. Созвон с Марией вчера по Project Atlas."
    )

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    canonical_keys = {
        anchor.normalized_key: anchor.metadata.get("canonical_key")
        for anchor in anchors
        if anchor.kind.value == "event"
    }
    assert ("event", "call with alex") in keys
    assert ("project", "atlas") in keys
    assert ("event", "созвон с марией вчера") in keys
    assert ("event", "созвон вчера") in keys
    assert canonical_keys["созвон с марией вчера"] == "sozvon s mariya vchera"


def test_anchor_extraction_keeps_event_participant_before_keyword() -> None:
    anchors = extract_observed_anchors(
        "Alex call last week covered billing. Мария созвон вчера подтвердила backend."
    )

    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}
    canonical_keys = {
        anchor.normalized_key: anchor.metadata.get("canonical_key")
        for anchor in anchors
        if anchor.kind.value == "event"
    }
    assert "call with alex last week" in event_keys
    assert "созвон с мария вчера" in event_keys
    assert canonical_keys["call with alex last week"] == "call with aleks last week"
    assert canonical_keys["созвон с мария вчера"] == "sozvon s mariya vchera"


def test_anchor_extraction_does_not_attach_next_event_participant() -> None:
    anchors = extract_observed_anchors(
        "Meeting last week and chat with Alex an hour ago covered Project Atlas."
    )

    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}
    assert "meeting last week" in event_keys
    assert "meeting with alex last week" not in event_keys
    assert "chat with alex an hour ago" in event_keys


def test_anchor_extraction_handles_russian_temporal_person_cases() -> None:
    anchors = extract_observed_anchors(
        "Час назад я переписывался с Алексом по Project Atlas. Созвон с Марией вчера про backend."
    )

    person_keys = {
        (anchor.normalized_key, anchor.metadata.get("canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "person"
    }
    event_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}
    assert ("час", "chas") not in person_keys
    assert ("созвон", "sozvon") not in person_keys
    assert ("алекс", "aleks") in person_keys
    assert ("мария", "mariya") in person_keys
    assert "переписывался с алексом час назад" in event_keys
    assert "созвон с марией вчера" in event_keys


def test_anchor_extraction_handles_phone_call_dative_person_and_project() -> None:
    anchors = extract_observed_anchors("Позвонил Алексу по Атласу час назад.")

    person_keys = {
        (anchor.normalized_key, anchor.metadata.get("person_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "person"
    }
    project_keys = {
        (anchor.normalized_key, anchor.metadata.get("project_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "project"
    }
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert ("алекс", "aleks") in person_keys
    assert ("атлас", "atlas") in project_keys
    assert ("позвонил алексу", "pozvonil aleksu") not in person_keys
    assert ("атласу", "atlasu") not in person_keys
    assert "позвонил с алексу по атласу час назад" in events
    assert events["позвонил с алексу по атласу час назад"]["event_type_canonical"] == ("pozvonil")
    assert (
        events["позвонил с алексу по атласу час назад"]["event_participant_canonical_key"]
        == "aleks"
    )
    assert events["позвонил с алексу по атласу час назад"]["event_project_canonical_key"] == (
        "atlas"
    )
    assert events["позвонил с алексу по атласу час назад"]["event_temporal_hint_code"] == (
        "hours_ago"
    )


def test_anchor_extraction_handles_dm_event_shorthand() -> None:
    anchors = extract_observed_anchors("Alex DM yesterday about Atlas invoice.")

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "alex" in person_keys
    assert "atlas" in project_keys
    assert "dm with alex about atlas yesterday" in events
    assert events["dm with alex about atlas yesterday"]["event_participant_canonical_key"] == (
        "aleks"
    )
    assert events["dm with alex about atlas yesterday"]["event_project_canonical_key"] == "atlas"
    assert events["dm with alex about atlas yesterday"]["event_temporal_hint_code"] == ("yesterday")


def test_anchor_extraction_handles_said_and_told_event_phrasing() -> None:
    anchors = extract_observed_anchors(
        "alex said about Atlas yesterday. Алекс сказал про Атлас вчера."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "said with alex about atlas yesterday" in events
    assert events["said with alex about atlas yesterday"]["event_type_canonical"] == "said"
    assert (
        events["said with alex about atlas yesterday"]["event_participant_canonical_key"] == "aleks"
    )
    assert events["said with alex about atlas yesterday"]["event_project_canonical_key"] == (
        "atlas"
    )
    assert "сказал с алекс про атлас вчера" in events
    assert events["сказал с алекс про атлас вчера"]["event_type_canonical"] == "skazal"
    assert events["сказал с алекс про атлас вчера"]["event_participant_canonical_key"] == ("aleks")


def test_anchor_extraction_handles_russian_message_event_verbs() -> None:
    anchors = extract_observed_anchors(
        "алекс ответил по Атласу вчера. "
        "Мария сообщила по Атласу вчера. "
        "Дана скинула по Атласу вчера."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "ответил с алекс по атласу вчера" in events
    assert events["ответил с алекс по атласу вчера"]["event_type_canonical"] == "otvetil"
    assert events["ответил с алекс по атласу вчера"]["event_participant_canonical_key"] == "aleks"
    assert events["ответил с алекс по атласу вчера"]["event_project_canonical_key"] == "atlas"
    assert "сообщила с мария по атласу вчера" in events
    assert events["сообщила с мария по атласу вчера"]["event_type_canonical"] == "soobschila"
    assert "скинула с дана по атласу вчера" in events
    assert events["скинула с дана по атласу вчера"]["event_type_canonical"] == "skinula"


def test_anchor_extraction_keeps_russian_message_actor_and_counterparty() -> None:
    anchors = extract_observed_anchors("Алекс ответил Марии по Атласу вчера.")

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "ответил с алекс по атласу вчера" in events
    assert events["ответил с алекс по атласу вчера"]["event_participant_canonical_key"] == "aleks"
    assert "ответил с марии по атласу вчера" in events
    assert events["ответил с марии по атласу вчера"]["event_participant_canonical_key"] == "mariya"


def test_anchor_extraction_does_not_promote_russian_asset_objects_to_people() -> None:
    cases = (
        ("Дана скинула файл про Атлас вчера.", "файл", "скинула с дана про атлас вчера"),
        (
            "Ирина отправила документ по Атласу вчера.",
            "документ",
            "отправила с ирина по атласу вчера",
        ),
        (
            "Сергей прислал скриншот по Атласу вчера.",
            "скриншот",
            "прислал с сергей по атласу вчера",
        ),
    )

    for text, object_key, expected_event_key in cases:
        anchors = extract_observed_anchors(text)
        person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
        events = {
            anchor.normalized_key: anchor.metadata
            for anchor in anchors
            if anchor.kind.value == "event"
        }

        assert object_key not in person_keys
        assert not any(f"с {object_key}" in event_key for event_key in events)
        assert expected_event_key in events


def test_anchor_extraction_handles_chat_handles_and_email_people() -> None:
    anchors = extract_observed_anchors(
        "DM @alex.cooper yesterday about Atlas invoice. "
        "alex.smith@example.com shared the notes. "
        "@project-atlas and noreply@github.com should not become people."
    )

    person_keys = {
        (anchor.normalized_key, anchor.metadata.get("person_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "person"
    }
    project_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert ("alex cooper", "aleks cooper") in person_keys
    assert ("alex smith", "aleks smith") in person_keys
    assert ("project atlas", "project atlas") not in person_keys
    assert ("noreply", "noreply") not in person_keys
    assert "atlas" in project_keys
    assert "dm with alex cooper about atlas yesterday" in events
    assert (
        events["dm with alex cooper about atlas yesterday"]["event_participant_canonical_key"]
        == "aleks cooper"
    )
    assert events["dm with alex cooper about atlas yesterday"]["event_project_canonical_key"] == (
        "atlas"
    )


def test_anchor_extraction_keeps_explicit_person_alias_as_identity_term() -> None:
    anchors = extract_observed_anchors(
        "Alex aka Alexander Cooper discussed Project Atlas. "
        "Alexander Cooper should resolve through the alias, not a second anchor."
    )

    people = {
        anchor.normalized_key: anchor
        for anchor in anchors
        if anchor.kind == MemoryAnchorKind.PERSON
    }

    assert "alex" in people
    assert "alexander cooper" not in people
    assert people["alex"].aliases == ("Alex", "Alexander Cooper")
    assert people["alex"].metadata["alias_identity_terms"] == ["aleksander cooper"]
    assert people["alex"].metadata["identity_key"] == "person:aleks"


def test_anchor_extraction_keeps_person_initial_without_duplicate_first_name() -> None:
    anchors = extract_observed_anchors("Alex C. sent Project Atlas notes after the call.")

    person_keys = {
        (anchor.normalized_key, anchor.metadata.get("person_canonical_key"))
        for anchor in anchors
        if anchor.kind == MemoryAnchorKind.PERSON
    }

    assert ("alex c", "aleks c") in person_keys
    assert ("alex", "aleks") not in person_keys


def test_anchor_extraction_keeps_explicit_project_alias_as_identity_term() -> None:
    anchors = extract_observed_anchors(
        "Project Atlas aka Atlas Mobile owns the screenshots. "
        "Project Atlas Mobile should not create a duplicate project in this capture."
    )

    projects = {
        anchor.normalized_key: anchor
        for anchor in anchors
        if anchor.kind == MemoryAnchorKind.PROJECT
    }

    assert "atlas" in projects
    assert "atlas mobile" not in projects
    assert projects["atlas"].aliases == ("Atlas", "Atlas Mobile")
    assert projects["atlas"].metadata["alias_identity_terms"] == ["atlas mobile"]
    assert projects["atlas"].metadata["identity_key"] == "project:atlas"


def test_anchor_extraction_merges_common_russian_person_case_variants() -> None:
    anchors = extract_observed_anchors(
        "Мария подтвердила Project Atlas. От Марии пришел follow-up. "
        "Сергей owns backend. От Сергея пришел Qdrant note. "
        "Алекс согласовал timeline. От Алекса пришел update."
    )

    person_keys = {
        anchor.normalized_key: anchor.metadata.get("canonical_key")
        for anchor in anchors
        if anchor.kind.value == "person"
    }

    assert person_keys["мария"] == "mariya"
    assert person_keys["сергей"] == "sergei"
    assert person_keys["алекс"] == "aleks"
    assert "марии" not in person_keys
    assert "сергея" not in person_keys
    assert "алекса" not in person_keys


def test_anchor_extraction_structures_event_identity_metadata() -> None:
    anchors = extract_observed_anchors(
        "Alex call 2 hours ago covered Project Atlas. "
        "Планерка с Сергеем на прошлой неделе по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex 2 hours ago"]
    assert call["anchor_family"] == "event"
    assert call["identity_scope"] == "event"
    assert call["identity_key"] == "event:call with aleks 2 hours ago"
    assert call["event_type"] == "call"
    assert call["event_participant_label"] == "alex"
    assert call["event_participant_canonical_key"] == "aleks"
    assert call["event_temporal_phrase"] == "2 hours ago"
    assert call["event_temporal_hint_code"] == "hours_ago"
    assert call["event_temporal_quantity"] == 2
    assert call["event_temporal_unit"] == "hour"
    assert call["event_identity_terms"] == ["call", "aleks", "hours_ago:2:hour"]

    planning = events["планерка с сергеем на прошлой неделе"]
    assert planning["event_type"] == "планерка"
    assert planning["event_participant_label"] == "сергеем"
    assert planning["event_participant_canonical_key"] == "sergei"
    assert planning["event_temporal_hint_code"] == "last_week"
    assert planning["event_identity_terms"] == [
        "planerka",
        "sergei",
        "last_week:1:week",
    ]


def test_anchor_extraction_structures_word_number_relative_week_events() -> None:
    anchors = extract_observed_anchors(
        "Alex call two weeks ago covered Project Atlas. "
        "Созвон с Сергеем две недели назад по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex two weeks ago"]
    assert call["event_temporal_phrase"] == "two weeks ago"
    assert call["event_temporal_hint_code"] == "weeks_ago"
    assert call["event_temporal_quantity"] == 2
    assert call["event_temporal_unit"] == "week"
    assert call["event_identity_terms"] == ["call", "aleks", "weeks_ago:2:week"]

    call_ru = events["созвон с сергеем две недели назад"]
    assert call_ru["event_temporal_phrase"] == "две недели назад"
    assert call_ru["event_temporal_hint_code"] == "weeks_ago"
    assert call_ru["event_temporal_quantity"] == 2
    assert call_ru["event_temporal_unit"] == "week"
    assert call_ru["event_identity_terms"] == [
        "sozvon",
        "sergei",
        "weeks_ago:2:week",
    ]


def test_anchor_extraction_structures_weekend_relative_events() -> None:
    anchors = extract_observed_anchors(
        "Caroline joined a mentorship program last weekend. "
        "Melanie went camping two weekends ago. "
        "Alex call this weekend covered Project Atlas."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    joined = events["joined with caroline last weekend"]
    assert joined["event_temporal_hint_code"] == "last_weekend"
    assert joined["event_temporal_quantity"] == 1
    assert joined["event_temporal_unit"] == "weekend"
    assert joined["event_identity_terms"] == ["joined", "caroline", "last_weekend:1:weekend"]

    camping = events["went with melanie two weekends ago"]
    assert camping["event_temporal_hint_code"] == "weekends_ago"
    assert camping["event_temporal_quantity"] == 2
    assert camping["event_temporal_unit"] == "weekend"
    assert camping["event_identity_terms"] == ["went", "melanie", "weekends_ago:2:weekend"]

    call = events["call with alex this weekend"]
    assert call["event_temporal_hint_code"] == "this_weekend"
    assert call["event_temporal_quantity"] == 0
    assert call["event_temporal_unit"] == "weekend"
    assert call["event_identity_terms"] == ["call", "aleks", "this_weekend:0:weekend"]


def test_anchor_extraction_structures_month_relative_events() -> None:
    anchors = extract_observed_anchors(
        "call with Alex two months ago covered Project Atlas. "
        "Созвон с Сергеем два месяца назад по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex two months ago"]
    assert call["event_temporal_phrase"] == "two months ago"
    assert call["event_temporal_hint_code"] == "months_ago"
    assert call["event_temporal_quantity"] == 2
    assert call["event_temporal_unit"] == "month"
    assert call["event_identity_terms"] == ["call", "aleks", "months_ago:2:month"]

    call_ru = events["созвон с сергеем два месяца назад"]
    assert call_ru["event_temporal_phrase"] == "два месяца назад"
    assert call_ru["event_temporal_hint_code"] == "months_ago"
    assert call_ru["event_temporal_quantity"] == 2
    assert call_ru["event_temporal_unit"] == "month"
    assert call_ru["event_identity_terms"] == [
        "sozvon",
        "sergei",
        "months_ago:2:month",
    ]


def test_anchor_extraction_structures_year_relative_events() -> None:
    anchors = extract_observed_anchors(
        "call with Alex four years ago covered Project Atlas. "
        "Созвон с Сергеем четыре года назад по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex four years ago"]
    assert call["event_temporal_phrase"] == "four years ago"
    assert call["event_temporal_hint_code"] == "years_ago"
    assert call["event_temporal_quantity"] == 4
    assert call["event_temporal_unit"] == "year"
    assert call["event_identity_terms"] == ["call", "aleks", "years_ago:4:year"]

    call_ru = events["созвон с сергеем четыре года назад"]
    assert call_ru["event_temporal_phrase"] == "четыре года назад"
    assert call_ru["event_temporal_hint_code"] == "years_ago"
    assert call_ru["event_temporal_quantity"] == 4
    assert call_ru["event_temporal_unit"] == "year"
    assert call_ru["event_identity_terms"] == [
        "sozvon",
        "sergei",
        "years_ago:4:year",
    ]


def test_anchor_extraction_structures_current_week_month_and_year_events() -> None:
    anchors = extract_observed_anchors(
        "call with Alex this week covered Project Atlas. "
        "planning with Dana this month covered Project Atlas. "
        "Созвон с Сергеем в этом году по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex this week"]
    assert call["event_temporal_phrase"] == "this week"
    assert call["event_temporal_hint_code"] == "this_week"
    assert call["event_temporal_quantity"] == 0
    assert call["event_temporal_unit"] == "week"
    assert call["event_identity_terms"] == ["call", "aleks", "this_week:0:week"]

    planning = events["planning with dana this month"]
    assert planning["event_temporal_phrase"] == "this month"
    assert planning["event_temporal_hint_code"] == "this_month"
    assert planning["event_temporal_quantity"] == 0
    assert planning["event_temporal_unit"] == "month"
    assert planning["event_identity_terms"] == ["planning", "dana", "this_month:0:month"]

    call_ru = events["созвон с сергеем в этом году"]
    assert call_ru["event_temporal_phrase"] == "в этом году"
    assert call_ru["event_temporal_hint_code"] == "this_year"
    assert call_ru["event_temporal_quantity"] == 0
    assert call_ru["event_temporal_unit"] == "year"
    assert call_ru["event_identity_terms"] == [
        "sozvon",
        "sergei",
        "this_year:0:year",
    ]


def test_anchor_extraction_structures_future_week_month_and_year_events() -> None:
    anchors = extract_observed_anchors(
        "call with Alex next week covered Project Atlas. "
        "planning with Dana next month covered Project Atlas. "
        "Созвон с Сергеем на следующий год по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    call = events["call with alex next week"]
    assert call["event_temporal_phrase"] == "next week"
    assert call["event_temporal_hint_code"] == "next_week"
    assert call["event_temporal_quantity"] == 1
    assert call["event_temporal_unit"] == "week"
    assert call["event_identity_terms"] == ["call", "aleks", "next_week:1:week"]

    planning = events["planning with dana next month"]
    assert planning["event_temporal_phrase"] == "next month"
    assert planning["event_temporal_hint_code"] == "next_month"
    assert planning["event_temporal_quantity"] == 1
    assert planning["event_temporal_unit"] == "month"

    call_ru = events["созвон с сергеем на следующий год"]
    assert call_ru["event_temporal_phrase"] == "на следующий год"
    assert call_ru["event_temporal_hint_code"] == "next_year"
    assert call_ru["event_temporal_quantity"] == 1
    assert call_ru["event_temporal_unit"] == "year"


def test_anchor_extraction_structures_future_workflow_deadline_events() -> None:
    anchors = extract_observed_anchors(
        "Project Atlas deadline tomorrow. Atlas is due next week. "
        "Поручение по Project Orion на следующий год."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    deadline = events["deadline for atlas tomorrow"]
    assert deadline["event_type"] == "deadline"
    assert deadline["event_has_participant"] is False
    assert deadline["event_project_canonical_key"] == "atlas"
    assert deadline["event_temporal_hint_code"] == "tomorrow"
    assert deadline["event_identity_terms"] == [
        "deadline",
        "atlas",
        "tomorrow:1:day",
    ]

    due = events["deadline for atlas next week"]
    assert due["event_type"] == "deadline"
    assert due["event_project_canonical_key"] == "atlas"
    assert due["event_temporal_hint_code"] == "next_week"

    task = events["поручение по orion на следующий год"]
    assert task["event_project_canonical_key"] == "orion"
    assert task["event_temporal_hint_code"] == "next_year"


def test_anchor_extraction_structures_absolute_date_workflow_events() -> None:
    anchors = extract_observed_anchors(
        "Project Atlas deadline 2026-08-15. Project Orion deadline 15.08.2026."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    atlas = events["deadline for atlas 2026-08-15"]
    assert atlas["event_project_canonical_key"] == "atlas"
    assert atlas["event_temporal_phrase"] == "2026-08-15"
    assert atlas["event_temporal_hint_code"] == "date_2026_08_15"
    assert atlas["event_date"] == "2026-08-15"
    assert atlas["event_identity_terms"] == [
        "deadline",
        "atlas",
        "date_2026_08_15",
    ]

    orion = events["deadline for orion 15.08.2026"]
    assert orion["event_project_canonical_key"] == "orion"
    assert orion["event_temporal_hint_code"] == "date_2026_08_15"
    assert orion["event_date"] == "2026-08-15"


def test_anchor_extraction_structures_quarter_events() -> None:
    anchors = extract_observed_anchors(
        "review with Maria this quarter covered Project Atlas. "
        "planning with John last quarter covered Project Atlas."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    review = events["review with maria this quarter"]
    assert review["event_temporal_phrase"] == "this quarter"
    assert review["event_temporal_hint_code"] == "this_quarter"
    assert review["event_temporal_quantity"] == 0
    assert review["event_temporal_unit"] == "quarter"
    assert review["event_identity_terms"] == ["review", "maria", "this_quarter:0:quarter"]

    last_quarter = events["planning with john last quarter"]
    assert last_quarter["event_temporal_phrase"] == "last quarter"
    assert last_quarter["event_temporal_hint_code"] == "last_quarter"
    assert last_quarter["event_temporal_quantity"] == 1
    assert last_quarter["event_temporal_unit"] == "quarter"
    assert last_quarter["event_identity_terms"] == ["planning", "john", "last_quarter:1:quarter"]


def test_anchor_extraction_handles_conversational_event_synonyms() -> None:
    anchors = extract_observed_anchors(
        "alex spoke two weeks ago about Project Atlas. "
        "Мария переписывалась с Сергеем две недели назад по Project Orion."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "spoke with alex about atlas two weeks ago" in events
    assert (
        events["spoke with alex about atlas two weeks ago"]["event_participant_canonical_key"]
        == "aleks"
    )
    assert events["spoke with alex about atlas two weeks ago"]["event_project_canonical_key"] == (
        "atlas"
    )
    assert events["spoke with alex about atlas two weeks ago"]["event_identity_terms"] == [
        "spoke",
        "aleks",
        "atlas",
        "weeks_ago:2:week",
    ]

    assert "переписывалась с сергеем по orion две недели назад" in events
    assert (
        events["переписывалась с сергеем по orion две недели назад"][
            "event_participant_canonical_key"
        ]
        == "sergei"
    )
    assert (
        events["переписывалась с сергеем по orion две недели назад"]["event_project_canonical_key"]
        == "orion"
    )
    assert events["переписывалась с сергеем по orion две недели назад"]["event_identity_terms"] == [
        "perepisyvalas",
        "sergei",
        "orion",
        "weeks_ago:2:week",
    ]


def test_anchor_extraction_structures_event_project_identity_metadata() -> None:
    anchors = extract_observed_anchors(
        "Call with Alex about Project Atlas 2 hours ago. Созвон с Марией вчера про backend."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "call with alex about atlas 2 hours ago" in events
    assert "call with alex 2 hours ago" in events
    assert "созвон с марией про backend вчера" in events
    call = events["call with alex about atlas 2 hours ago"]
    assert call["event_project_label"] == "atlas"
    assert call["event_project_relation"] == "about"
    assert call["event_project_canonical_key"] == "atlas"
    assert call["project_canonical_key"] == "atlas"
    assert call["event_identity_terms"] == [
        "call",
        "aleks",
        "atlas",
        "hours_ago:2:hour",
    ]

    russian = events["созвон с марией про backend вчера"]
    assert russian["event_project_label"] == "backend"
    assert russian["event_project_relation"] == "про"
    assert russian["event_project_canonical_key"] == "backend"
    assert russian["event_identity_terms"] == [
        "sozvon",
        "mariya",
        "backend",
        "yesterday:1:day",
    ]


def test_anchor_extraction_handles_lowercase_direct_event_participant_and_project() -> None:
    anchors = extract_observed_anchors(
        "call alex about atlas last week. созвон алекс по атлас неделю назад."
    )

    people = {
        (anchor.normalized_key, anchor.metadata.get("person_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "person"
    }
    projects = {
        (anchor.normalized_key, anchor.metadata.get("project_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "project"
    }
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert ("alex", "aleks") in people
    assert ("алекс", "aleks") in people
    assert ("atlas", "atlas") in projects
    assert ("атлас", "atlas") in projects
    assert "call with alex about atlas last week" in events
    assert events["call with alex about atlas last week"]["event_identity_terms"] == [
        "call",
        "aleks",
        "atlas",
        "last_week:1:week",
    ]
    assert "созвон с алекс по атлас неделю назад" in events
    assert events["созвон с алекс по атлас неделю назад"]["event_identity_terms"] == [
        "sozvon",
        "aleks",
        "atlas",
        "last_week:1:week",
    ]


def test_anchor_extraction_handles_lowercase_actor_before_message_event() -> None:
    anchors = extract_observed_anchors("alex wrote about atlas hour ago.")

    people = {
        (anchor.normalized_key, anchor.metadata.get("person_canonical_key"))
        for anchor in anchors
        if anchor.kind.value == "person"
    }
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert ("alex", "aleks") in people
    assert "wrote with alex about atlas hour ago" in events
    assert events["wrote with alex about atlas hour ago"]["event_participant_canonical_key"] == (
        "aleks"
    )
    assert events["wrote with alex about atlas hour ago"]["event_project_canonical_key"] == (
        "atlas"
    )
    assert events["wrote with alex about atlas hour ago"]["event_temporal_hint_code"] == (
        "hours_ago"
    )


def test_anchor_extraction_structures_partial_day_event_temporal_hints() -> None:
    anchors = extract_observed_anchors(
        "Alex wrote about Atlas earlier today. Созвон с Марией по Project Atlas сегодня утром."
    )

    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert "wrote with alex about atlas earlier today" in events
    wrote = events["wrote with alex about atlas earlier today"]
    assert wrote["event_participant_canonical_key"] == "aleks"
    assert wrote["event_project_canonical_key"] == "atlas"
    assert wrote["event_temporal_hint_code"] == "earlier_today"
    assert wrote["event_identity_terms"] == [
        "wrote",
        "aleks",
        "atlas",
        "earlier_today:0:day",
    ]

    assert "созвон с марией по atlas сегодня утром" in events
    call = events["созвон с марией по atlas сегодня утром"]
    assert call["event_participant_canonical_key"] == "mariya"
    assert call["event_project_canonical_key"] == "atlas"
    assert call["event_temporal_hint_code"] == "today_morning"
    assert call["event_identity_terms"] == [
        "sozvon",
        "mariya",
        "atlas",
        "today_morning:0:part_of_day",
    ]


def test_anchor_extraction_does_not_promote_temporal_or_topic_words_from_event_context() -> None:
    anchors = extract_observed_anchors(
        "the call last week covered notes. weekly sync yesterday. call about documents last week."
    )

    people = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    projects = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "project"}
    events = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "event"}

    assert people == set()
    assert projects == set()
    assert "call last week" in events
    assert "sync yesterday" in events
    assert "call with last last week" not in events
    assert "documents" not in projects


def test_anchor_extraction_normalizes_russian_locative_event_project() -> None:
    anchors = extract_observed_anchors("Созвон с Алексом в Атласе час назад про документы.")

    keys = {(anchor.kind.value, anchor.normalized_key) for anchor in anchors}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }

    assert ("project", "атлас") in keys
    assert events["созвон с алексом в атласе час назад"]["canonical_key"] == (
        "sozvon s aleks v atlas chas nazad"
    )
    assert events["созвон с алексом в атласе час назад"]["event_project_label"] == "атласе"
    assert events["созвон с алексом в атласе час назад"]["event_project_canonical_key"] == ("atlas")
    assert events["созвон с алексом в атласе час назад"]["event_identity_terms"] == [
        "sozvon",
        "aleks",
        "atlas",
        "hours_ago:1:hour",
    ]


def test_anchor_extraction_does_not_promote_russian_summary_word_to_person() -> None:
    anchors = extract_observed_anchors(
        "Итоги созвона: Алекс отвечает за поиск документов в Атласе."
    )

    person_keys = {anchor.normalized_key for anchor in anchors if anchor.kind.value == "person"}
    events = {
        anchor.normalized_key: anchor.metadata for anchor in anchors if anchor.kind.value == "event"
    }
    project_metadata = {
        anchor.normalized_key: anchor.metadata
        for anchor in anchors
        if anchor.kind.value == "project"
    }

    assert "итоги" not in person_keys
    assert "алекс" in person_keys
    assert "атлас" not in person_keys
    assert project_metadata["атлас"]["project_canonical_key"] == "atlas"
    assert events["созвон в атласе"]["event_project_canonical_key"] == "atlas"
    assert "event_participant_canonical_key" not in events["созвон в атласе"]


def test_anchor_extraction_structures_people_projects_and_organizations() -> None:
    anchors = extract_observed_anchors("Alex discussed Project Atlas with OpenAI team.")

    by_key = {(anchor.kind.value, anchor.normalized_key): anchor.metadata for anchor in anchors}

    assert by_key[("person", "alex")]["identity_scope"] == "person"
    assert by_key[("person", "alex")]["identity_key"] == "person:aleks"
    assert by_key[("person", "alex")]["person_canonical_key"] == "aleks"
    assert by_key[("project", "atlas")]["identity_scope"] == "project"
    assert by_key[("project", "atlas")]["identity_key"] == "project:atlas"
    assert by_key[("project", "atlas")]["project_canonical_key"] == "atlas"
    assert by_key[("organization", "openai")]["identity_key"] == "organization:openai"
    assert by_key[("organization", "openai")]["organization_canonical_key"] == "openai"
