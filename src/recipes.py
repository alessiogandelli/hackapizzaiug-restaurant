"""Deterministic recipe & ingredient analysis — no LLM needed.

Handles recipe feasibility filtering, ingredient demand computation,
and bid target calculation. Replaces the old 10-recipe truncation
with intelligent filtering.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def filter_feasible_recipes(
    all_recipes: list[dict],
    inventory: list[dict],
    market_entries: list[dict] | None = None,
) -> list[dict]:
    """Return recipes that can be cooked with current inventory + market supply.

    A recipe is feasible if every required ingredient is either:
    - already in inventory, OR
    - available on the market (BUY side or SELL side we can purchase)
    """
    # Build sets of available ingredients
    inv_ingredients: set[str] = set()
    for item in inventory:
        if isinstance(item, str):
            inv_ingredients.add(item.lower().strip())
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("ingredient_name") or item.get("ingredient", "")
        if name:
            inv_ingredients.add(name.lower().strip())

    market_ingredients: set[str] = set()
    if market_entries:
        for entry in market_entries:
            if not isinstance(entry, dict):
                continue
            side = entry.get("side", "").upper()
            name = entry.get("ingredient_name") or entry.get("ingredient", "")
            if name and side == "SELL":
                # Others selling = we can buy
                market_ingredients.add(name.lower().strip())

    available = inv_ingredients | market_ingredients

    feasible = []
    for recipe in all_recipes:
        if not isinstance(recipe, dict):
            continue
        ingredients = recipe.get("ingredients", [])
        if not ingredients:
            continue

        # Check every ingredient is available somewhere
        all_available = True
        for ing in ingredients:
            if isinstance(ing, str):
                ing_name = ing
            elif isinstance(ing, dict):
                ing_name = ing.get("name") or ing.get("ingredient_name") or ing.get("ingredient", "")
            else:
                continue
            if not ing_name:
                continue
            if ing_name.lower().strip() not in available:
                all_available = False
                break

        if all_available:
            feasible.append(recipe)

    logger.info(
        "Recipe filter: %d/%d feasible (inv=%d ingredients, market=%d ingredients)",
        len(feasible), len(all_recipes), len(inv_ingredients), len(market_ingredients),
    )
    return feasible


def compute_ingredient_demand(
    feasible_recipes: list[dict],
    menu: list[dict],
) -> dict[str, int]:
    """Compute which ingredients are needed for the current menu.

    Returns {ingredient_name: total_quantity_needed} for menu items
    that map to feasible recipes.
    """
    # Build menu → recipe mapping
    menu_names: set[str] = set()
    for item in menu if isinstance(menu, list) else []:
        if isinstance(item, str):
            menu_names.add(item.lower().strip())
        elif isinstance(item, dict) and item.get("name"):
            menu_names.add(item["name"].lower().strip())

    demand: dict[str, int] = {}
    for recipe in feasible_recipes:
        if not isinstance(recipe, dict):
            continue
        recipe_name = recipe.get("name", "").lower().strip()
        if recipe_name not in menu_names:
            continue

        for ing in recipe.get("ingredients", []):
            if isinstance(ing, str):
                name = ing
                qty = 1
            elif isinstance(ing, dict):
                name = ing.get("name") or ing.get("ingredient_name") or ing.get("ingredient", "")
                qty = ing.get("quantity", 1)
            else:
                continue
            if name:
                key = name.lower().strip()
                demand[key] = demand.get(key, 0) + qty

    logger.info("Ingredient demand: %d unique ingredients needed", len(demand))
    return demand


def compute_bid_targets(
    demand: dict[str, int],
    inventory: list[dict],
) -> list[dict]:
    """Compute what to bid on based on demand minus inventory.

    Returns [{ingredient, quantity_needed, in_stock}] for items we're short on.
    """
    # Count current inventory
    stock: dict[str, int] = {}
    for item in inventory:
        if isinstance(item, str):
            stock[item.lower().strip()] = stock.get(item.lower().strip(), 0) + 1
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("ingredient_name") or item.get("ingredient", "")
        qty = item.get("quantity", 1)
        if name:
            key = name.lower().strip()
            stock[key] = stock.get(key, 0) + qty

    targets = []
    for ingredient, needed in demand.items():
        in_stock = stock.get(ingredient, 0)
        if needed > in_stock:
            targets.append({
                "ingredient": ingredient,
                "quantity_needed": needed - in_stock,
                "in_stock": in_stock,
            })

    targets.sort(key=lambda t: t["quantity_needed"], reverse=True)
    logger.info("Bid targets: %d ingredients needed", len(targets))
    return targets


def get_recipe_summary(recipes: list[dict], max_recipes: int = 30) -> str:
    """Compact recipe summary for agent context — much better than raw JSON."""
    import json
    if not isinstance(recipes, list):
        logger.warning("get_recipe_summary: recipes is %s, not list", type(recipes).__name__)
        return "[]"
    summaries = []
    for r in recipes[:max_recipes]:
        if isinstance(r, str):
            summaries.append({"name": r, "ingredients": [], "prep_time": "?"})
            continue
        if not isinstance(r, dict):
            logger.debug("get_recipe_summary: skipping non-dict recipe: %s", type(r).__name__)
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
        summaries.append({
            "name": name,
            "ingredients": ingredients,
            "prep_time": prep_time,
        })
    return json.dumps(summaries, default=str)
