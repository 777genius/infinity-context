from infinity_context_core.application.anchor_extraction import (
    extract_observed_anchors,
    structured_anchor_metadata_for_label,
)
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
