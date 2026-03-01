# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "aiohttp",
#     "datapizza-ai",
#     "datapizza-ai-clients-openai-like"
# ]
# ///

import asyncio
import json
from datetime import datetime
from typing import Any, Awaitable, Callable
from agenti import opener, bidder, menu, prepara, servi
from ricette import ricette as all_recipes

from config import TEAM_API_KEY, TEAM_ID, BASE_URL
import aiohttp

TEAM_ID = 15  # your team id
TEAM_API_KEY = "dTpZhKpZ02-b91de4ab95c9fa33d6c7c9c0"

BASE_URL = "https://hackapizza.datapizza.tech"

if not TEAM_API_KEY or not TEAM_ID:
    raise SystemExit("Set TEAM_API_KEY and TEAM_ID")


def log(tag: str, message: str) -> None:
    print(f"[{tag}] {datetime.now()}: {message}")


# ── Serving state ────────────────────────────────────────────
current_turn_id: int = 0
pending_dishes: dict[str, list[str]] = {}  # dish_name -> [client_id, ...]


async def game_started(data: dict[str, Any]) -> None:
    global current_turn_id
    current_turn_id = data.get("turn_id", 0)
    opener.run("Apri il ristorante")
    log("EVENT", "game started, turn id: " + str(current_turn_id))

async def speaking_phase_started() -> None:
    log("EVENT", "speaking phase started")


def get_inventory() -> dict:
    import requests
    response = requests.get(
        f"{BASE_URL}/restaurants",
        headers={"x-api-key": TEAM_API_KEY},
    )
    response.raise_for_status()
    restaurants = response.json()
    for r in restaurants:
        if str(r.get("id")) == str(TEAM_ID):
            return r.get("inventory", {})
    return {}


def print_inventory() -> None:
    inventory = get_inventory()
    if not inventory:
        log("INVENTORY", "inventario vuoto")
        return
    log("INVENTORY", f"{'Ingrediente':<40} Quantità")
    log("INVENTORY", "-" * 50)
    for ingredient, qty in sorted(inventory.items()):
        log("INVENTORY", f"{ingredient:<40} {qty}")


async def closed_bid_phase_started() -> None:
    from ingredienti import ingredienti
    bidder.run("Fai un'offerta, compra uno di tutto a 3 euro ciascuno, " + str(ingredienti))
    log("EVENT", "closed bid phase started")
    print_inventory()

async def waiting_phase_started() -> None:
    from ricette import ricette
    menu.run("Aggiorna il menu utilizzando" + str(ricette) + " assicurati di sceglierne 12")
    log("EVENT", "waiting phase started")


async def serving_phase_started() -> None:
    log("EVENT", "serving phase started")


async def end_turn() -> None:
    log("EVENT", "turn ended")

def get_meals(turn_id: int) -> list:
    import requests
    response = requests.get(
        f"{BASE_URL}/meals",
        params={"turn_id": turn_id, "restaurant_id": 15},
        headers={"x-api-key": TEAM_API_KEY},
    )
    response.raise_for_status()
    return response.json()


async def client_spawned(data: dict[str, Any]) -> None:
    log("SPAWN", f"--- client_spawned raw data: {data}")
    client_name = data.get("clientName", "unknown")
    order_text = str(data.get("orderText", "unknown"))
    order_text_raw = order_text
    order_text = order_text.lower().replace("i'd like a ", "").replace("i'd like ", "")

    log("SPAWN", f"client={client_name!r}  order_raw={order_text_raw!r}  order_clean={order_text!r}")

    # 1. Fetch meals to get client_id and intolerances
    log("SPAWN", f"calling get_meals(turn_id={current_turn_id}) ...")
    try:
        meals = get_meals(current_turn_id)
        log("SPAWN", f"get_meals returned {len(meals)} entries: {meals}")
    except Exception as e:
        log("ERROR", f"get_meals failed: {e}")
        return

    # 2. Find this client in the meals list
    log("SPAWN", f"searching for clientName={client_name!r} in meals ...")
    client_meal = None
    for i, meal in enumerate(meals):
        customer = meal.get("customer") or {}
        meal_name = customer.get("name", "")
        executed = meal.get("executed", False)
        log("SPAWN", f"  meal[{i}]: name={meal_name!r} executed={executed}")
        if meal_name == client_name and not executed:
            client_meal = meal
            log("SPAWN", f"  -> matched at index {i}")
            break

    if not client_meal:
        log("ERROR", f"client '{client_name}' not found in meals (checked {len(meals)} entries)")
        return

    client_id = client_meal.get("customerId") or client_meal.get("id")

    # Parse intolerances from the order text (e.g. "I'm intolerant to X")
    intolerances: set[str] = set()
    intol_marker = "intolerant to "
    intol_idx = order_text.find(intol_marker)
    if intol_idx != -1:
        intol_str = order_text[intol_idx + len(intol_marker):]
        # Clean up trailing punctuation / extra text
        for sep in [".", ",", ";"]:
            intol_str = intol_str.split(sep)[0]
        intolerances = {i.strip() for i in intol_str.split(",") if i.strip()}

    log("SPAWN", f"client_id={client_id!r}  intolerances={intolerances}")

    # 3. Match order to a recipe: best word-overlap, respecting intolerances
    order_words = set(order_text.lower().split())
    log("SPAWN", f"matching order words {order_words} against {len(all_recipes)} recipes ...")
    best_match = None
    best_score = -1

    skipped_intol = 0
    for recipe in all_recipes:
        recipe_ingredients = set(recipe["ingredients"].keys())
        blocked = intolerances & recipe_ingredients
        if blocked:
            skipped_intol += 1
            continue

        recipe_words = set(recipe["name"].lower().split())
        score = len(order_words & recipe_words)

        if score > best_score:
            best_score = score
            best_match = recipe
            log("SPAWN", f"  new best: {recipe['name']!r}  score={score}  overlap={order_words & recipe_words}")

    log("SPAWN", f"skipped {skipped_intol} recipes due to intolerances, best_score={best_score}")

    # Fallback: pick highest-prestige compatible dish
    if not best_match or best_score == 0:
        log("SPAWN", "no word-match found, falling back to highest-prestige compatible dish")
        compatible = [
            r for r in all_recipes
            if not (intolerances & set(r["ingredients"].keys()))
        ]
        log("SPAWN", f"  {len(compatible)} compatible recipes available")
        if compatible:
            best_match = max(compatible, key=lambda r: r["prestige"])
            log("SPAWN", f"  fallback pick: {best_match['name']!r} prestige={best_match['prestige']}")

    if not best_match:
        log("ERROR", f"no compatible dish found for {client_name}")
        return

    dish_name = best_match["name"]
    log("SPAWN", f"chosen dish: {dish_name!r}  prestige={best_match['prestige']}  cook_ms={best_match['preparationTimeMs']}  ingredients={list(best_match['ingredients'].keys())}")

    # 4. Track this dish -> client_id mapping
    pending_dishes.setdefault(dish_name, []).append(client_id)
    log("SPAWN", f"pending_dishes now: { {k: v for k, v in pending_dishes.items()} }")

    log("ACTION", f">>> prepare_dish '{dish_name}' for client {client_name!r} (id={client_id})")
    prepara.run(f"Prepara il piatto '{dish_name}'")
    log("SPAWN", f"prepare_dish call returned for '{dish_name}'")



async def preparation_complete(data: dict[str, Any]) -> None:
    log("READY", f"--- preparation_complete raw data: {data}")
    dish_name = data.get("dish", "unknown")

    log("READY", f"dish ready: {dish_name!r}")
    log("READY", f"pending_dishes state: { {k: v for k, v in pending_dishes.items()} }")

    # Pop the first client waiting for this dish
    clients = pending_dishes.get(dish_name, [])
    log("READY", f"clients waiting for '{dish_name}': {clients}")
    if not clients:
        log("ERROR", f"no pending client for dish '{dish_name}' — cannot serve!")
        return

    client_id = clients.pop(0)
    if not clients:
        del pending_dishes[dish_name]
    log("READY", f"popped client_id={client_id!r}, remaining for this dish: {clients}")
    log("READY", f"pending_dishes after pop: { {k: v for k, v in pending_dishes.items()} }")

    log("ACTION", f">>> serve_dish '{dish_name}' to client {client_id!r}")
    servi.run(f"Servi il piatto '{dish_name}' al cliente con id '{client_id}'")
    log("READY", f"serve_dish call returned for '{dish_name}' -> client {client_id!r}")


async def message(data: dict[str, Any]) -> None:
    sender = data.get("sender", "unknown")
    text = data.get("payload", "")
    log("EVENT", f"message from {sender}: {text}")


async def game_phase_changed(data: dict[str, Any]) -> None:
    phase = data.get("phase", "unknown")
    handlers: dict[str, Callable[[], Awaitable[None]]] = {
        "speaking": speaking_phase_started,
        "closed_bid": closed_bid_phase_started,
        "waiting": waiting_phase_started,
        "serving": serving_phase_started,
        "stopped": end_turn,
    }
    handler = handlers.get(phase)
    if handler:
        await handler()
    else:
        log("EVENT", f"unknown phase: {phase}")


async def game_reset(data: dict[str, Any]) -> None:
    if data:
        log("EVENT", f"game reset: {data}")
    else:
        log("EVENT", "game reset")


EVENT_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {
    "game_started": game_started,
    "game_phase_changed": game_phase_changed,
    "game_reset": game_reset,
    "client_spawned": client_spawned,
    "preparation_complete": preparation_complete,
    "message": message,
}

##########################################################################################
#                                    DANGER ZONE                                         #
##########################################################################################
# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.


# It is the central event dispatcher used by all handlers.
async def dispatch_event(event_type: str, event_data: dict[str, Any]) -> None:
    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        return
    try:
        await handler(event_data)
    except Exception as exc:
        log("ERROR", f"handler failed for {event_type}: {exc}")


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It parses SSE lines and translates them into internal events.
async def handle_line(raw_line: bytes) -> None:
    if not raw_line:
        return

    # dump the raw line to file for debugging
    decoded = raw_line.decode("utf-8", errors="ignore").strip()
    if decoded and not decoded.startswith("Restaurant"):
        with open("debug_sse.log", "a") as f:
            f.write(decoded + "\n")

    line = decoded
    if not line:
        return

    # Standard SSE data format: data: ...
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "connected":
            log("SSE", "connected")
            return
        line = payload

    try:
        event_json = json.loads(line)
    except json.JSONDecodeError:
        log("SSE", f"raw: {line}")
        return

    event_type = event_json.get("type", "unknown")
    event_data = event_json.get("data", {})
    if isinstance(event_data, dict):
        await dispatch_event(event_type, event_data)
    else:
        await dispatch_event(event_type, {"value": event_data})


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It owns the SSE HTTP connection lifecycle.
async def listen_once(session: aiohttp.ClientSession) -> None:
    url = f"{BASE_URL}/events/{TEAM_ID}"
    headers = {"Accept": "text/event-stream", "x-api-key": TEAM_API_KEY}

    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        log("SSE", "connection open")
        async for line in response.content:
            await handle_line(line)


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It controls script exit behavior when the SSE connection drops.
async def listen_once_and_exit_on_drop() -> None:
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        await listen_once(session)
        log("SSE", "connection closed, exiting")


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# Keep this minimal to avoid changing startup behavior.
async def main() -> None:
    log("INIT", f"team={TEAM_ID} base_url={BASE_URL}")
    await listen_once_and_exit_on_drop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("INIT", "client stopped")