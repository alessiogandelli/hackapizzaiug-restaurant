"""HTTP helpers — wrappers around the game-server REST endpoints."""
import aiohttp
import json
import logging
from src.config import SERVER_URL, HEADERS, RESTAURANT_ID

logger = logging.getLogger(__name__)


async def _get(path: str, params: dict | None = None) -> dict | list:
    """Generic authenticated GET against the game server."""
    url = f"{SERVER_URL}{path}"
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(url, params=params) as resp:
                status = resp.status
                if status != 200:
                    body = await resp.text()
                    logger.error("API %s returned HTTP %d: %s", path, status, body[:500])
                resp.raise_for_status()
                data = await resp.json()
                logger.debug("API %s → type=%s, %s",
                             path, type(data).__name__,
                             f"len={len(data)}" if isinstance(data, (list, dict)) else f"value={str(data)[:200]}")
                return data
    except aiohttp.ClientResponseError:
        raise  # already logged above
    except Exception as exc:
        logger.error("API %s request failed: %s (%s)", path, exc, type(exc).__name__)
        raise


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
