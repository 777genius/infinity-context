from memo_stack_core.application.anchor_extraction import extract_observed_anchors


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
    assert ("event", "созвон с марией вчера") in keys
    assert ("event", "созвон вчера") in keys
    assert canonical_keys["созвон с марией вчера"] == "sozvon s mariya vchera"


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
    assert ("алексом", "aleks") in person_keys
    assert ("марией", "mariya") in person_keys
    assert "переписывался с алексом час назад" in event_keys
    assert "созвон с марией вчера" in event_keys
