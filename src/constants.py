"""Hardcoded constants for our 5-recipe restaurant strategy.

These are the ONLY recipes we serve, the ONLY ingredients we bid on,
and the ONLY menu items we set. No dynamic filtering needed.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# THE 5 RECIPES WE SERVE
# ═══════════════════════════════════════════════════════════════

MENU_ITEMS = [
    {"name": "Cosmic Synchrony: Il Destino di Pulsar", "price": 500},
]

OUR_RECIPE_NAMES: set[str] = {item["name"] for item in MENU_ITEMS}

# Full ingredient breakdown per recipe (for serving agent context)
RECIPE_INGREDIENTS = {
    "Cosmic Synchrony: Il Destino di Pulsar": [
        "Polvere di Pulsar", "Foglie di Mandragora", "Spaghi del Sole",
        "Farina di Nettuno", "Plasma Vitale", "Essenza di Tachioni",
    ],
}

# ═══════════════════════════════════════════════════════════════
# INGREDIENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

CORE_INGREDIENTS = [
    "Polvere di Pulsar", "Foglie di Mandragora", "Spaghi del Sole",
    "Farina di Nettuno", "Plasma Vitale", "Essenza di Tachioni",
]

ALT_INGREDIENTS = []

SUPPORT_INGREDIENTS = []

# All unique ingredients we ever need
ALL_INGREDIENTS: set[str] = set(CORE_INGREDIENTS + ALT_INGREDIENTS + SUPPORT_INGREDIENTS)

# ═══════════════════════════════════════════════════════════════
# BIDDING DEFAULTS  (conservative fixed bid prices per unit)
# ═══════════════════════════════════════════════════════════════

# quantity = how many units to bid for each ingredient per turn
#   (1 unit of each is usually enough for 1 serving of each recipe)
# bid_price = price per unit (conservative)
DEFAULT_BIDS = [
    {"ingredient": "Polvere di Pulsar",     "quantity": 200, "bid": 42},
    {"ingredient": "Foglie di Mandragora",  "quantity": 200, "bid": 38},
    {"ingredient": "Spaghi del Sole",       "quantity": 200, "bid": 42},
    {"ingredient": "Farina di Nettuno",     "quantity": 200, "bid": 58},
    {"ingredient": "Plasma Vitale",         "quantity": 200, "bid": 92},
    {"ingredient": "Essenza di Tachioni",   "quantity": 200, "bid": 98},
]

# Max total we'll spend on bids per turn (absolute cap)
MAX_BID_SPEND = 100000

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
MAX_MARKET_PRICE = 110

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
