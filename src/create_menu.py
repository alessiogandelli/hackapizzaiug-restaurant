from __future__ import annotations
import api 

# filepath: /Users/alessiogandelli/dev/cantiere/hackapizzaiug-restaurant/src/create_menu.py
"""Menu creation utilities — select feasible recipes from available ingredients."""


def select_feasible_recipes( turn_id) -> list[dict]:
    """Return recipes that can be made with the available ingredients.

    Args:
        available_ingredients: mapping of ingredient name -> quantity available.
        recipes: list of recipe dicts (each with an "ingredients" dict).

    Returns:
        List of recipes whose ingredient requirements are fully covered.
    """
    ingredients = api.get_inventory(turn_id)
    feasible = []
    recipes = api.get_recipes()  # Fetch recipes at runtime to ensure up-to-date data
    for recipe in recipes:
        required = recipe.get("ingredients", {})
        if all(
            available_ingredients.get(ingredient, 0) >= qty
            for ingredient, qty in required.items()
        ):
            feasible.append(recipe)
    return feasible


select_feasible_recipes({"tomato": 3, "dough": 2, "cheese": 1})