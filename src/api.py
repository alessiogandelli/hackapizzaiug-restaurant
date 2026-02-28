"""HTTP helpers — wrappers around the game-server REST endpoints."""
import asyncio
import aiohttp
import json
import logging
from src.config import SERVER_URL, HEADERS, RESTAURANT_ID

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0  # seconds — doubles each retry (1, 2, 4, 8, 16)


async def _get(path: str, params: dict | None = None) -> dict | list:
    """Generic authenticated GET with exponential-backoff retry on 429."""
    url = f"{SERVER_URL}{path}"
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(url, params=params) as resp:
                    status = resp.status

                    # ── 429 rate-limit: back off and retry ──
                    if status == 429:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "API %s returned 429 (attempt %d/%d) — retrying in %.1fs …",
                            path, attempt, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    if status != 200:
                        body = await resp.text()
                        logger.error("API %s returned HTTP %d: %s", path, status, body[:500])

                    resp.raise_for_status()
                    data = await resp.json()
                    logger.debug(
                        "API %s → type=%s, %s",
                        path, type(data).__name__,
                        f"len={len(data)}" if isinstance(data, (list, dict)) else f"value={str(data)[:200]}",
                    )
                    return data

        except aiohttp.ClientResponseError as exc:
            last_exc = exc
            if exc.status == 429:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "API %s 429 (attempt %d/%d) — retrying in %.1fs …",
                    path, attempt, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
        except Exception as exc:
            logger.error("API %s request failed: %s (%s)", path, exc, type(exc).__name__)
            raise

    # All retries exhausted
    logger.error("API %s — 429 rate-limit persisted after %d retries", path, MAX_RETRIES)
    if last_exc:
        raise last_exc
    raise aiohttp.ClientResponseError(
        request_info=aiohttp.RequestInfo(url=url, method="GET", headers={}, real_url=url),
        history=(),
        status=429,
        message="Rate limited after max retries",
    )


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
