"""Hardcoded constants for our 5-recipe restaurant strategy.

These are the ONLY recipes we serve, the ONLY ingredients we bid on,
and the ONLY menu items we set. No dynamic filtering needed.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# THE 5 RECIPES WE SERVE
# ═══════════════════════════════════════════════════════════════

MENU_ITEMS = [
    {"name": "Sinfonia Cosmica di Proteine Interstellari", "price": 320},
    {"name": "Cosmic Serenade",                            "price": 520},
    {"name": "Sinfonia Temporale di Fenice e Xenodonte su Pane degli Abissi", "price": 580},
    {"name": "Galassia di Sapore",                         "price": 400},
    {"name": "Sinfonia Cosmica di Mare e Stelle",          "price": 500},
]

OUR_RECIPE_NAMES: set[str] = {item["name"] for item in MENU_ITEMS}

# Full ingredient breakdown per recipe (for serving agent context)
RECIPE_INGREDIENTS = {
    "Sinfonia Cosmica di Proteine Interstellari": [
        "Carne di Balena spaziale", "Pane degli Abissi", "Funghi dell'Etere", "Carne di Mucca",
    ],
    "Cosmic Serenade": [
        "Carne di Balena spaziale", "Carne di Kraken", "Amido di Stellarion",
        "Nettare di Sirena", "Essenza di Tachioni",
    ],
    "Sinfonia Temporale di Fenice e Xenodonte su Pane degli Abissi": [
        "Carne di Balena spaziale", "Uova di Fenice", "Carne di Xenodonte",
        "Pane degli Abissi", "Plasma Vitale",
    ],
    "Galassia di Sapore": [
        "Carne di Balena spaziale", "Carne di Xenodonte", "Amido di Stellarion",
        "Lattuga Namecciana", "Erba Pipa",
    ],
    "Sinfonia Cosmica di Mare e Stelle": [
        "Carne di Balena spaziale", "Carne di Kraken", "Carne di Xenodonte",
        "Salsa Szechuan", "Lacrime di Andromeda",
    ],
}

# ═══════════════════════════════════════════════════════════════
# INGREDIENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

CORE_INGREDIENTS = ["Carne di Balena spaziale"]

ALT_INGREDIENTS = ["Carne di Kraken", "Uova di Fenice", "Carne di Xenodonte"]

SUPPORT_INGREDIENTS = [
    "Pane degli Abissi", "Amido di Stellarion", "Funghi dell'Etere",
    "Carne di Mucca", "Nettare di Sirena", "Essenza di Tachioni",
    "Plasma Vitale", "Lattuga Namecciana", "Erba Pipa",
    "Salsa Szechuan", "Lacrime di Andromeda",
]

# All unique ingredients we ever need
ALL_INGREDIENTS: set[str] = set(CORE_INGREDIENTS + ALT_INGREDIENTS + SUPPORT_INGREDIENTS)

# ═══════════════════════════════════════════════════════════════
# BIDDING DEFAULTS  (conservative fixed bid prices per unit)
# ═══════════════════════════════════════════════════════════════

# quantity = how many units to bid for each ingredient per turn
#   (1 unit of each is usually enough for 1 serving of each recipe)
# bid_price = price per unit (conservative)
DEFAULT_BIDS = [
    # CORE — always bid, 40% budget
    {"ingredient": "Carne di Balena spaziale", "quantity": 7, "bid": 60},
    # ALT — bid on all three, 20% budget split
    {"ingredient": "Carne di Kraken",          "quantity": 2, "bid": 20},
    {"ingredient": "Uova di Fenice",           "quantity": 1, "bid": 25},
    {"ingredient": "Carne di Xenodonte",       "quantity": 6, "bid": 20},
    # SUPPORT — 40% budget split
    {"ingredient": "Pane degli Abissi",        "quantity": 2, "bid": 15},
    {"ingredient": "Amido di Stellarion",      "quantity": 2, "bid": 20},
    {"ingredient": "Funghi dell'Etere",        "quantity": 1, "bid": 12},
    {"ingredient": "Carne di Mucca",           "quantity": 3, "bid": 20},
    {"ingredient": "Nettare di Sirena",        "quantity": 3, "bid": 15},
    {"ingredient": "Essenza di Tachioni",      "quantity": 3, "bid": 20},
    {"ingredient": "Plasma Vitale",            "quantity": 3, "bid": 20},
    {"ingredient": "Lattuga Namecciana",       "quantity": 3, "bid": 20},
    {"ingredient": "Erba Pipa",                "quantity": 3, "bid": 20},
    {"ingredient": "Salsa Szechuan",           "quantity": 3, "bid": 20},
    {"ingredient": "Lacrime di Andromeda",     "quantity": 3, "bid": 20},
]

# Max total we'll spend on bids per turn (absolute cap)
MAX_BID_SPEND = 500

# ═══════════════════════════════════════════════════════════════
# DEFAULT STRATEGY  (planner will return something close to this)
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY = {
    "segment": "balanced",
    "bid_aggression": 0.4,
    "target_margin": 0.35,
    "inventory_risk_limit": 400,
    "market_strategy": "defensive",
    "speaking_strategy": "silent",
}

# Max price we'll pay for an ingredient on the market
MAX_MARKET_PRICE = 70

# ═══════════════════════════════════════════════════════════════
# MARKET PRICE ANALYSIS
# ═══════════════════════════════════════════════════════════════

def compute_market_prices_from_history(bid_history: list) -> dict[str, float]:
    """Analyze bid history to compute average market prices per ingredient.
    
    Args:
        bid_history: List of bid records from the API, each with structure:
            {
                "ingredientId": int,
                "priceForEach": int,
                "status": "COMPLETED" | "FAILED",
                "ingredient": {"name": str, "id": int}
            }
    
    Returns:
        Dict mapping ingredient names to their average successful bid price.
        Example: {"Carne di Balena spaziale": 35.5, "Spore Quantiche": 12.0}
    """
    # Group successful bids by ingredient name
    ingredient_prices: dict[str, list[float]] = {}
    
    for bid in bid_history:
        # Only consider completed/successful bids
        if bid.get("status") != "COMPLETED":
            continue
            
        ingredient = bid.get("ingredient")
        if not ingredient:
            continue
            
        name = ingredient.get("name")
        price = bid.get("priceForEach")
        
        if name and price is not None:
            if name not in ingredient_prices:
                ingredient_prices[name] = []
            ingredient_prices[name].append(float(price))
    
    # Compute average price for each ingredient
    avg_prices = {}
    for name, prices in ingredient_prices.items():
        if prices:
            avg_prices[name] = sum(prices) / len(prices)
    
    return avg_prices


def get_competitive_bid_price(ingredient: str, market_prices: dict[str, float], default: float = 20.0) -> int:
    """Get a competitive bid price for an ingredient based on market data.
    
    Args:
        ingredient: Name of the ingredient (case-sensitive from our constants)
        market_prices: Dict from compute_market_prices_from_history
        default: Fallback price if no market data available
    
    Returns:
        Competitive bid price (20% above market average to win)
    """
    # Case-insensitive lookup - market data may have different capitalization
    ingredient_lower = ingredient.lower()
    matched_price = None
    
    for market_name, price in market_prices.items():
        if market_name.lower() == ingredient_lower:
            matched_price = price
            break
    
    if matched_price is not None:
        # Bid 20% above average market price to be competitive
        competitive_price = matched_price * 1.2
        # Round to nearest integer, min 5 credits
        return max(5, int(competitive_price))
    
    return int(default)
