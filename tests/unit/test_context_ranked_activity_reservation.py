from __future__ import annotations

from infinity_context_core.application.context_ranked_activity_reservation import (
    activity_inventory_evidence_slots,
    activity_inventory_query_supported,
    activity_inventory_slot_key,
    reserve_activity_inventory_head,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _item(index: int, text: str, *, referenced: bool = True) -> ContextItem:
    return ContextItem(
        item_id=f"candidate-{index}",
        item_type="chunk",
        text=text,
        score=1.0 - index / 100,
        source_refs=(
            (SourceRef(source_type="episode", source_id=f"session:D1:{index}"),)
            if referenced
            else ()
        ),
    )


def test_activity_reservation_keeps_unrelated_queries_unchanged() -> None:
    items = (
        _item(1, "D1:1 Riley: I joined a glassblowing class."),
        _item(2, "D1:2 Jordan: I went birdwatching."),
    )

    result = reserve_activity_inventory_head(items, query="Where does Riley live?")

    assert result is items


def test_activity_reservation_prioritizes_owned_distinct_slots_stably() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    wrong_owner = _item(2, "D1:2 Jordan: I joined a glassblowing class.")
    glassblowing = _item(3, "D1:3 Riley: I took a glassblowing class.")
    duplicate = _item(4, "D1:4 Riley: I returned to my glassblowing class.")
    birdwatching = _item(5, "D1:5 Riley: We went birdwatching near the wetlands.")
    visual = _item(
        6,
        "D1:6 Riley: Here's a photo from my woodworking workshop.",
    )
    items = (noise, wrong_owner, glassblowing, duplicate, birdwatching, visual)

    result = reserve_activity_inventory_head(
        items,
        query="What activities has Riley done?",
    )

    assert result[:3] == (glassblowing, birdwatching, visual)
    assert result[3:] == (noise, wrong_owner, duplicate)


def test_activity_reservation_requires_direct_or_visual_owner_evidence() -> None:
    third_person = _item(
        1,
        "D1:1 Riley: My cousin joined a sailing club.",
    )
    unsupported = _item(
        2,
        "D1:2 Riley: I joined a fencing class.",
        referenced=False,
    )
    direct = _item(3, "D1:3 Riley: I joined a rowing club.")
    items = (third_person, unsupported, direct)

    result = reserve_activity_inventory_head(
        items,
        query="Which activities does Riley participate in?",
    )

    assert result == (direct, third_person, unsupported)


def test_activity_reservation_is_bounded_to_eight_syntax_derived_slots() -> None:
    labels = (
        "glassblowing",
        "birdwatching",
        "woodworking",
        "sailing",
        "knitting",
        "sculpting",
        "fencing",
        "baking",
        "rowing",
    )
    activities = tuple(
        _item(index + 10, f"D2:{index} Riley: I joined a {label} class.")
        for index, label in enumerate(labels, start=1)
    )
    noise = tuple(
        _item(index, f"D1:{index} Jordan: General memory {index}.") for index in range(1, 4)
    )
    items = (*noise, *activities)

    result = reserve_activity_inventory_head(
        items,
        query="List all activities Riley has done.",
    )

    assert result[:8] == activities[:8]
    assert result[8:] == (*noise, activities[8])


def test_activity_reservation_does_not_infer_an_owner_from_generic_inventory() -> None:
    items = (_item(1, "D1:1 Riley: I joined a rowing club."),)

    result = reserve_activity_inventory_head(
        items,
        query="What activities are available?",
    )

    assert result is items


def test_activity_reservation_accepts_bracketed_visual_query_label() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    visual = _item(
        2,
        (
            "D1:2 Riley: [Sharing image - query: woodcarving. "
            "The image shows a cedar bird and carving tools]"
        ),
    )

    result = reserve_activity_inventory_head(
        (noise, visual),
        query="What activities has Riley done?",
    )

    assert result == (visual, noise)


def test_activity_reservation_dedupes_visual_query_before_caption_objects() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    first = _item(
        2,
        (
            "D1:2 Riley: [Sharing image - query: sketching. "
            "The image shows a lighthouse and charcoal pencils]"
        ),
    )
    caption_variant = _item(
        3,
        (
            "D1:3 Riley: [Sharing image - query: sketching. "
            "The image shows a bicycle and city buildings]"
        ),
    )
    other = _item(4, "D1:4 Riley: We went stargazing after sunset.")

    result = reserve_activity_inventory_head(
        (noise, first, caption_variant, other),
        query="What activities has Riley done?",
    )

    assert result == (first, other, noise, caption_variant)


def test_activity_reservation_rejects_possessive_direct_object_as_slot() -> None:
    items = (
        _item(1, "D1:1 Jordan: General memory."),
        _item(
            2,
            (
                "D1:2 Riley: I took my kids to a park after lunch. "
                "[Sharing image - query: kids at a park. The image shows a playground]"
            ),
        ),
    )

    result = reserve_activity_inventory_head(
        items,
        query="What activities has Riley done?",
    )

    assert result is items


def test_activity_reservation_rejects_arbitrary_visual_search_subjects() -> None:
    subjects = (
        "kids at a park",
        "family portrait",
        "how to draw",
        "outdoor scene",
        "painted portrait",
        "live talent show",
        "me at a concert",
    )
    items = tuple(
        _item(
            index,
            (
                f"D2:{index} Riley: [Sharing image - query: {subject}. "
                "The image shows unrelated caption objects]"
            ),
        )
        for index, subject in enumerate(subjects, start=1)
    )

    result = reserve_activity_inventory_head(
        items,
        query="What activities has Riley done?",
    )

    assert result is items


def test_activity_reservation_uses_first_visual_ing_form() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    hiking = _item(
        2,
        "D1:2 Riley: [Sharing image - query: family hiking trail. A wooded ridge]",
    )
    painting = _item(
        3,
        "D1:3 Riley: [Sharing image - query: painting sunrise. A bright horizon]",
    )

    result = reserve_activity_inventory_head(
        (noise, hiking, painting),
        query="What activities has Riley done?",
    )

    assert result == (hiking, painting, noise)


def test_activity_reservation_keeps_distinct_semantic_activity_head() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    visual_only_pottery = _item(
        2,
        "D1:2 Riley: [Sharing image - query: pottery bowl. A glazed vessel]",
    )
    possessive_object = _item(
        3,
        (
            "D1:3 Riley: I took my kids to a park. "
            "[Sharing image - query: kids outdoors. A playground]"
        ),
    )
    camping = _item(
        4,
        (
            "D1:4 Riley: We went camping by the lake. "
            "[Sharing image - query: outdoor lake. A tent beside water]"
        ),
    )
    pottery = _item(
        5,
        (
            "D1:5 Riley: I took a pottery class. "
            "[Sharing image - query: pottery bowl. A glazed vessel]"
        ),
    )
    painting = _item(
        6,
        (
            "D1:6 Riley: [Sharing image - query: family painting sunrise. "
            "The image shows a blue vase and several brushes]"
        ),
    )
    swimming = _item(
        7,
        (
            "D1:7 Riley: I'm off to go swimming. "
            "[Sharing image - query: how the pool looks. Blue water]"
        ),
    )
    items = (
        noise,
        visual_only_pottery,
        possessive_object,
        camping,
        pottery,
        painting,
        swimming,
    )

    result = reserve_activity_inventory_head(
        items,
        query="What activities has Riley done?",
    )

    assert result[:4] == (camping, pottery, painting, swimming)
    assert result[4:] == (noise, visual_only_pottery, possessive_object)


def test_activity_reservation_does_not_let_visual_decoys_exhaust_distinct_head() -> None:
    visual_decoys = tuple(
        _item(
            index,
            (
                f"D1:{index} Riley: I took my kids to the park. "
                f"[Sharing image - query: kids {label}. A family photo]"
            ),
        )
        for index, label in enumerate(
            (
                "climbing",
                "painting",
                "skating",
                "sailing",
                "hiking",
                "swimming",
                "camping",
                "cycling",
            ),
            start=1,
        )
    )
    pottery = _item(20, "D2:1 Riley: I took a pottery class.")
    stargazing = _item(21, "D2:2 Riley: I'm off to go stargazing.")

    result = reserve_activity_inventory_head(
        (*visual_decoys, pottery, stargazing),
        query="What activities has Riley done?",
    )

    assert result[:2] == (pottery, stargazing)
    assert result[2:] == visual_decoys


def test_activity_reservation_accepts_auxiliary_off_to_go_syntax() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    direct = _item(
        2,
        "D1:2 Riley: I'm off to go stargazing tonight.",
    )

    result = reserve_activity_inventory_head(
        (noise, direct),
        query="What activities has Riley done?",
    )

    assert result == (direct, noise)


def test_activity_reservation_bounds_adversarial_item_analysis() -> None:
    noise = _item(1, "D1:1 Jordan: General memory.")
    long_invalid_header = "D9:9 " + ("A " * 100_000)
    activity_beyond_bound = "D9:10 Riley: I'm off to go stargazing."
    adversarial = _item(2, long_invalid_header + activity_beyond_bound)
    items = (noise, adversarial)

    result = reserve_activity_inventory_head(
        items,
        query="What activities has Riley done?",
    )

    assert result is items


def test_activity_inventory_public_support_extracts_only_owned_direct_slots() -> None:
    query = "What activities does Riley partake in?"
    text = (
        "D1:1 Jordan: I went painting with friends. "
        "D1:2 Riley: We went camping by the lake. "
        "D1:3 Riley: I took a pottery class. "
        "D1:4 Riley: I'm off to go swimming."
    )

    assert activity_inventory_query_supported(query) is True
    assert activity_inventory_evidence_slots(query=query, text=text) == (
        "camping",
        "pottery",
        "swimming",
    )


def test_activity_inventory_public_support_requires_named_owner_and_direct_evidence() -> None:
    query = "What activities has Riley done?"

    assert activity_inventory_query_supported("What activities were mentioned?") is False
    assert (
        activity_inventory_evidence_slots(
            query=query,
            text="D1:1 Jordan: I went painting. D1:2 Riley: Jordan went camping.",
        )
        == ()
    )


def test_activity_inventory_public_support_uses_stable_generic_slot_keys() -> None:
    assert activity_inventory_slot_key("rock climbing") == "climbing"
    assert activity_inventory_slot_key("  Pottery  ") == "pottery"


def test_activity_inventory_public_support_rejects_unowned_visual_caption_slot() -> None:
    query = "What activities has Riley done?"
    child_activity = (
        "D1:1 Riley: I took my kids to a park. They had fun exploring. "
        "[Sharing image - query: kids climbing jungle gym park. A playground]"
    )
    owned_activity = (
        "D1:2 Riley: Painting landscapes is my favorite. "
        "Here's a painting I did recently. "
        "[Sharing image - query: painting field sunflowers. A canvas]"
    )

    assert (
        activity_inventory_evidence_slots(
            query=query,
            text=child_activity,
        )
        == ()
    )
    assert activity_inventory_evidence_slots(
        query=query,
        text=owned_activity,
    ) == ("painting",)


def test_activity_inventory_uses_primary_subject_not_relational_companion() -> None:
    query = "What activities did Riley do with Jordan?"
    text = "D1:1 Jordan: I went camping. D1:2 Riley: I started swimming."

    assert activity_inventory_query_supported(query) is True
    assert activity_inventory_evidence_slots(query=query, text=text) == ("swimming",)


def test_activity_reservation_does_not_promote_relational_companion_evidence() -> None:
    companion = _item(1, "D1:1 Jordan: I went camping.")
    owner = _item(2, "D1:2 Riley: I started swimming.")

    result = reserve_activity_inventory_head(
        (companion, owner),
        query="What activities did Riley do with Jordan?",
    )

    assert result == (owner, companion)


def test_activity_inventory_ignores_all_image_marker_and_caption_content() -> None:
    query = "What activities has Riley done?"
    manufactured = (
        "D1:1 Riley: [Sharing image - query: pottery class. "
        "I started swimming. D1:2 Jordan: I went camping.]"
    )

    assert activity_inventory_evidence_slots(query=query, text=manufactured) == ()


def test_activity_inventory_keeps_direct_owner_support_outside_image_payload() -> None:
    query = "What activities has Riley done?"
    direct_then_image = (
        "D1:1 Riley: I started painting. "
        "[Sharing image - query: kids swimming. D1:2 Jordan: I went camping.]"
    )

    assert activity_inventory_evidence_slots(
        query=query,
        text=direct_then_image,
    ) == ("painting",)


def test_activity_inventory_rejects_name_and_activity_from_image_query() -> None:
    assert (
        activity_inventory_evidence_slots(
            query="What activities has Riley done?",
            text=("D1:1 Riley: [Sharing image - query: Jordan climbing class. A gym photo]"),
        )
        == ()
    )


def test_activity_inventory_does_not_attribute_companion_action_to_speaker() -> None:
    assert (
        activity_inventory_evidence_slots(
            query="What activities has Riley done?",
            text=(
                "D1:1 Riley: My kids waved while Jordan tried climbing. "
                "[Sharing image - query: climbing wall. A gym photo]"
            ),
        )
        == ()
    )
