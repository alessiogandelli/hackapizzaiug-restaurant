"""Recipe utilities — dynamic menu building from /recipes + inventory.

Core flow:
1. Fetch all recipes from the server (/recipes)
2. Check current inventory
3. Find which recipes we can actually make (have ALL ingredients)
4. Build menu from feasible recipes
"""
from __future__ import annotations

import json
import logging
from src.constants import ALL_INGREDIENTS

logger = logging.getLogger(__name__)


def get_inventory_stock(inventory: list[dict]) -> dict[str, int]:
    """Parse inventory into {ingredient_name: quantity}."""
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
    return stock


def extract_recipe_ingredients(recipe: dict) -> list[dict]:
    """Extract ingredient list from a recipe dict.
    
    Returns list of {"name": str, "quantity": int}.
    """
    raw_ings = recipe.get("ingredients", [])
    result = []
    if not isinstance(raw_ings, list):
        return result
    for ing in raw_ings:
        if isinstance(ing, str):
            result.append({"name": ing, "quantity": 1})
        elif isinstance(ing, dict):
            name = ing.get("name") or ing.get("ingredient_name") or ing.get("ingredient", "")
            qty = ing.get("quantity", 1)
            if name:
                result.append({"name": name.strip(), "quantity": qty})
    return result


def find_feasible_recipes(all_recipes: list[dict], inventory: list[dict]) -> list[dict]:
    """Given server recipes and our inventory, return recipes we CAN make.
    
    A recipe is feasible if we have ALL its ingredients in sufficient quantity.
    Returns a list of recipe dicts, each augmented with '_ingredients_parsed'.
    """
    stock = get_inventory_stock(inventory)
    logger.info("INVENTORY STOCK | %s", ", ".join(f"{k}x{v}" for k, v in stock.items()))
    feasible = []

    for recipe in all_recipes:
        ings = extract_recipe_ingredients(recipe)
        logger.info("Checking recipe '%s' with ingredients: %s", recipe.get("name", "?"),
                     ", ".join(f"{ing['name']}x{ing['quantity']}" for ing in ings))
        if not ings:
            logger.info("Recipe '%s' has no valid ingredients, skipping", recipe.get("name", "?"))
            continue
        can_make = True
        for ing in ings:
            logger.info("Checking ingredient '%s' x%d against stock", ing["name"], ing["quantity"])
            name = ing["name"]
            qty_needed = ing["quantity"]
            qty_in_stock = stock.get(name, 0)
            if qty_in_stock < qty_needed:
                logger.debug("Not enough '%s': need %d, have %d", name, qty_needed, qty_in_stock)
                can_make = False
                break
        if can_make:
            logger.info("Recipe '%s' is feasible", recipe.get("name", "?"))
            recipe["_ingredients_parsed"] = ings
            feasible.append(recipe)
    

    
    logger.info("RECIPES | %d feasible out of %d total recipes", len(feasible), len(all_recipes))
    return feasible


def build_menu_from_feasible(feasible_recipes: list[dict], default_price: int = 400) -> list[dict]:
    """Build menu items from feasible recipes.
    
    Returns [{"name": "exact recipe name", "price": N}, ...]
    Menu uses EXACT recipe names from the server (case-sensitive).
    """
    menu = []
    for recipe in feasible_recipes:
        name = recipe.get("name", "")
        # Use recipe's price if available, otherwise default
        price = recipe.get("price") or recipe.get("selling_price") or default_price
        menu.append({"name": name, "price": price})
    
    logger.info("MENU BUILT | %d items: %s", len(menu), 
               [f"{m['name']} @ {m['price']}" for m in menu])
    return menu


def build_recipe_ingredients_map(feasible_recipes: list[dict]) -> dict[str, list[str]]:
    """Build {recipe_name: [ingredient_names]} for feasible recipes."""
    mapping = {}
    for recipe in feasible_recipes:
        name = recipe.get("name", "")
        ingredients = recipe.get("_ingredients_parsed") or extract_recipe_ingredients(recipe)
        mapping[name] = [ing["name"] for ing in ingredients]
    return mapping


def compute_missing_ingredients(inventory: list[dict]) -> dict[str, int]:
    """Return {ingredient_name: count_in_stock} for ALL known ingredients."""
    stock = get_inventory_stock(inventory)
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
