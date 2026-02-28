# API Examples & Cookbook

Practical examples for common operations with the Hackapizza 2.0 agent system.

---

## Table of Contents

1. [REST API Examples](#rest-api-examples)
2. [Custom Event Handlers](#custom-event-handlers)
3. [Agent Prompting Examples](#agent-prompting-examples)
4. [State Queries](#state-queries)
5. [Testing Examples](#testing-examples)
6. [Production Patterns](#production-patterns)

---

## REST API Examples

All examples assume you have configured your environment and imported the necessary modules.

### Get Current Restaurant Status

```python
from src.api import get_restaurant_info

async def check_status():
    info = await get_restaurant_info()
    
    print(f"Restaurant: {info['name']}")
    print(f"Balance: ${info['balance']}")
    print(f"Turn: {info['turn_id']}")
    print(f"Inventory items: {len(info['inventory'])}")
    
    for item in info['inventory']:
        print(f"  - {item['name']}: {item['quantity']} units")
```

**Output:**
```
Restaurant: Cosmic Kitchen
Balance: $1250.5
Turn: 7
Inventory items: 5
  - flour: 10 units
  - tomato: 8 units
  - cheese: 5 units
```

### List All Available Recipes

```python
from src.api import get_recipes

async def show_recipes():
    recipes = await get_recipes()
    
    for recipe in recipes:
        print(f"\n{recipe['name']} (ID: {recipe['id']})")
        print(f"  Prep time: {recipe['preparation_time']}s")
        print(f"  Ingredients:")
        
        for ing in recipe['ingredients']:
            print(f"    - {ing['name']}: {ing['quantity']}")
```

**Output:**
```
Cosmic Pizza (ID: recipe_001)
  Prep time: 30s
  Ingredients:
    - flour: 2
    - tomato: 1
    - cheese: 1

Nebula Pasta (ID: recipe_002)
  Prep time: 45s
  Ingredients:
    - flour: 1
    - butter: 2
```

### Check Menu and Pricing

```python
from src.api import get_menu

async def check_menu():
    menu = await get_menu()
    
    if not menu:
        print("Menu is empty!")
        return
    
    print("Current Menu:")
    for item in menu:
        print(f"  {item['recipe_name']}: ${item['price']}")
```

### Get Meal History

```python
from src.api import get_meals

async def review_turn(turn_id: int):
    meals = await get_meals(turn_id)
    
    total_revenue = 0
    
    for meal in meals:
        client = meal.get('client_name', 'Unknown')
        dish = meal.get('dish', 'Unknown')
        price = meal.get('price', 0)
        paid = meal.get('paid', False)
        
        status = "✅ Paid" if paid else "❌ Not paid"
        
        print(f"{client}: {dish} (${price}) {status}")
        
        if paid:
            total_revenue += price
    
    print(f"\nTotal revenue: ${total_revenue}")
```

### Query Market Entries

```python
from src.api import get_market_entries

async def browse_market():
    entries = await get_market_entries()
    
    print("Available on market:")
    for entry in entries:
        seller = entry.get('seller_name', 'Unknown')
        ingredient = entry.get('ingredient', 'Unknown')
        quantity = entry.get('quantity', 0)
        price = entry.get('price_per_unit', 0)
        
        print(f"  {ingredient} x{quantity} @ ${price}/unit (from {seller})")
```

---

## Custom Event Handlers

### Add a New Event Type Handler

```python
# In src/main.py, inside dispatch_events()

async def dispatch_events(event_queue: asyncio.Queue):
    while True:
        event = await event_queue.get()
        etype = event.get("type", "")
        data = event.get("data", {})

        try:
            # ... existing handlers ...
            
            elif etype == "market_entry_sold":
                await on_market_sale(data)
            
            elif etype == "bid_won":
                await on_bid_won(data)
            
            # ... rest of handlers ...
            
        except Exception as exc:
            logger.exception("Error handling event %s: %s", etype, exc)


# Define the new handlers
async def on_market_sale(data: dict):
    """Handle when our market entry is purchased."""
    buyer = data.get("buyer_name", "unknown")
    ingredient = data.get("ingredient", "")
    quantity = data.get("quantity", 0)
    revenue = data.get("total_price", 0)
    
    logger.info("Market sale: %s bought %d %s for $%.2f", 
                buyer, quantity, ingredient, revenue)
    
    # Ask agent to adjust pricing strategy
    await ask_agent(
        f"We just sold {quantity} {ingredient} for ${revenue}. "
        f"Consider adjusting market prices based on demand."
    )


async def on_bid_won(data: dict):
    """Handle when our bid wins."""
    ingredient = data.get("ingredient", "")
    quantity = data.get("quantity", 0)
    cost = data.get("total_cost", 0)
    
    logger.info("Bid won: %s x%d for $%.2f", ingredient, quantity, cost)
    
    # Update inventory tracking
    state.inventory.append({"name": ingredient, "quantity": quantity})
    state.balance -= cost
```

### Implement Rate Limiting

```python
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
    
    async def acquire(self):
        now = time.time()
        
        # Remove old calls outside the window
        while self.calls and self.calls[0] < now - self.period:
            self.calls.popleft()
        
        # Check if we're at the limit
        if len(self.calls) >= self.max_calls:
            sleep_time = self.calls[0] - (now - self.period)
            if sleep_time > 0:
                logger.info("Rate limit reached, waiting %.1fs", sleep_time)
                await asyncio.sleep(sleep_time)
        
        self.calls.append(time.time())

# Usage
agent_rate_limiter = RateLimiter(max_calls=10, period=60)  # 10 calls/minute

async def ask_agent(prompt: str):
    await agent_rate_limiter.acquire()
    
    # ... rest of ask_agent implementation ...
```

---

## Agent Prompting Examples

### Strategic Phase-Specific Prompts

```python
# In src/main.py, enhance on_phase_changed()

async def on_phase_changed(phase: str):
    state.phase = phase
    logger.info("━━━ Phase changed → %s ━━━", phase)
    
    await refresh_state()
    
    if phase == "speaking":
        await ask_agent(
            f"SPEAKING PHASE STRATEGY:\n"
            f"- Current balance: ${state.balance}\n"
            f"- Inventory: {len(state.inventory)} items\n"
            f"- Review recipes and set COMPETITIVE menu prices\n"
            f"- List excess ingredients on market BEFORE they expire\n"
            f"- Consider other restaurants' pricing"
        )
    
    elif phase == "closed_bid":
        # Calculate what we need
        needed = analyze_ingredient_needs()
        
        await ask_agent(
            f"CLOSED BID STRATEGY:\n"
            f"- Budget: ${state.balance}\n"
            f"- Needed ingredients: {needed}\n"
            f"- Submit BLIND bids (others can't see your offer)\n"
            f"- Only bid what you can afford AND will use\n"
            f"- Remember: ingredients EXPIRE at turn end!"
        )
    
    elif phase == "waiting":
        await ask_agent(
            f"WAITING PHASE CHECKLIST:\n"
            f"1. Finalize menu (save_menu tool)\n"
            f"2. Buy last-minute ingredients from market if needed\n"
            f"3. Sell remaining excess inventory\n"
            f"4. Prepare for incoming clients\n"
            f"Current ready dishes in menu: {len(state.menu)}"
        )
    
    elif phase == "serving":
        await ask_agent(
            f"SERVING PHASE:\n"
            f"- Wait for client_spawned events\n"
            f"- Check EVERY client's intolerances carefully\n"
            f"- Prepare dishes one by one\n"
            f"- Serve promptly when preparation_complete fires\n"
            f"- Monitor balance: currently ${state.balance}"
        )


def analyze_ingredient_needs() -> dict:
    """Calculate what ingredients we need based on menu."""
    needed = {}
    
    for menu_item in state.menu:
        recipe = next((r for r in state.recipes if r['id'] == menu_item['recipe_id']), None)
        if recipe:
            for ing in recipe['ingredients']:
                needed[ing['name']] = needed.get(ing['name'], 0) + ing['quantity']
    
    # Subtract current inventory
    for inv_item in state.inventory:
        if inv_item['name'] in needed:
            needed[inv_item['name']] -= inv_item['quantity']
    
    # Filter to only shortages
    return {k: v for k, v in needed.items() if v > 0}
```

### Context-Aware Client Handling

```python
async def on_client_spawned(data: dict):
    client_name = data.get("clientName", "unknown")
    order = data.get("orderText", "")
    intolerances = data.get("intolerances", [])
    special_requests = data.get("specialRequests", "")
    
    state.pending_clients.append(data)
    
    # Build detailed context
    intolerance_warning = ""
    if intolerances:
        intolerance_warning = (
            f"⚠️ CRITICAL: Client is intolerant to: {', '.join(intolerances)}\n"
            f"Serving these ingredients will cause SEVERE penalty!\n"
        )
    
    # Find matching recipes
    matching_recipes = find_recipes_for_order(order, intolerances)
    
    await ask_agent(
        f"NEW CLIENT ALERT:\n"
        f"Name: {client_name}\n"
        f"Order: \"{order}\"\n"
        f"{intolerance_warning}"
        f"Special requests: {special_requests or 'None'}\n\n"
        f"Suggested recipes (safe to serve):\n"
        f"{format_recipe_list(matching_recipes)}\n\n"
        f"ACTION REQUIRED:\n"
        f"1. Choose appropriate dish from menu\n"
        f"2. Use prepare_dish tool\n"
        f"3. Wait for preparation_complete event\n"
        f"4. Use serve_dish tool"
    )


def find_recipes_for_order(order_text: str, intolerances: list) -> list:
    """Find recipes that match order and avoid intolerances."""
    order_lower = order_text.lower()
    matches = []
    
    for recipe in state.recipes:
        # Check if recipe name matches order
        if recipe['name'].lower() in order_lower or order_lower in recipe['name'].lower():
            # Check for intolerances
            recipe_ingredients = [ing['name'] for ing in recipe['ingredients']]
            has_intolerance = any(intol in recipe_ingredients for intol in intolerances)
            
            if not has_intolerance:
                matches.append(recipe)
    
    return matches


def format_recipe_list(recipes: list) -> str:
    if not recipes:
        return "  ⚠️ No safe recipes found!"
    
    lines = []
    for recipe in recipes:
        ingredients = ", ".join(ing['name'] for ing in recipe['ingredients'])
        lines.append(f"  - {recipe['name']}: {ingredients}")
    
    return "\n".join(lines)
```

---

## State Queries

### Check if We Can Afford Something

```python
def can_afford(amount: float) -> bool:
    """Check if we have enough balance."""
    return state.balance >= amount


def get_affordable_market_entries():
    """Filter market to only affordable entries."""
    affordable = []
    
    for entry in state.market_entries:
        total_cost = entry['price_per_unit'] * entry['quantity']
        if can_afford(total_cost):
            affordable.append(entry)
    
    return affordable
```

### Find Recipes We Can Make

```python
def get_cookable_recipes() -> list:
    """Return recipes we have ingredients for."""
    cookable = []
    
    for recipe in state.recipes:
        can_make = True
        
        for ing in recipe['ingredients']:
            have = next((i['quantity'] for i in state.inventory if i['name'] == ing['name']), 0)
            
            if have < ing['quantity']:
                can_make = False
                break
        
        if can_make:
            cookable.append(recipe)
    
    return cookable


# Use in agent prompt
async def suggest_menu():
    cookable = get_cookable_recipes()
    
    await ask_agent(
        f"You can currently make these recipes:\n"
        f"{format_recipe_list(cookable)}\n"
        f"Update the menu to include profitable dishes."
    )
```

### Inventory Analysis

```python
def get_expiring_soon() -> list:
    """All inventory expires at turn end, so everything is 'expiring soon'."""
    return state.inventory.copy()


def get_excess_inventory() -> list:
    """Find ingredients we have but aren't using in any menu item."""
    used_ingredients = set()
    
    for menu_item in state.menu:
        recipe = next((r for r in state.recipes if r['id'] == menu_item['recipe_id']), None)
        if recipe:
            used_ingredients.update(ing['name'] for ing in recipe['ingredients'])
    
    excess = []
    for item in state.inventory:
        if item['name'] not in used_ingredients:
            excess.append(item)
    
    return excess


# Trigger cleanup
async def cleanup_inventory():
    excess = get_excess_inventory()
    
    if excess:
        await ask_agent(
            f"URGENT: You have excess ingredients that will EXPIRE:\n"
            f"{format_inventory(excess)}\n"
            f"Sell them on the market NOW to recover value!"
        )


def format_inventory(items: list) -> str:
    return "\n".join(f"  - {item['name']}: {item['quantity']}" for item in items)
```

---

## Testing Examples

### Mock SSE Events for Testing

```python
import asyncio
from src.main import dispatch_events, state

async def test_client_flow():
    """Test the full client serving workflow."""
    queue = asyncio.Queue()
    
    # Simulate phase change
    await queue.put({
        "type": "game_phase_changed",
        "data": {"phase": "serving"}
    })
    
    # Simulate client arrival
    await queue.put({
        "type": "client_spawned",
        "data": {
            "clientName": "Test Client",
            "orderText": "I want a pizza",
            "intolerances": ["mushroom"]
        }
    })
    
    # Simulate dish completion
    await queue.put({
        "type": "preparation_complete",
        "data": {"dish": "Cosmic Pizza"}
    })
    
    # Run dispatcher briefly
    task = asyncio.create_task(dispatch_events(queue))
    await asyncio.sleep(1)
    task.cancel()
    
    # Assertions
    assert state.phase == "serving"
    assert len(state.pending_clients) == 1
    assert "Cosmic Pizza" in state.prepared_dishes


if __name__ == "__main__":
    asyncio.run(test_client_flow())
```

### Mock Agent for Testing

```python
class MockAgent:
    """Fake agent for testing without LLM calls."""
    
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []
    
    async def a_run(self, context: str):
        self.calls.append(context)
        
        # Return canned response based on context content
        for keyword, response in self.responses.items():
            if keyword in context:
                return MockResult(response)
        
        return MockResult("No action taken")


class MockResult:
    def __init__(self, text: str):
        self.text = text


# Use in tests
async def test_with_mock_agent():
    from src import main
    
    mock = MockAgent({
        "client_spawned": "I will prepare Cosmic Pizza",
        "preparation_complete": "I will serve the dish"
    })
    
    main.agent = mock
    
    await main.ask_agent("A new client arrived")
    
    assert len(mock.calls) == 1
    assert "client arrived" in mock.calls[0]
```

---

## Production Patterns

### Graceful Shutdown

```python
import signal

shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    logger.info("Shutdown signal received")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def main():
    # ... setup ...
    
    try:
        while not shutdown_requested:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
    finally:
        logger.info("Cleaning up...")
        # Release SSE lock, close connections, etc.
```

### Structured Logging

```python
import json
import logging

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "turn_id": state.turn_id,
            "phase": state.phase,
            "balance": state.balance
        }
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


# Use it
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger()
logger.addHandler(handler)
```

### Health Check Endpoint

```python
from aiohttp import web

async def health_check(request):
    """HTTP endpoint for monitoring."""
    status = {
        "status": "healthy" if agent is not None else "degraded",
        "turn": state.turn_id,
        "phase": state.phase,
        "balance": state.balance,
        "pending_clients": len(state.pending_clients)
    }
    
    return web.json_response(status)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "localhost", 8080)
    await site.start()
    
    logger.info("Health check server running on http://localhost:8080/health")


# In main()
await asyncio.gather(
    listen_sse(event_queue),
    dispatch_events(event_queue),
    start_health_server(),  # Add health check
)
```

### Persistent State Snapshots

```python
import json
from pathlib import Path

SNAPSHOT_FILE = Path("state_snapshot.json")

def save_state_snapshot():
    """Save state to disk for crash recovery."""
    snapshot = {
        "turn_id": state.turn_id,
        "phase": state.phase,
        "balance": state.balance,
        "inventory": state.inventory,
        "menu": state.menu,
        "timestamp": time.time()
    }
    
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2))
    logger.debug("State snapshot saved")


def load_state_snapshot():
    """Restore state from disk."""
    if not SNAPSHOT_FILE.exists():
        return
    
    try:
        snapshot = json.loads(SNAPSHOT_FILE.read_text())
        
        state.turn_id = snapshot["turn_id"]
        state.phase = snapshot["phase"]
        state.balance = snapshot["balance"]
        state.inventory = snapshot["inventory"]
        state.menu = snapshot["menu"]
        
        logger.info("State restored from snapshot (turn %d)", state.turn_id)
    except Exception as exc:
        logger.warning("Could not load snapshot: %s", exc)


# Call periodically
async def periodic_snapshot():
    while True:
        await asyncio.sleep(30)  # Every 30 seconds
        save_state_snapshot()


# In main()
await asyncio.gather(
    listen_sse(event_queue),
    dispatch_events(event_queue),
    periodic_snapshot(),
)
```

---

## Advanced Patterns

### Multi-Step Agent Workflows

```python
async def complex_serving_workflow(client_data: dict):
    """Multi-step workflow with validation."""
    
    client_name = client_data['clientName']
    order = client_data['orderText']
    intolerances = client_data.get('intolerances', [])
    
    # Step 1: Analyze order
    analysis_result = await ask_agent(
        f"Analyze this order: \"{order}\"\n"
        f"Which recipe from our menu best matches?"
    )
    
    # Extract recipe name from agent response (simplified)
    recipe_name = extract_recipe_name(analysis_result.text)
    
    # Step 2: Validate safety
    if not is_safe_for_client(recipe_name, intolerances):
        logger.warning("Recipe %s unsafe for %s", recipe_name, client_name)
        
        await ask_agent(
            f"CRITICAL: {recipe_name} contains intolerant ingredients!\n"
            f"Find an alternative recipe or inform client we cannot serve them."
        )
        return
    
    # Step 3: Prepare
    logger.info("Preparing %s for %s", recipe_name, client_name)
    await ask_agent(f"Use prepare_dish tool for {recipe_name}")
    
    # Note: serve step happens later in on_preparation_complete


def is_safe_for_client(recipe_name: str, intolerances: list) -> bool:
    recipe = next((r for r in state.recipes if r['name'] == recipe_name), None)
    if not recipe:
        return False
    
    recipe_ingredients = [ing['name'] for ing in recipe['ingredients']]
    return not any(intol in recipe_ingredients for intol in intolerances)
```

---

## Debugging Helpers

### Context Dumper

```python
def dump_full_context():
    """Print everything the agent can see."""
    print("=" * 60)
    print("FULL GAME CONTEXT")
    print("=" * 60)
    print(f"\nPhase: {state.phase}")
    print(f"Turn: {state.turn_id}")
    print(f"Balance: ${state.balance}")
    
    print(f"\nInventory ({len(state.inventory)} items):")
    for item in state.inventory:
        print(f"  - {item['name']}: {item['quantity']}")
    
    print(f"\nMenu ({len(state.menu)} items):")
    for item in state.menu:
        print(f"  - {item.get('recipe_name', 'Unknown')}: ${item.get('price', 0)}")
    
    print(f"\nPending Clients ({len(state.pending_clients)}):")
    for client in state.pending_clients:
        print(f"  - {client.get('clientName')}: {client.get('orderText')}")
    
    print(f"\nPrepared Dishes ({len(state.prepared_dishes)}):")
    for dish in state.prepared_dishes:
        print(f"  - {dish}")
    
    print("=" * 60)


# Call when debugging
# dump_full_context()
```

---

This cookbook provides practical patterns for extending and debugging the Hackapizza 2.0 agent. For architectural details, see [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md).

**Last Updated**: 2026-02-28
