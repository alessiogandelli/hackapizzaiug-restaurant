"""Constants for the undercutting restaurant strategy.

We bid LOW (3 credits per unit) on ALL ingredients, then dynamically
build our menu from whatever recipes we can make with what we won.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# ALL KNOWN INGREDIENTS (case-sensitive, letter-perfect)
# ═══════════════════════════════════════════════════════════════

ALL_INGREDIENTS_LIST: list[str] = [
    "Alghe Bioluminescenti",
    "Amido di Stellarion",
    "Baccacedro",
    "Biscotti della Galassia",
    "Burrobirra",
    "Carne di Balena spaziale",
    "Carne di Drago",
    "Carne di Kraken",
    "Carne di Mucca",
    "Carne di Xenodonte",
    "Chocobo Wings",
    "Cioccorane",
    "Colonia di Mycoflora",
    "Cristalli di Memoria",
    "Cristalli di Nebulite",
    "Erba Pipa",
    "Essenza di Speziaria",
    "Essenza di Tachioni",
    "Essenza di Vuoto",
    "Farina di Nettuno",
    "Fibra di Sintetex",
    "Foglie di Mandragora",
    "Foglie di Nebulosa",
    "Frammenti di Supernova",
    "Frutti del Diavolo",
    "Funghi dell’Etere",
    "Funghi Orbitali",
    "Fusilli del Vento",
    "Gnocchi del Crepuscolo",
    "Granuli di Nebbia Arcobaleno",
    "Lacrime di Andromeda",
    "Lacrime di Unicorno",
    "Latte+",
    "Lattuga Namecciana",
    "Liane di Plasmodio",
    "Muffa Lunare",
    "Nduja Fritta Tanto",
    "Nettare di Sirena",
    "Pane degli Abissi",
    "Pane di Luce",
    "Petali di Eco",
    "Pickle Rick Croccante",
    "Plasma Vitale",
    "Polvere di Crononite",
    "Polvere di Pulsar",
    "Polvere di Stelle",
    "Radici di Gravità",
    "Radici di Singolarità",
    "Ravioli al Vaporeon",
    "Riso di Cassandra",
    "Sale Temporale",
    "Salsa Szechuan",
    "Sashimi di Magikarp",
    "Shard di Materia Oscura",
    "Shard di Prisma Stellare",
    "Slurm",
    "Spaghi del Sole",
    "Spezie Melange",
    "Spore Quantiche",
    "Teste di Idra",
    "Uova di Fenice",
    "Vero Ghiaccio",
]

ALL_INGREDIENTS: set[str] = set(ALL_INGREDIENTS_LIST)

# ═══════════════════════════════════════════════════════════════
# BIDDING: UNDERCUTTING STRATEGY — 3 credits × 3 units each
# ═══════════════════════════════════════════════════════════════

BID_PRICE_PER_UNIT = 3
BID_QUANTITY_PER_INGREDIENT = 3

# Build the full bid list automatically
DEFAULT_BIDS = [
    {"ingredient": ing, "quantity": BID_QUANTITY_PER_INGREDIENT, "bid": BID_PRICE_PER_UNIT}
    for ing in ALL_INGREDIENTS_LIST
]

# Max total we'll spend on bids per turn
# 62 ingredients × 3 units × 3 credits = 558 credits
MAX_BID_SPEND = len(ALL_INGREDIENTS_LIST) * BID_QUANTITY_PER_INGREDIENT * BID_PRICE_PER_UNIT + 50

# Max total we'll spend across ALL operations (bids + market) per turn
MAX_TURN_SPEND = MAX_BID_SPEND + 200

# ═══════════════════════════════════════════════════════════════
# DEFAULT STRATEGY
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY = {
    "segment": "undercutter",
    "bid_aggression": 0.1,
    "target_margin": 0.8,
    "inventory_risk_limit": MAX_BID_SPEND,
    "market_strategy": "defensive",
    "speaking_strategy": "silent",
}

# Max price we'll pay for an ingredient on the market
MAX_MARKET_PRICE = 10

# ═══════════════════════════════════════════════════════════════
# DYNAMIC MENU — these are populated at runtime from /recipes + inventory
# ═══════════════════════════════════════════════════════════════

# Will be set by orchestrator after checking inventory
MENU_ITEMS: list[dict] = []          # [{"name": "...", "price": ...}, ...]
OUR_RECIPE_NAMES: set[str] = set()   # set of active recipe names
RECIPE_INGREDIENTS: dict[str, list[str]] = {}  # {recipe_name: [ingredients]}


