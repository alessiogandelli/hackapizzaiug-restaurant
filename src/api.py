"""HTTP helpers — wrappers around the game-server REST endpoints."""
import aiohttp
import json
from src.config import SERVER_URL, HEADERS, RESTAURANT_ID


async def _get(path: str, params: dict | None = None) -> dict | list:
    """Generic authenticated GET against the game server."""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{SERVER_URL}{path}", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()


# ── Public helpers ───────────────────────────────────────────
async def get_restaurant_info() -> dict:
    return await _get(f"/restaurant/{RESTAURANT_ID}")


async def get_all_restaurants() -> list:
    return await _get("/restaurants")


async def get_recipes() -> list:
    return await _get("/recipes")


async def get_menu() -> list:
    return await _get(f"/restaurant/{RESTAURANT_ID}/menu")


async def get_meals(turn_id: int) -> list:
    return await _get("/meals", {"turn_id": turn_id, "restaurant_id": RESTAURANT_ID})


async def get_bid_history(turn_id: int) -> list:
    return await _get("/bid_history", {"turn_id": turn_id})


async def get_market_entries() -> list:
    return await _get("/market/entries")
