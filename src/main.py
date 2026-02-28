"""Main entry point — event loop that connects SSE → state → agent."""
from __future__ import annotations
import asyncio
import json
import logging

from src.config import RESTAURANT_ID
from src.state import GameState
from src.sse import listen_sse
from src.api import get_restaurant_info, get_recipes, get_meals
from src.agent import build_agent

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackapizza")

# ── Globals ──────────────────────────────────────────────────
state = GameState()
agent = None  # built lazily after imports are verified


# ── Event handlers ───────────────────────────────────────────
async def refresh_state():
    """Pull fresh restaurant info from the REST API."""
    try:
        info = await get_restaurant_info()
        state.update_from_restaurant_info(info)
    except Exception as exc:
        logger.warning("Could not refresh state: %s", exc)


async def on_phase_changed(phase: str):
    """React to a new game phase."""
    state.phase = phase
    logger.info("━━━ Phase changed → %s ━━━", phase)

    if phase == "stopped":
        # Reset per-turn transient data
        state.pending_clients.clear()
        state.prepared_dishes.clear()
        return

    # Refresh state at every phase transition
    await refresh_state()

    # Load recipes once (they don't change between turns)
    if not state.recipes:
        try:
            state.recipes = await get_recipes()
            logger.info("Loaded %d recipes", len(state.recipes))
        except Exception as exc:
            logger.warning("Could not load recipes: %s", exc)

    # Ask the agent what to do
    await ask_agent(f"The phase just changed to '{phase}'. Decide what actions to take.")


async def on_client_spawned(data: dict):
    """A new client has arrived during serving phase."""
    state.pending_clients.append(data)
    client_name = data.get("clientName", "unknown")
    order = data.get("orderText", "")
    logger.info("Client spawned: %s — order: %s", client_name, order)

    await ask_agent(
        f"A new client '{client_name}' just arrived with this order: \"{order}\". "
        f"Decide how to serve them (prepare_dish then serve_dish)."
    )


async def on_preparation_complete(data: dict):
    """A dish has finished cooking."""
    dish = data.get("dish", "")
    state.prepared_dishes.append(dish)
    logger.info("Dish ready: %s", dish)

    await ask_agent(
        f"The dish '{dish}' is now ready. Serve it to the appropriate waiting client."
    )


async def ask_agent(prompt: str):
    """Run the agent with the current game context."""
    global agent
    if agent is None:
        return

    context = (
        f"GAME STATE:\n{state.summary()}\n\n"
        f"RECIPES AVAILABLE: {json.dumps(state.recipes[:10], default=str)}\n\n"  # first 10 for token budget
        f"YOUR TASK:\n{prompt}"
    )

    try:
        logger.info("Agent invoked: %s", prompt[:120])
        result = await agent.a_run(context)
        logger.info("Agent response: %s", result.text[:300] if result.text else "(no text)")
    except Exception as exc:
        logger.exception("Agent error: %s", exc)


# ── Event dispatcher ─────────────────────────────────────────
async def dispatch_events(event_queue: asyncio.Queue):
    """Consume events from the SSE queue and route them."""
    while True:
        event = await event_queue.get()
        etype = event.get("type", "")
        data = event.get("data", {})

        try:
            if etype == "game_started":
                logger.info("Game started!")
                state.turn_id += 1
                await refresh_state()

            elif etype == "game_phase_changed":
                await on_phase_changed(data.get("phase", ""))

            elif etype == "client_spawned":
                await on_client_spawned(data)

            elif etype == "preparation_complete":
                await on_preparation_complete(data)

            elif etype == "message":
                sender = data.get("sender", "?")
                payload = data.get("payload", "")
                logger.info("Broadcast message from %s: %s", sender, str(payload)[:200])

            elif etype == "new_message":
                sender = data.get("senderName", "?")
                text = data.get("text", "")
                logger.info("DM from %s: %s", sender, text[:200])

            elif etype == "game_reset":
                logger.warning("Game reset by organizers!")
                state.__init__()

            elif etype == "heartbeat":
                pass  # silently ignore

            else:
                logger.debug("Unhandled event type: %s", etype)

        except Exception as exc:
            logger.exception("Error handling event %s: %s", etype, exc)


# ── Main ─────────────────────────────────────────────────────
async def main():
    global agent

    logger.info("═══ Hackapizza 2.0 — Restaurant Agent ═══")
    logger.info("Restaurant ID: %s", RESTAURANT_ID)

    # Build the agent (fetches MCP tools from the server)
    try:
        agent = build_agent()
    except Exception as exc:
        logger.error("Failed to build agent (is the server up?): %s", exc)
        logger.info("Running in listen-only mode — will retry on next phase change")

    # SSE event queue
    event_queue: asyncio.Queue = asyncio.Queue()

    # Launch SSE listener + event dispatcher concurrently
    await asyncio.gather(
        listen_sse(event_queue),
        dispatch_events(event_queue),
    )


if __name__ == "__main__":
    asyncio.run(main())
