from infinity_context_core.application.context_food_inventory_exact_turns import (
    exact_food_inventory_turn_candidates,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_food_inventory_exact_turns_infer_visible_recipe_markers() -> None:
    anchored_chunk = _food_item(
        "anchored_chunk",
        (
            "D10:9 Riley: I have been testing out dairy-free dessert recipes "
            "for friends and family. Here's a pic of a cake I made recently! "
            "D10:10 Morgan: That looks really good. "
            "D10:11 Riley: Thanks! It's dairy-free vanilla with strawberry "
            "filling and coconut cream frosting."
        ),
        source_id="locomo:conv-fixture:session_10:D10:10:turn",
    )

    selected = exact_food_inventory_turn_candidates(
        (anchored_chunk,),
        query="What recipes has Riley made?",
        limit=4,
    )

    selected_source_ids = {str(item.source_refs[0].source_id) for item in selected}
    assert "locomo:conv-fixture:session_10:D10:9:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_10:D10:11:turn" in selected_source_ids
    assert any("testing out dairy-free dessert recipes" in item.text for item in selected)
    assert any("dairy-free vanilla with strawberry" in item.text for item in selected)


def test_food_inventory_exact_turns_keep_setup_and_recipe_continuation() -> None:
    session_summary = _food_item(
        "session_summary",
        (
            "D21:3 Riley: I finished backing up my work. So, how have you "
            "been? Making anything cool? "
            "D21:16 Morgan: Yum, any others you want to share? "
            "D21:17 Riley: Here's another recipe I like. It's a delicious "
            "dessert made with blueberries, coconut milk, and a gluten-free crust."
        ),
        source_id="locomo:conv-fixture:session_21:events",
    )

    selected = exact_food_inventory_turn_candidates(
        (session_summary,),
        query="What recipes has Riley made?",
        limit=4,
    )

    selected_source_ids = {str(item.source_refs[0].source_id) for item in selected}
    assert "locomo:conv-fixture:session_21:D21:3:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_21:D21:17:turn" in selected_source_ids
    assert any("Making anything cool" in item.text for item in selected)
    assert any("another recipe I like" in item.text for item in selected)


def test_food_inventory_source_sibling_keeps_setup_prompt_as_answer_evidence() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Riley recipes made dessert recipe",
        expansion_reason="decomposition_inventory_list",
        text=(
            "D21:3 Riley: I never want to go through this again. "
            "So, how have you been? Making anything cool?"
        ),
    )


def test_food_inventory_exact_turns_demote_aspirational_recipe_comments() -> None:
    aspirational = _food_item(
        "aspirational",
        "D8:16 Riley: I love your ice cream so much! I wish I could make it the way you do!",
        source_id="locomo:conv-fixture:session_8:D8:16:turn",
        score=0.99,
    )
    interested = _food_item(
        "interested",
        (
            "D8:20 Riley: Riley is interested in trying Morgan's dairy-free "
            "ice cream recipe made with coconut milk and vanilla."
        ),
        source_id="locomo:conv-fixture:session_8:D8:20:turn",
        score=0.98,
    )
    setup = _food_item(
        "setup",
        "D21:3 Riley: So, how have you been? Making anything cool?",
        source_id="locomo:conv-fixture:session_21:D21:3:turn",
        score=0.72,
    )

    selected = exact_food_inventory_turn_candidates(
        (aspirational, interested, setup),
        query="What recipes has Riley made?",
        limit=3,
    )

    selected_ids = [item.item_id for item in selected]
    assert "setup" in selected_ids
    assert "aspirational" not in selected_ids
    assert "interested" not in selected_ids


def test_context_packer_keeps_recipe_inventory_details_before_broad_food_noise() -> None:
    broad_noise = tuple(
        _food_item(
            f"broad_food_{index}",
            (
                f"D{index}:2 Riley talked about desserts, cooking plans, "
                "and favorite recipe ideas in general. " + ("food context " * 12)
            ),
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            score=0.99 - index * 0.001,
        )
        for index in range(30, 36)
    )
    recipe_chunk = _food_item(
        "recipe_chunk",
        (
            "D10:9 Riley: I have been testing out dairy-free dessert recipes "
            "for friends and family. Here's a pic of a cake I made recently! "
            "D10:10 Morgan: That looks really good. "
            "D10:11 Riley: Thanks! It's dairy-free vanilla with strawberry "
            "filling and coconut cream frosting."
        ),
        source_id="locomo:conv-fixture:session_10:D10:10:turn",
        score=0.72,
    )
    continuation_chunk = _food_item(
        "continuation_chunk",
        (
            "D21:3 Riley: So, how have you been? Making anything cool? "
            "D21:17 Riley: Here's another recipe I like. It's a delicious "
            "dessert made with blueberries, coconut milk, and a gluten-free crust."
        ),
        source_id="locomo:conv-fixture:session_21:events",
        score=0.71,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_recipe_inventory_details",
        items=(*broad_noise, recipe_chunk, continuation_chunk),
        query="What recipes has Riley made?",
        token_budget=900,
        max_rendered_chars=1800,
    )

    rendered = result.bundle.rendered_text
    assert "D10:9 Riley: I have been testing out dairy-free dessert recipes" in rendered
    assert "D10:11 Riley: Thanks! It's dairy-free vanilla" in rendered
    assert "D21:3 Riley: So, how have you been? Making anything cool?" in rendered
    assert "D21:17 Riley: Here's another recipe I like" in rendered


def test_context_packer_keeps_large_recipe_inventory_under_noise() -> None:
    noise = tuple(
        _food_item(
            f"food_noise_{index}",
            (
                f"D{index}:2 Riley and Morgan talked about dessert ideas, "
                "recipes, cooking, and favorite food in general. "
                + ("general context " * 8)
            ),
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            score=0.99 - index * 0.001,
        )
        for index in range(30, 42)
    )
    recipe_turns = (
        _food_item(
            "cake_setup",
            (
                "D10:9 Riley: I have been testing out dairy-free dessert recipes "
                "for friends and family. Here's a pic of a cake I made recently!"
            ),
            source_id="locomo:conv-fixture:session_10:D10:9:turn",
            score=0.71,
        ),
        _food_item(
            "cake_detail",
            (
                "D10:11 Riley: It's dairy-free vanilla with strawberry "
                "filling and coconut cream frosting."
            ),
            source_id="locomo:conv-fixture:session_10:D10:11:turn",
            score=0.7,
        ),
        _food_item(
            "parfait",
            (
                "D19:8 Riley: I celebrated by making this delicious treat - yum! "
                "image caption: two desserts with chocolate. "
                "visual query: raspberry chia pudding parfait dessert."
            ),
            source_id="locomo:conv-fixture:session_19:D19:8:turn",
            score=0.69,
        ),
        _food_item(
            "revised_recipe",
            "D20:2 Riley: I just revised one of my old recipes and made this!",
            source_id="locomo:conv-fixture:session_20:D20:2:turn",
            score=0.68,
        ),
        _food_item(
            "cupcakes",
            (
                "D20:10 Riley: I made these dairy-free chocolate coconut "
                "cupcakes with raspberry frosting."
            ),
            source_id="locomo:conv-fixture:session_20:D20:10:turn",
            score=0.67,
        ),
        _food_item(
            "continuation_prompt",
            (
                "D21:3 Riley: I never want to go through this again. "
                "So, how have you been? Making anything cool?"
            ),
            source_id="locomo:conv-fixture:session_21:D21:3:turn",
            score=0.66,
        ),
        _food_item(
            "tart",
            (
                "D21:11 Riley: My favorite dairy-free treat is this amazing "
                "chocolate raspberry tart with almond flour crust."
            ),
            source_id="locomo:conv-fixture:session_21:D21:11:turn",
            score=0.65,
        ),
        _food_item(
            "blueberry_recipe",
            (
                "D21:17 Riley: Here's another recipe I like. It's a delicious "
                "dessert made with blueberries, coconut milk, and a gluten-free crust."
            ),
            source_id="locomo:conv-fixture:session_21:D21:17:turn",
            score=0.64,
        ),
        _food_item(
            "newest_recipe",
            (
                "D22:1 Riley: Yesterday, I tried my newest dairy-free recipe "
                "and it was a winner with my family!"
            ),
            source_id="locomo:conv-fixture:session_22:D22:1:turn",
            score=0.63,
        ),
    )

    result = ContextPacker().pack(
        bundle_id="ctx_large_recipe_inventory",
        items=(*noise, *recipe_turns),
        query="What recipes has Riley made?",
        token_budget=1600,
        max_rendered_chars=3200,
    )

    rendered = result.bundle.rendered_text
    assert "D10:9 Riley: I have been testing out dairy-free dessert recipes" in rendered
    assert "D10:11 Riley: It's dairy-free vanilla" in rendered
    assert "D19:8 Riley: I celebrated by making this delicious treat" in rendered
    assert "D20:2 Riley: I just revised one of my old recipes" in rendered
    assert "D20:10 Riley: I made these dairy-free chocolate coconut cupcakes" in rendered
    assert "D21:3 Riley: I never want to go through this again" in rendered
    assert "D21:11 Riley: My favorite dairy-free treat" in rendered
    assert "D21:17 Riley: Here's another recipe I like" in rendered
    assert "D22:1 Riley: Yesterday, I tried my newest dairy-free recipe" in rendered


def _food_item(
    item_id: str,
    text: str,
    *,
    source_id: str,
    score: float = 0.9,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {
                "query_expansion_reason": "original_query",
                "source_sibling_answer_evidence": 1,
            },
        },
    )
