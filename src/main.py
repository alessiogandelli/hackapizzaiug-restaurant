"""Main entry point — event loop that connects SSE → state → agent."""
from __future__ import annotations
import asyncio
import json
import logging

from datapizza.tracing import DatapizzaMonitoringInstrumentor

from src.config import (
    RESTAURANT_ID,
    MONITORING_KEY,
    PROJECT_ID,
    DATAPIZZA_OTLP_ENDPOINT,
)
from src.state import GameState
from src.sse import listen_sse
from src.api import get_restaurant_info, get_recipes, get_meals
from src.agent import build_agent

# ── Monitoring ───────────────────────────────────────────────
_instrumentor = DatapizzaMonitoringInstrumentor(
    api_key=MONITORING_KEY,
    project_id=PROJECT_ID,
    endpoint=DATAPIZZA_OTLP_ENDPOINT,
)
_instrumentor.instrument()
tracer = _instrumentor.get_tracer(__name__)

# ── Logging ──────────────────────────────────────────────────
class _Fmt(logging.Formatter):
    """Compact coloured formatter for terminal output."""

    GREY = "\033[90m"
    WHITE = "\033[97m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    LEVEL_STYLE = {
        logging.DEBUG:    (GREY,   "dbg"),
        logging.INFO:     (WHITE,  "inf"),
        logging.WARNING:  (YELLOW, "wrn"),
        logging.ERROR:    (RED,    "ERR"),
        logging.CRITICAL: (RED,    "CRT"),
    }

    def format(self, record: logging.LogRecord) -> str:
        color, tag = self.LEVEL_STYLE.get(record.levelno, (self.WHITE, "???"))
        ts = self.formatTime(record, "%H:%M:%S")
        return (
            f"{self.GREY}{ts}{self.RESET} "
            f"{color}{tag}{self.RESET}  "
            f"{record.getMessage()}"
        )


_handler = logging.StreamHandler()
_handler.setFormatter(_Fmt())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)

# Silence noisy third-party loggers
for _quiet in ("aiohttp", "urllib3", "httpcore", "httpx", "openai"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

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


PHASE_ICONS = {
    "speaking": "\U0001f4ac",   # 💬
    "closed_bid": "\U0001f4b0", # 💰
    "waiting": "\u23f3",         # ⏳
    "serving": "\U0001f354",     # 🍔
    "stopped": "\U0001f6d1",     # 🛑
}


async def on_phase_changed(phase: str):
    """React to a new game phase."""
    state.phase = phase
    icon = PHASE_ICONS.get(phase, "❓")
    logger.info("")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  %s  PHASE → %s", icon, phase.upper())
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

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
    with tracer.start_as_current_span(f"phase_{phase}"):
        await ask_agent(f"The phase just changed to '{phase}'. Decide what actions to take.")


async def on_client_spawned(data: dict):
    """A new client has arrived during serving phase."""
    state.pending_clients.append(data)
    client_name = data.get("clientName", "unknown")
    order = data.get("orderText", "")
    logger.info("\U0001f9d1 Client  %s  →  \"%s\"", client_name, order)

    with tracer.start_as_current_span("serve_client") as span:
        span.set_attribute("client.name", client_name)
        span.set_attribute("client.order", order)
        await ask_agent(
            f"A new client '{client_name}' just arrived with this order: \"{order}\". "
            f"Decide how to serve them (prepare_dish then serve_dish)."
        )


async def on_preparation_complete(data: dict):
    """A dish has finished cooking."""
    dish = data.get("dish", "")
    state.prepared_dishes.append(dish)
    logger.info("\u2705 Dish ready  →  %s", dish)

    with tracer.start_as_current_span("serve_prepared_dish") as span:
        span.set_attribute("dish.name", dish)
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
        logger.info("\U0001f916 Agent  ←  %s", prompt[:100])
        with tracer.start_as_current_span("agent_run") as span:
            span.set_attribute("agent.prompt", prompt[:200])
            result = await agent.a_run(context)
            span.set_attribute("agent.response", result.text[:200] if result.text else "")
        logger.info("\U0001f916 Agent  →  %s", result.text[:200] if result.text else "(no text)")
    except Exception as exc:
        logger.exception("Agent error: %s", exc)


# ── Event dispatcher ─────────────────────────────────────────
async def dispatch_events(event_queue: asyncio.Queue):
    """Consume events from the SSE queue and route them."""
    while True:
        event = await event_queue.get()
        etype = event.get("type", "")
        data = event.get("data", {})
        
        if etype != "heartbeat":
            logger.info("\U0001f4e8 Event  %-22s  %s", etype, json.dumps(data, default=str)[:120])

        try:
            if etype == "game_started":
                logger.info("")
                logger.info("\U0001f3ae ══════ GAME STARTED  (turn %d) ══════", state.turn_id + 1)
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
                logger.info("\U0001f4e2 Broadcast  %s  →  %s", sender, str(payload)[:160])

            elif etype == "new_message":
                sender = data.get("senderName", "?")
                text = data.get("text", "")
                logger.info("\u2709\ufe0f  DM from %s  →  %s", sender, text[:160])

            elif etype == "game_reset":
                logger.warning("\U0001f504 GAME RESET by organizers")
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

    logger.info("")
    logger.info("\U0001f355 ═══════════════════════════════════════")
    logger.info("\U0001f355  Hackapizza 2.0 — Restaurant Agent")
    logger.info("\U0001f355  ID: %s", RESTAURANT_ID)
    logger.info("\U0001f355 ═══════════════════════════════════════")
    logger.info("")

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
