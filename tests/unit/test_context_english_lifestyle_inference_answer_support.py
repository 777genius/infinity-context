from infinity_context_core.application.context_english_lifestyle_inference_answer_support import (
    english_lifestyle_inference_turn_candidates,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_lifestyle_inference_keeps_indoor_activity_and_pet_context() -> None:
    cooking = _lifestyle_item(
        "cooking",
        (
            "D4:2 Alex: Since I can't hike much lately, I've been getting into "
            "cooking and trying new recipes. It has been enjoyable."
        ),
        source_id="locomo:fixture:session_4:D4:2:turn",
        score=0.9,
    )
    puppy = _lifestyle_item(
        "puppy",
        (
            "D5:1 Alex: Meet Toby, my new puppy. He's a bundle of joy and I "
            "couldn't resist taking him home, city living and all."
        ),
        source_id="locomo:fixture:session_5:D5:1:turn",
        score=0.89,
    )
    dog_park_noise = _lifestyle_item(
        "dog_park_noise",
        "D9:3 Alex: The indoor dog park was busy and the dogs chased a ball.",
        source_id="locomo:fixture:session_9:D9:3:turn",
        score=0.99,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_indoor_pet_activity",
        items=(dog_park_noise, puppy, cooking),
        query="What is an indoor activity Alex would enjoy doing while making his dog happy?",
        token_budget=180,
        max_rendered_chars=900,
    )

    rendered = result.bundle.rendered_text
    assert "D4:2" in rendered
    assert "cooking and trying new recipes" in rendered
    assert "D5:1" in rendered
    assert "new puppy" in rendered


def test_lifestyle_inference_keeps_stress_and_city_outdoor_constraints() -> None:
    work_stress = _lifestyle_item(
        "work_stress",
        (
            "D7:3 Alex: Work has been piling up and I've been stuck inside. "
            "I miss the peace and feeling of freedom that comes with hiking."
        ),
        source_id="locomo:fixture:session_7:D7:3:turn",
        score=0.89,
    )
    city_space = _lifestyle_item(
        "city_space",
        (
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance."
        ),
        source_id="locomo:fixture:session_8:D8:5:turn",
        score=0.88,
    )
    dog_bed_noise = _lifestyle_item(
        "dog_bed_noise",
        "D9:4 Alex: The dogs love the new beds in the apartment.",
        source_id="locomo:fixture:session_9:D9:4:turn",
        score=0.99,
    )

    candidates = english_lifestyle_inference_turn_candidates(
        [dog_bed_noise, work_stress, city_space],
        query=(
            "What can Alex do to improve his stress and accommodate his living "
            "situation with his dogs?"
        ),
        limit=4,
    )

    assert tuple(item.item_id for item in candidates) == ("work_stress", "city_space")


def test_lifestyle_inference_focuses_supported_marker_in_multi_ref_item() -> None:
    mixed_window = _lifestyle_item(
        "mixed_window",
        (
            "D7:1 Alex: The dogs liked their new beds in the apartment.\n"
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance.\n"
            "D9:4 Alex: The dogs ate dinner and took a nap."
        ),
        source_id="locomo:fixture:session_8:D7:1:turn",
        source_ids=(
            "locomo:fixture:session_8:D7:1:turn",
            "locomo:fixture:session_8:D8:5:turn",
            "locomo:fixture:session_8:D9:4:turn",
        ),
        score=0.99,
    )
    unrelated_city_dogs = _lifestyle_item(
        "unrelated_city_dogs",
        "D3:1 Alex: The dogs slept in the apartment after a walk downtown.",
        source_id="locomo:fixture:session_3:D3:1:turn",
        score=1.0,
    )

    candidates = english_lifestyle_inference_turn_candidates(
        [unrelated_city_dogs, mixed_window],
        query=(
            "What can Alex do to improve his stress and accommodate his living "
            "situation with his dogs?"
        ),
        limit=2,
    )

    assert len(candidates) == 1
    assert candidates[0].source_refs[0].source_id == "locomo:fixture:session_8:D8:5:turn"
    assert "D8:5" in candidates[0].text
    assert "D7:1" not in candidates[0].text
    assert "D9:4" not in candidates[0].text


def test_lifestyle_inference_rejects_cross_turn_combined_support() -> None:
    mixed_window = _lifestyle_item(
        "mixed_window",
        (
            "D7:1 Alex: The dogs liked their new beds in the apartment.\n"
            "D8:5 Alex: It's hard to find open spaces in the city.\n"
            "D9:4 Alex: I used to hike a lot on weekends."
        ),
        source_id="locomo:fixture:session_8:D7:1:turn",
        source_ids=(
            "locomo:fixture:session_8:D7:1:turn",
            "locomo:fixture:session_8:D8:5:turn",
            "locomo:fixture:session_8:D9:4:turn",
        ),
        score=0.99,
    )

    candidates = english_lifestyle_inference_turn_candidates(
        [mixed_window],
        query=(
            "What can Alex do to improve his stress and accommodate his living "
            "situation with his dogs?"
        ),
        limit=2,
    )

    assert candidates == ()


def test_lifestyle_inference_prioritizes_living_constraint_over_generic_nature() -> None:
    generic_city_nature = _lifestyle_item(
        "generic_city_nature",
        (
            "D4:1 Alex: Living in the city, I miss nature a lot. Whenever I "
            "can, I try nearby parks or hikes because it feels peaceful."
        ),
        source_id="locomo:fixture:session_4:D4:1:turn",
        score=1.0,
    )
    living_constraint = _lifestyle_item(
        "living_constraint",
        (
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance."
        ),
        source_id="locomo:fixture:session_8:D8:5:turn",
        score=0.88,
    )

    candidates = english_lifestyle_inference_turn_candidates(
        [generic_city_nature, living_constraint],
        query=(
            "What can Alex do to improve his stress and accommodate his living "
            "situation with his dogs?"
        ),
        limit=2,
    )

    assert tuple(item.item_id for item in candidates) == (
        "living_constraint",
        "generic_city_nature",
    )


def test_lifestyle_inference_keeps_animal_and_nature_career_evidence() -> None:
    dog_nature = _lifestyle_item(
        "dog_nature",
        (
            "D2:6 Alex: My family's dog made hiking trails peaceful, and I "
            "miss exploring nature with a dog."
        ),
        source_id="locomo:fixture:session_2:D2:6:turn",
        score=0.9,
    )
    city_nature = _lifestyle_item(
        "city_nature",
        (
            "D3:1 Alex: The cafe in the city was fun, but I was sad not being "
            "out in nature. That is where I really thrive."
        ),
        source_id="locomo:fixture:session_3:D3:1:turn",
        score=0.89,
    )
    nature_reset = _lifestyle_item(
        "nature_reset",
        "D8:7 Alex: Whenever I need a reset, I turn to nature for a new outlook.",
        source_id="locomo:fixture:session_8:D8:7:turn",
        score=0.88,
    )
    ecology_noise = _lifestyle_item(
        "ecology_noise",
        "D9:3 Alex: I read about animals, plants, and ecosystems.",
        source_id="locomo:fixture:session_9:D9:3:turn",
        score=0.99,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_animal_nature_career",
        items=(ecology_noise, nature_reset, city_nature, dog_nature),
        query="What is a career Alex could pursue with his love for animals and nature?",
        token_budget=320,
        max_rendered_chars=1600,
    )

    rendered = result.bundle.rendered_text
    assert "D2:6" in rendered
    assert "hiking trails" in rendered
    assert "D3:1" in rendered
    assert "really thrive" in rendered
    assert "D8:7" in rendered
    assert "turn to nature" in rendered


def _lifestyle_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    source_ids: tuple[str, ...] = (),
    score: float,
) -> ContextItem:
    refs = source_ids or (source_id,)
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            *(
                SourceRef(
                    source_type="locomo_turn",
                    source_id=ref_source_id,
                    chunk_id=item_id,
                )
                for ref_source_id in refs
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "query_expansion_reason": "decomposition_inference_support",
        },
    )
