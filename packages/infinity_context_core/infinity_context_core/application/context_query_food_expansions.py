"""Food, dessert, and recipe query expansion rules."""

from __future__ import annotations

_FOOD_RECIPE_DETAIL_EXPANSION = (
    "food recipe recipes dessert desserts baking baked bake cake cakes filling "
    "frosting ganache crust raspberries blueberries coconut milk almond milk "
    "gluten-free dairy-free lactose-free vegan ice cream icecream flavor flavors "
    "treat treats sweet pudding parfait mousse ingredient ingredients spice soup "
    "honey garlic chicken share shared offer hosted taught cooking show"
)

FOOD_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"dessert"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"desserts"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"recipe"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"recipes"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"ice", "cream"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"dairy", "free"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"vegan", "ice"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"vegan", "recipes"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"vegan", "diet"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"cake", "flavor"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"cake", "filling"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"cake", "frosting"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"coconut", "milk"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"lactose", "free"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
    (
        frozenset({"spice", "soup"}),
        _FOOD_RECIPE_DETAIL_EXPANSION,
        "food_recipe_detail_bridge",
    ),
)
