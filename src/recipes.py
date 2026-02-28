"""Recipe utilities — simplified for our fixed 5-recipe strategy.

Only keeps helpers actually needed: recipe summary for serving context,
and missing ingredient computation for bidding.
"""
from __future__ import annotations

import json
import logging
from src.constants import OUR_RECIPE_NAMES, ALL_INGREDIENTS

logger = logging.getLogger(__name__)


def get_our_recipes_from_server(all_recipes: list[dict]) -> list[dict]:
    """Filter the server's full recipe list to just our 5 recipes."""
    ours = []
    for r in all_recipes:
        if not isinstance(r, dict):
            continue
        name = r.get("name", "")
        if name in OUR_RECIPE_NAMES:
            ours.append(r)
    logger.info("RECIPES | Found %d/%d of our recipes on server", len(ours), len(OUR_RECIPE_NAMES))
    return ours


def compute_missing_ingredients(inventory: list[dict]) -> dict[str, int]:
    """Return {ingredient_name: count_in_stock} for ingredients we care about.

    The orchestrator uses this to decide what to bid on.
    """
    stock: dict[str, int] = {}
    for item in inventory:
        if isinstance(item, str):
            name = item
            qty = 1
        elif isinstance(item, dict):
            name = item.get("name") or item.get("ingredient_name") or item.get("ingredient", "")
            qty = item.get("quantity", 1)
        else:
            continue
        if name:
            key = name.strip()
            stock[key] = stock.get(key, 0) + qty

    # Only return stock for ingredients we care about
    return {ing: stock.get(ing, 0) for ing in ALL_INGREDIENTS}


def get_recipe_summary(recipes: list[dict], max_recipes: int = 30) -> str:
    """Compact recipe summary for agent context."""
    if not isinstance(recipes, list):
        logger.warning("get_recipe_summary: recipes is %s, not list", type(recipes).__name__)
        return "[]"
    summaries = []
    for r in recipes[:max_recipes]:
        if isinstance(r, str):
            summaries.append({"name": r, "ingredients": [], "prep_time": "?"})
            continue
        if not isinstance(r, dict):
            continue
        name = r.get("name", "?")
        raw_ings = r.get("ingredients", [])
        ingredients = []
        for ing in (raw_ings if isinstance(raw_ings, list) else []):
            if isinstance(ing, str):
                ingredients.append(ing)
            elif isinstance(ing, dict):
                ingredients.append(f"{ing.get('name', '?')} x{ing.get('quantity', 1)}")
            else:
                ingredients.append(str(ing))
        prep_time = r.get("preparation_time", "?")
        summaries.append({"name": name, "ingredients": ingredients, "prep_time": prep_time})
    return json.dumps(summaries, default=str)
