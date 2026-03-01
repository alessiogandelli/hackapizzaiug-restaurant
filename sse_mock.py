"""Mock SSE server for testing — emulates the Hackapizza game server.

This mock server:
- Serves SSE events on /events/:restaurantId
- Follows the turn 9 timeline from the logs
- Spawns random clients during the serving phase
- Responds to MCP prepare_dish calls with preparation_complete events
- Provides mock endpoints for restaurant state and recipes

Run with: python sse_mock.py
Then update .env to point to http://localhost:8080
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Set, List
from aiohttp import web
import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("sse_mock")

# ── Mock Data ────────────────────────────────────────────────
MOCK_RECIPES = [
    {
        "name": "Sinfonia Cosmica di Proteine Interstellari",
        "ingredients": ["Carne di Balena spaziale", "Carne di Kraken", "Uova di Fenice"],
        "preparation_time": 45,
        "prestige": 8
    },
    {
        "name": "Galassia di Sapore",
        "ingredients": ["Carne di Xenodonte", "Pane degli Abissi", "Amido di Stellarion"],
        "preparation_time": 30,
        "prestige": 6
    },
    {
        "name": "Cosmic Serenade",
        "ingredients": ["Funghi dell'Etere", "Carne di Mucca", "Nettare di Sirena"],
        "preparation_time": 35,
        "prestige": 7
    },
    {
        "name": "Sinfonia Cosmica di Mare e Stelle",
        "ingredients": ["Essenza di Tachioni", "Plasma Vitale", "Lattuga Namecciana"],
        "preparation_time": 40,
        "prestige": 9
    }
]

MOCK_CLIENTS = [
    ("Zyx-Alpha", "Mi serve qualcosa di veloce e proteico, sono un esploratore galattico di fretta!"),
    ("Lady Nebulosa", "Desidero il piatto più prestigioso e raffinato che avete, il costo non è un problema."),
    ("Dr. Quantum", "Cerco un pasto equilibrato e di qualità, rappresento una famiglia orbitale."),
    ("Sage Cosmicus", "Voglio assaggiare la vostra ricetta più complessa e culturalmente significativa."),
    ("Captain Swift", "Ho solo 50 crediti, datemi il piatto più economico e veloce!"),
    ("Astrobarone Rex", "Portatemi il meglio che avete, rapidamente. Sono disposto a pagare bene."),
]

MOCK_INVENTORY = {
    'Carne di Kraken': 2,
    'Amido di Stellarion': 2,
    'Pane degli Abissi': 2,
    'Lattuga Namecciana': 3,
    'Carne di Balena spaziale': 7,
    'Nettare di Sirena': 3,
    'Uova di Fenice': 1
}

# ── Global State ─────────────────────────────────────────────
# Active SSE connections per restaurant
sse_queues: Dict[str, asyncio.Queue] = {}
# Dishes being prepared (restaurantId -> list of dishes)
preparing_dishes: Dict[str, List[dict]] = {}
# Current game state
game_state = {
    "phase": "stopped",
    "turn": 9,
    "started": False
}
# Mock restaurant state
restaurant_state = {
    "id": "test_restaurant",
    "name": "Test Restaurant",
    "balance": 9975.0,
    "inventory": {},
    "menu": {"items": []},
    "is_open": True
}


# ── SSE Endpoint ─────────────────────────────────────────────
async def sse_handler(request: web.Request):
    """SSE endpoint — streams events to a specific restaurant."""
    restaurant_id = request.match_info.get("restaurantId", "")
    api_key = request.headers.get("x-api-key", "")
    
    if not api_key:
        return web.Response(status=401, text="Missing API key")
    
    if not restaurant_id:
        return web.Response(status=404, text="Restaurant not found")
    
    # Check if already connected
    if restaurant_id in sse_queues:
        return web.Response(status=409, text="Restaurant already connected")
    
    # Create queue for this connection
    queue = asyncio.Queue()
    sse_queues[restaurant_id] = queue
    
    logger.info(f"SSE connection established for restaurant {restaurant_id}")
    
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    await response.prepare(request)
    
    # Send initial handshake
    await response.write(b"data: connected\n\n")
    
    try:
        while True:
            # Wait for events from the queue
            event = await queue.get()
            
            if event is None:  # Shutdown signal
                break
            
            # Send event
            data = json.dumps(event)
            message = f"data: {data}\n\n"
            await response.write(message.encode())
            
    except Exception as e:
        logger.error(f"SSE error for {restaurant_id}: {e}")
    finally:
        # Clean up
        logger.info(f"SSE connection closed for restaurant {restaurant_id}")
        sse_queues.pop(restaurant_id, None)
        
    return response


# ── Broadcast Helper ─────────────────────────────────────────
async def broadcast_event(event_type: str, data: dict):
    """Send event to all connected clients."""
    event = {"type": event_type, "data": data}
    logger.info(f"📨 Broadcasting {event_type}: {data}")
    
    for queue in sse_queues.values():
        await queue.put(event)


async def send_to_restaurant(restaurant_id: str, event_type: str, data: dict):
    """Send event to a specific restaurant."""
    event = {"type": event_type, "data": data}
    logger.info(f"📨 Sending to {restaurant_id} — {event_type}: {data}")
    
    if restaurant_id in sse_queues:
        await sse_queues[restaurant_id].put(event)


# ── Game Timeline ────────────────────────────────────────────
async def game_timeline():
    """Orchestrate the game phases according to the log timeline."""
    await asyncio.sleep(2)  # Wait for connections
    
    # Get base time
    base_time = datetime.now()
    
    # GAME STARTED
    logger.info("🎮 ══════ GAME STARTED (turn 9) ══════")
    game_state["started"] = True
    game_state["turn"] = 9
    await broadcast_event("game_started", {})
    
    # Calculate phase times (using durations from the log)
    # 19:55:41 -> 19:56:43 = 62 seconds
    closed_bid_delay = 5  # Start after 5 seconds
    # 19:56:43 -> 19:57:47 = 64 seconds
    waiting_delay = closed_bid_delay + 10
    # 19:57:47 -> 19:58:43 = 56 seconds
    serving_delay = waiting_delay + 8
    # 19:58:43 -> 20:01:43 = 180 seconds (3 minutes)
    stopped_delay = serving_delay + 20
    
    # CLOSED_BID Phase
    await asyncio.sleep(closed_bid_delay)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  💰  PHASE → CLOSED_BID")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    game_state["phase"] = "closed_bid"
    await broadcast_event("game_phase_changed", {"phase": "closed_bid"})
    
    # After closed_bid, send bid results message
    await asyncio.sleep(waiting_delay - closed_bid_delay - 1)
    await broadcast_event("message", {
        "sender": "server",
        "payload": "Restaurant 24 try to buy:1 Radici di Gravità at single price of: 69 result:Bought 1 Radici di Gravità for 69\nRestaurant 14 try to buy:2 Radici di Gravità at single price of: 40 result:Bought 0"
    })
    
    # WAITING Phase
    await asyncio.sleep(1)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  ⏳  PHASE → WAITING")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    game_state["phase"] = "waiting"
    restaurant_state["balance"] = 9503.0
    restaurant_state["inventory"] = MOCK_INVENTORY.copy()
    await broadcast_event("game_phase_changed", {"phase": "waiting"})
    
    # SERVING Phase
    await asyncio.sleep(serving_delay - waiting_delay)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  🍔  PHASE → SERVING")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    game_state["phase"] = "serving"
    await broadcast_event("game_phase_changed", {"phase": "serving"})
    
    # Spawn random clients during serving
    client_task = asyncio.create_task(spawn_clients_randomly(stopped_delay - serving_delay))
    
    # STOPPED Phase
    await asyncio.sleep(stopped_delay - serving_delay)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  🛑  PHASE → STOPPED")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    game_state["phase"] = "stopped"
    restaurant_state["inventory"] = {}
    await broadcast_event("game_phase_changed", {"phase": "stopped"})
    
    # Cancel client spawning
    client_task.cancel()


async def spawn_clients_randomly(duration: float):
    """Spawn random clients during the serving phase."""
    end_time = time.time() + duration
    
    while time.time() < end_time:
        # Wait random time between 2-8 seconds
        await asyncio.sleep(random.uniform(2, 8))
        
        if game_state["phase"] != "serving":
            break
        
        # Pick random client
        client_name, order_text = random.choice(MOCK_CLIENTS)
        
        # Send to all restaurants (they filter their own)
        for restaurant_id in list(sse_queues.keys()):
            await send_to_restaurant(
                restaurant_id,
                "client_spawned",
                {
                    "clientName": client_name,
                    "orderText": order_text
                }
            )


async def preparation_monitor():
    """Monitor dishes being prepared and emit completion events."""
    while True:
        await asyncio.sleep(1)
        
        for restaurant_id, dishes in list(preparing_dishes.items()):
            completed = []
            
            for dish_info in dishes:
                # Check if preparation time has elapsed
                if time.time() >= dish_info["complete_at"]:
                    await send_to_restaurant(
                        restaurant_id,
                        "preparation_complete",
                        {"dish": dish_info["name"]}
                    )
                    completed.append(dish_info)
            
            # Remove completed dishes
            for dish_info in completed:
                dishes.remove(dish_info)


# ── Heartbeat ────────────────────────────────────────────────
async def heartbeat():
    """Send periodic heartbeat events."""
    while True:
        await asyncio.sleep(30)
        await broadcast_event("heartbeat", {"ts": int(time.time() * 1000)})


# ── MCP Endpoint ─────────────────────────────────────────────
async def mcp_handler(request: web.Request):
    """Handle MCP tool calls (JSON-RPC)."""
    api_key = request.headers.get("x-api-key", "")
    if not api_key:
        return web.Response(status=401, text="Missing API key")
    
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    
    logger.info(f"MCP call: {method} with params {params}")
    
    if method != "tools/call":
        return web.json_response({
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32601, "message": "Method not found"}
        })
    
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    
    # Handle different tools
    result = {"isError": False, "content": [{"type": "text", "text": "Success"}]}
    
    if tool_name == "prepare_dish":
        dish_name = arguments.get("name")
        restaurant_id = arguments.get("restaurant_id", "test_restaurant")
        
        # Find recipe
        recipe = next((r for r in MOCK_RECIPES if r["name"] == dish_name), None)
        if not recipe:
            result = {
                "isError": True,
                "content": [{"type": "text", "text": f"Recipe '{dish_name}' not found"}]
            }
        else:
            # Start preparation
            prep_time = recipe["preparation_time"]
            complete_at = time.time() + prep_time
            
            if restaurant_id not in preparing_dishes:
                preparing_dishes[restaurant_id] = []
            
            preparing_dishes[restaurant_id].append({
                "name": dish_name,
                "complete_at": complete_at
            })
            
            result["content"][0]["text"] = f"Started preparing '{dish_name}' (will complete in {prep_time}s)"
    
    elif tool_name == "serve_dish":
        dish_name = arguments.get("dish_name")
        client_name = arguments.get("client_name")
        result["content"][0]["text"] = f"Served '{dish_name}' to {client_name}"
    
    elif tool_name == "save_menu":
        items = arguments.get("items", [])
        restaurant_state["menu"]["items"] = items
        result["content"][0]["text"] = f"Menu updated with {len(items)} items"
    
    elif tool_name == "closed_bid":
        bids = arguments.get("bids", [])
        result["content"][0]["text"] = f"Bid submitted for {len(bids)} ingredients"
    
    elif tool_name == "update_restaurant_is_open":
        is_open = arguments.get("is_open", True)
        restaurant_state["is_open"] = is_open
        result["content"][0]["text"] = f"Restaurant {'opened' if is_open else 'closed'}"
    
    else:
        result = {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not implemented"}]
        }
    
    return web.json_response({
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "result": result
    })


# ── HTTP Endpoints ───────────────────────────────────────────
async def get_recipes(request: web.Request):
    """Return available recipes."""
    return web.json_response(MOCK_RECIPES)


async def get_restaurant(request: web.Request):
    """Return restaurant state."""
    restaurant_id = request.match_info.get("id", "")
    api_key = request.headers.get("x-api-key", "")
    
    if not api_key:
        return web.Response(status=401, text="Missing API key")
    
    return web.json_response(restaurant_state)


async def get_menu(request: web.Request):
    """Return restaurant menu."""
    return web.json_response(restaurant_state["menu"]["items"])


async def get_meals(request: web.Request):
    """Return meals for a turn."""
    return web.json_response([])


async def get_restaurants(request: web.Request):
    """Return all restaurants."""
    return web.json_response([restaurant_state])


async def get_market_entries(request: web.Request):
    """Return market entries."""
    return web.json_response([])


async def get_bid_history(request: web.Request):
    """Return bid history."""
    return web.json_response([])


# ── Application ──────────────────────────────────────────────
async def start_background_tasks(app):
    """Start background tasks."""
    app['timeline_task'] = asyncio.create_task(game_timeline())
    app['heartbeat_task'] = asyncio.create_task(heartbeat())
    app['prep_monitor_task'] = asyncio.create_task(preparation_monitor())


async def cleanup_background_tasks(app):
    """Clean up background tasks."""
    app['timeline_task'].cancel()
    app['heartbeat_task'].cancel()
    app['prep_monitor_task'].cancel()
    
    await app['timeline_task']
    await app['heartbeat_task']
    await app['prep_monitor_task']


def create_app():
    """Create and configure the application."""
    app = web.Application()
    
    # Routes
    app.router.add_get('/events/{restaurantId}', sse_handler)
    app.router.add_post('/mcp', mcp_handler)
    app.router.add_get('/recipes', get_recipes)
    app.router.add_get('/restaurant/{id}', get_restaurant)
    app.router.add_get('/restaurant/{id}/menu', get_menu)
    app.router.add_get('/meals', get_meals)
    app.router.add_get('/restaurants', get_restaurants)
    app.router.add_get('/market/entries', get_market_entries)
    app.router.add_get('/bid_history', get_bid_history)
    
    # Background tasks
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    return app


def main():
    """Run the mock server."""
    logger.info("=" * 60)
    logger.info("🍕 HACKAPIZZA MOCK SERVER")
    logger.info("=" * 60)
    logger.info("Starting mock SSE server on http://localhost:8080")
    logger.info("Update your .env to:")
    logger.info("  SERVER_URL=http://localhost:8080")
    logger.info("  RESTAURANT_ID=test_restaurant")
    logger.info("=" * 60)
    
    app = create_app()
    web.run_app(app, host='localhost', port=8080)


if __name__ == "__main__":
    main()
