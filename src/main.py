"""Main entry point — event loop that connects SSE → state → orchestrator → agents."""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path

from datapizza.tracing import DatapizzaMonitoringInstrumentor

from src.config import (
    RESTAURANT_ID,
    MONITORING_KEY,
    PROJECT_ID,
    DATAPIZZA_OTLP_ENDPOINT,
)
from src.state import GameState
from src.memory import GameMemory
from src.sse import listen_sse
from src.api import get_restaurant_info
from src.agents import build_agents
from src.orchestrator import PhaseController

# ── Logs directory ───────────────────────────────────────────
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

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


# Console handler (coloured)
_handler = logging.StreamHandler()
_handler.setFormatter(_Fmt())

# File handler (plain text, full detail)
_file_handler = logging.FileHandler(LOGS_DIR / "game.log", mode="a")
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

logging.root.handlers = [_handler, _file_handler]
logging.root.setLevel(logging.INFO)


def setup_turn_log_file(turn_id: int) -> None:
    """Switch logging to a new file for the current turn."""
    global _file_handler
    
    # Remove old file handler if it exists
    if _file_handler in logging.root.handlers:
        logging.root.handlers.remove(_file_handler)
        _file_handler.close()
    
    # Create new file handler for this turn
    log_file = LOGS_DIR / f"turn_{turn_id}.log"
    _file_handler = logging.FileHandler(log_file, mode="a")
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.root.handlers.append(_file_handler)
    logger.info("📝 Logging to %s", log_file.name)

# Silence noisy third-party loggers
for _quiet in ("aiohttp", "urllib3", "httpcore", "httpx", "openai"):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

logger = logging.getLogger("hackapizza")

# ── Globals ──────────────────────────────────────────────────
state = GameState()
memory = GameMemory()
controller: PhaseController | None = None  # built lazily after agents init


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
    """React to a new game phase — delegate to PhaseController."""
    icon = PHASE_ICONS.get(phase, "❓")
    logger.info("")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  %s  PHASE → %s", icon, phase.upper())
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if controller is None:
        logger.warning("Controller not ready — skipping phase %s", phase)
        return

    with tracer.start_as_current_span(f"phase_{phase}"):
        await controller.handle_phase(phase)


async def on_client_spawned(data: dict):
    """A new client has arrived during serving phase."""
    client_name = data.get("clientName", "unknown")
    order = data.get("orderText", "")
    intolerances = data.get("intolerances", [])
    logger.info("\U0001f9d1 Client  %s  →  \"%s\"  intolerances=%s", client_name, order, intolerances)

    if controller is None:
        logger.warning("Controller not ready — cannot serve client")
        return

    with tracer.start_as_current_span("serve_client") as span:
        span.set_attribute("client.name", client_name)
        span.set_attribute("client.order", order)
        await controller.handle_client(data)


async def on_preparation_complete(data: dict):
    """A dish has finished cooking."""
    dish = data.get("dish", "")
    logger.info("\u2705 Dish ready  →  %s", dish)

    if controller is None:
        return

    with tracer.start_as_current_span("serve_prepared_dish") as span:
        span.set_attribute("dish.name", dish)
        await controller.handle_preparation_complete(data)


# ── Event dispatcher ─────────────────────────────────────────
async def dispatch_events(event_queue: asyncio.Queue):
    """Consume events from the SSE queue and route them."""
    while True:
        event = await event_queue.get()
        etype = event.get("type", "")
        raw_data = event.get("data", {})

        if etype != "heartbeat":
            logger.debug("📦 Raw event — type=%s, data type=%s, data=%r",
                         etype, type(raw_data).__name__, str(raw_data)[:500])

        # Normalize: SSE parser wraps strings as {"value": ...}, but some
        # events arrive as raw strings.  Ensure `data` is always a dict.
        if isinstance(raw_data, str):
            logger.info("⚠️  Event '%s' data is str, wrapping: %r", etype, raw_data[:200])
            data = {"value": raw_data}
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            logger.info("⚠️  Event '%s' data is %s, wrapping: %r",
                        etype, type(raw_data).__name__, str(raw_data)[:200])
            data = {"value": raw_data}
        
        if etype != "heartbeat":
            logger.info("\U0001f4e8 Event  %-22s  %s", etype, json.dumps(data, default=str)[:200])

        try:
            if etype == "game_started":
                # Parse turn_id from the event payload
                new_turn_id = data.get("turn_id")
                if new_turn_id is not None:
                    state.turn_id = new_turn_id
                    setup_turn_log_file(state.turn_id)
                logger.info("")
                logger.info("\U0001f3ae ══════ GAME STARTED  (turn %d) ══════", state.turn_id)
                await refresh_state()

                # Run SpeakingAgent immediately to set menu + open restaurant
                if controller is not None:
                    logger.info("🚀 Running SpeakingAgent at game start …")
                    with tracer.start_as_current_span("game_start_speaking"):
                        await controller.handle_phase("speaking")
                else:
                    logger.warning("Controller not ready — cannot run SpeakingAgent at game start")

            elif etype == "game_phase_changed":
                phase = data.get("phase") or data.get("value", "")
                logger.debug("  phase_changed — extracted phase=%r (type=%s) from data=%r",
                             phase, type(phase).__name__, str(data)[:300])
                if not isinstance(phase, str) or not phase:
                    logger.error("  ⚠️  Invalid phase value! type=%s, value=%r, full data=%r",
                                 type(phase).__name__, phase, str(data)[:500])
                await on_phase_changed(phase)

            elif etype == "client_spawned":
                logger.debug("  client_spawned — data type=%s, keys=%s, data=%r",
                             type(data).__name__,
                             list(data.keys()) if isinstance(data, dict) else 'N/A',
                             str(data)[:500])
                await on_client_spawned(data)

            elif etype == "preparation_complete":
                logger.debug("  preparation_complete — data type=%s, data=%r",
                             type(data).__name__, str(data)[:500])
                await on_preparation_complete(data)

            elif etype == "message":
                sender = data.get("sender", "?")
                payload = data.get("payload") or data.get("value", "")
                logger.info("\U0001f4e2 Broadcast  %s  →  %s", sender, str(payload)[:160])

            elif etype == "new_message":
                sender = data.get("senderName", "?")
                text = data.get("text") or data.get("value", "")
                logger.info("\u2709\ufe0f  DM from %s  →  %s", sender, text[:160])
                # Track incoming messages for planner/speaking agent
                if memory is not None:
                    memory.record_message(sender, text)

            elif etype == "game_reset":
                logger.warning("\U0001f504 GAME RESET by organizers")
                state.__init__()
                memory.__init__()

            elif etype == "heartbeat":
                pass  # silently ignore

            else:
                logger.debug("Unhandled event type: %s", etype)

        except Exception as exc:
            logger.exception(
                "Error handling event %s: %s\n"
                "  → event data type: %s\n"
                "  → event data dump: %r\n"
                "  → raw_data type: %s\n"
                "  → raw_data dump: %r",
                etype, exc,
                type(data).__name__, str(data)[:500],
                type(raw_data).__name__, str(raw_data)[:500],
            )


# ── Main ─────────────────────────────────────────────────────
async def main():
    global controller

    logger.info("")
    logger.info("\U0001f355 ═══════════════════════════════════════")
    logger.info("\U0001f355  Hackapizza 2.0 — Multi-Agent System")
    logger.info("\U0001f355  ID: %s", RESTAURANT_ID)
    logger.info("\U0001f355  Architecture: Planner → PhaseController → Specialists")
    logger.info("\U0001f355 ═══════════════════════════════════════")
    logger.info("")

    # Build all agents (fetches MCP tools from the server)
    try:
        agents = build_agents()
        controller = PhaseController(
            agents=agents,
            state=state,
            memory=memory,
            tracer=tracer,
        )
        logger.info("Multi-agent system ready — %d agents built", len(agents))
    except Exception as exc:
        logger.error("Failed to build agents (is the server up?): %s", exc)
        logger.info("Running in listen-only mode — will retry on next restart")

    # SSE event queue
    event_queue: asyncio.Queue = asyncio.Queue()

    # Launch SSE listener + event dispatcher concurrently
    await asyncio.gather(
        listen_sse(event_queue),
        dispatch_events(event_queue),
    )


if __name__ == "__main__":
    asyncio.run(main())
