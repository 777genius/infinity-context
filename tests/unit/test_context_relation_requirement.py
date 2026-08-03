from infinity_context_core.application.context_relation_requirement import (
    _relation_requirement,
    relation_requirement_signal,
)


def test_relation_requirement_matches_direct_mention_evidence() -> None:
    signal = relation_requirement_signal(
        query="Did Alex ever mention Project Atlas?",
        text="D3:4 Alex: I mentioned Project Atlas during the billing call.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "relation_requirement_match"


def test_relation_requirement_extracts_owner_from_coordinated_intent_subject() -> None:
    requirement = _relation_requirement("When did Sam and his friend decide to try kayaking?")

    assert requirement is not None
    assert requirement.subject.raw == "Sam"
    assert requirement.group.key == "use"


def test_relation_requirement_matches_compact_direct_speaker_mention() -> None:
    signal = relation_requirement_signal(
        query="When did Alex mention Project Atlas?",
        text=(
            "session date: 3 March, 2025\nD3:4 Alex: Project Atlas is ready for the billing review!"
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "relation_requirement_match"


def test_relation_requirement_does_not_infer_mention_from_other_speaker() -> None:
    signal = relation_requirement_signal(
        query="When did Alex mention Project Atlas?",
        text="D3:4 Dana: Alex showed me Project Atlas during the review.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_missing_relation"


def test_relation_requirement_does_not_infer_mention_from_broad_dialogue() -> None:
    signal = relation_requirement_signal(
        query="When did Alex mention Project Atlas?",
        text=("D3:3 Dana: Alex joined the review.\nD3:4 Alex: Project Atlas is ready."),
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_missing_relation"


def test_relation_requirement_matches_compact_anaphoric_use_relation() -> None:
    signal = relation_requirement_signal(
        query="When did Sam and his friend decide to try kayaking?",
        text=(
            "session date: 14 October, 2023\n"
            "D13:10 Sam: My mate and I are by the lake after talking about "
            "kayaking, and we are going to try that now!"
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "relation_requirement_match"


def test_relation_requirement_does_not_infer_use_from_other_speaker() -> None:
    signal = relation_requirement_signal(
        query="When did Sam and his friend decide to try kayaking?",
        text=("D13:10 Evan: Sam and his friend discussed kayaking, and I will try it later."),
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_missing_relation"


def test_relation_requirement_penalizes_anchor_only_mention_decoy() -> None:
    signal = relation_requirement_signal(
        query="Did Alex ever mention Project Atlas?",
        text="Alex and Project Atlas appeared in the planning summary.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_missing_relation"


def test_relation_requirement_accepts_named_object_without_generic_descriptor() -> None:
    signal = relation_requirement_signal(
        query="Did Alex ever mention Project Atlas?",
        text="Alex mentioned Atlas during the billing call.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "relation_requirement_match"


def test_relation_requirement_penalizes_wrong_named_object() -> None:
    signal = relation_requirement_signal(
        query="Did Alex ever mention Project Atlas?",
        text="Alex mentioned Project Apollo during the billing call.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_object_mismatch"


def test_relation_requirement_matches_russian_mention_query() -> None:
    signal = relation_requirement_signal(
        query="Алекс упоминал Project Atlas?",
        text="Алекс упоминал Атлас на созвоне по биллингу.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "relation_requirement_match"


def test_relation_requirement_penalizes_russian_wrong_object() -> None:
    signal = relation_requirement_signal(
        query="Алекс упоминал Project Atlas?",
        text="Алекс упоминал Project Apollo на созвоне.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "relation_requirement_object_mismatch"


def test_relation_requirement_accepts_negative_possession_evidence() -> None:
    signal = relation_requirement_signal(
        query="Is there any evidence that Alex has a cat?",
        text="No evidence mentions Alex having a cat.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0


def test_relation_requirement_penalizes_possession_anchor_decoy() -> None:
    signal = relation_requirement_signal(
        query="Is there any evidence that Alex has a cat?",
        text="Alex visited the Cat Cafe after the billing call.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0


def test_relation_requirement_ignores_queries_without_object_target() -> None:
    signal = relation_requirement_signal(
        query="What items has Melanie bought?",
        text="Melanie bought family figurines yesterday.",
    )

    assert signal == (0.0, 0.0, "")
