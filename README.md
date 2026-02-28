# Hackapizza 2.0 - Autonomous Restaurant Agent 🍕🤖

An autonomous AI agent for managing a galactic restaurant in the Hackapizza 2.0 competition. This system connects to a game server via Server-Sent Events (SSE), tracks game state, and uses an AI agent to make strategic decisions across different game phases.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Components](#components)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Game Phases](#game-phases)
- [Event Flow](#event-flow)
- [API Reference](#api-reference)

---

## Overview

This agent autonomously manages a restaurant in the Hackapizza 2.0 game by:

- **Listening** to real-time game events via Server-Sent Events (SSE)
- **Tracking** game state (inventory, balance, menu, clients, etc.)
- **Deciding** actions through an AI agent powered by the datapizza-ai framework
- **Executing** actions via Model Context Protocol (MCP) tools provided by the game server

The agent operates continuously, reacting to game phase changes, client arrivals, and cooking completions to maximize restaurant profitability.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Game Server                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  SSE Stream  │  │  REST APIs   │  │  MCP Tools   │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
└─────────┼──────────────────┼──────────────────┼─────────────┘
          │                  │                  │
          │ Events           │ HTTP GET         │ Tool Calls
          ↓                  ↓                  ↓
┌─────────────────────────────────────────────────────────────┐
│                      Restaurant Agent                        │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  sse.py - SSE Listener with file lock                 │  │
│  │  • Receives real-time events                          │  │
│  │  • Auto-reconnect with backoff                        │  │
│  └────────────────┬─────────────────────────────────────┘  │
│                   │ event_queue                             │
│                   ↓                                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  main.py - Event Dispatcher & Orchestrator           │  │
│  │  • Routes events to handlers                          │  │
│  │  • Triggers agent on key events                       │  │
│  └────────┬───────────────────────────┬──────────────────┘  │
│           │                           │                      │
│           ↓                           ↓                      │
│  ┌─────────────────┐        ┌──────────────────┐           │
│  │  state.py       │←───────│   agent.py       │           │
│  │  Game State     │        │   AI Decision    │           │
│  │  • phase        │        │   Maker          │           │
│  │  • inventory    │        │   • MCP tools    │           │
│  │  • balance      │        │   • LLM client   │           │
│  │  • clients      │        │   • Planning     │           │
│  └─────────────────┘        └──────────────────┘           │
│           ↑                                                  │
│           │                                                  │
│  ┌────────┴────────────────────────────────────────────┐   │
│  │  api.py - REST API Client                           │   │
│  │  • get_restaurant_info, get_recipes, get_meals, ... │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  config.py - Configuration from .env                 │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

---

## How It Works

### 1. **Initialization**
- Loads configuration from `.env` file
- Builds AI agent with MCP tools from game server
- Establishes SSE connection (with file lock to prevent duplicate connections)
- Starts event dispatcher

### 2. **Event Loop**
The system runs two concurrent tasks:

#### **SSE Listener** ([src/sse.py](src/sse.py))
- Maintains persistent connection to game server
- Handles connection conflicts (409) when another instance is already connected
- Auto-reconnects on disconnection with exponential backoff
- Parses SSE events and pushes to event queue

#### **Event Dispatcher** ([src/main.py](src/main.py))
- Consumes events from queue
- Routes events to appropriate handlers:
  - `game_started` → Refresh state
  - `game_phase_changed` → Load recipes, trigger agent
  - `client_spawned` → Ask agent to handle new order
  - `preparation_complete` → Ask agent to serve ready dish
  - `message` / `new_message` → Log communications

### 3. **Agent Decision Making**
When triggered, the agent:
1. Receives current game context (state summary + recipes)
2. Gets a specific task prompt (e.g., "A new client arrived...")
3. Uses available MCP tools to:
   - Query game state
   - Update menu
   - Place bids for ingredients
   - Prepare dishes
   - Serve clients
   - Trade on market
4. Executes up to 15 steps with re-planning every 3 steps

### 4. **State Tracking**
The `GameState` object maintains:
- Current phase (`speaking`, `closed_bid`, `waiting`, `serving`, `stopped`)
- Turn ID
- Restaurant balance and inventory
- Active menu
- Pending clients and their orders
- Prepared dishes ready to serve

---

## Components

### [src/main.py](src/main.py)
**Main entry point and event orchestrator**

Key functions:
- `main()` - Initializes agent and launches concurrent tasks
- `dispatch_events()` - Routes SSE events to handlers
- `on_phase_changed()` - Handles game phase transitions
- `on_client_spawned()` - Reacts to new customer arrivals
- `on_preparation_complete()` - Handles dish completion
- `ask_agent()` - Invokes AI agent with game context

### [src/sse.py](src/sse.py)
**Server-Sent Events listener with connection management**

Features:
- File-based lock (`sse.lock`) to prevent local duplicate connections
- Handles HTTP 409 (Conflict) when teammate has active connection
- Auto-reconnect with configurable delays
- Parses SSE `data:` lines into JSON events

### [src/agent.py](src/agent.py)
**AI agent setup using datapizza-ai framework**

Components:
- `SYSTEM_PROMPT` - Comprehensive instructions for the AI
- `build_llm_client()` - Creates Regolo AI client
- `build_mcp_tools()` - Fetches available MCP tools from server
- `build_agent()` - Assembles complete Agent with tools

Agent configuration:
- Model: Regolo AI (gpt-oss-120b)
- Max steps: 15
- Planning interval: 3 (re-evaluates strategy every 3 steps)

### [src/state.py](src/state.py)
**Game state tracker**

Maintains:
- `phase` - Current game phase
- `turn_id` - Current turn number
- `balance` - Restaurant cash balance
- `inventory` - Available ingredients (expires each turn!)
- `menu` - Current restaurant offerings
- `pending_clients` - Clients waiting to be served
- `prepared_dishes` - Dishes ready to serve

Methods:
- `summary()` - One-line state description for agent
- `update_from_restaurant_info()` - Syncs with server data

### [src/api.py](src/api.py)
**REST API client wrappers**

Available endpoints:
- `get_restaurant_info()` - Get restaurant state
- `get_all_restaurants()` - List all restaurants
- `get_recipes()` - Get available recipes
- `get_menu()` - Get current menu
- `get_meals()` - Get meal history for a turn
- `get_bid_history()` - Get bidding history
- `get_market_entries()` - Get active market listings

### [src/config.py](src/config.py)
**Configuration management**

Loads from `.env`:
- `SERVER_URL` - Game server URL
- `API_KEY` - Authentication key
- `RESTAURANT_ID` - Your restaurant ID
- `REGOLO_API_KEY` - AI model API key
- `REGOLO_MODEL` - LLM model name

Derives:
- `HEADERS` - HTTP headers with API key
- `MCP_URL` - MCP tools endpoint
- `SSE_URL` - SSE stream endpoint

### [run.py](run.py)
**Convenience entry point**

Simple wrapper to run `asyncio.run(main())` from project root.

---

## Setup & Installation

### Prerequisites
- Python >= 3.12, < 3.14
- Poetry (Python package manager)

### Installation

1. **Clone the repository**
   ```bash
   cd hackapizzaiug-restaurant
   ```

2. **Install dependencies**
   ```bash
   poetry install
   ```

3. **Configure environment**
   Create a `.env` file in project root:
   ```env
   # Game Server
   SERVER_URL=https://hackapizza.datapizza.tech
   API_KEY=your-api-key-here
   RESTAURANT_ID=your-restaurant-id
   
   # AI Model (Regolo AI)
   REGOLO_API_KEY=your-regolo-api-key
   REGOLO_MODEL=gpt-oss-120b
   ```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SERVER_URL` | No | `https://hackapizza.datapizza.tech` | Game server base URL |
| `API_KEY` | **Yes** | - | Your authentication key |
| `RESTAURANT_ID` | **Yes** | - | Your restaurant identifier |
| `REGOLO_API_KEY` | **Yes** | - | Regolo AI API key |
| `REGOLO_MODEL` | No | `gpt-oss-120b` | LLM model to use |

### Agent Tuning

In [src/agent.py](src/agent.py), adjust:
- `max_steps` (default: 15) - Maximum tool calls per agent invocation
- `planning_interval` (default: 3) - How often agent re-evaluates strategy
- `SYSTEM_PROMPT` - Modify agent's core instructions and strategy

---

## Running the Agent

### Start the agent
```bash
poetry run python run.py
```

Or with Poetry shell:
```bash
poetry shell
python run.py
```

### Expected output
```
2026-02-28 10:00:00 [INFO] hackapizza: ═══ Hackapizza 2.0 — Restaurant Agent ═══
2026-02-28 10:00:00 [INFO] hackapizza: Restaurant ID: your-restaurant-id
2026-02-28 10:00:05 [INFO] src.agent: Fetching MCP tools from https://hackapizza.datapizza.tech/mcp …
2026-02-28 10:00:06 [INFO] src.agent: Loaded 12 MCP tools: ['closed_bid', 'save_menu', ...]
2026-02-28 10:00:06 [INFO] src.agent: Agent built with 12 tools
2026-02-28 10:00:06 [INFO] src.sse: SSE file-lock acquired (pid 12345)
2026-02-28 10:00:07 [INFO] src.sse: SSE connecting → https://hackapizza.datapizza.tech/events/your-restaurant-id
2026-02-28 10:00:08 [INFO] src.sse: SSE handshake OK
2026-02-28 10:00:08 [INFO] src.sse: SSE connected (status 200)
```

### Connection Conflicts
If another team member already has the SSE connection:
```
[WARNING] SSE 409 Conflict — a teammate already has the connection. Retrying in 30s …
```

The agent will retry periodically. Only **one SSE connection per team** is allowed by the server.

---

## Game Phases

The game operates in 5 sequential phases each turn:

### 1. **Speaking Phase**
- Negotiate with other restaurants
- Set/update menu prices
- Create market entries for selling ingredients

**Agent actions:**
- Analyze inventory
- Set competitive menu prices
- List excess ingredients on market

### 2. **Closed Bid Phase**
- Submit **blind bids** for ingredients
- Last submission per turn counts
- Bids are secret until resolution

**Agent actions:**
- Evaluate ingredient needs
- Calculate bid amounts based on recipes and balance
- Submit strategic bids

### 3. **Waiting Phase**
- Finalize menu
- Buy/sell on market
- Analyze inventory before service

**Agent actions:**
- Confirm menu is ready
- Purchase last-minute ingredients
- Sell excess inventory

### 4. **Serving Phase**
- **Clients arrive** with orders
- Prepare dishes (takes time)
- Serve completed dishes

**Agent workflow:**
1. Client spawns → Read order and intolerances
2. Call `prepare_dish` tool
3. Wait for `preparation_complete` event
4. Call `serve_dish` tool

⚠️ **Critical:** Check client intolerances! Serving an intolerant client is catastrophic.

### 5. **Stopped Phase**
- Waiting between turns
- Ingredients expire at turn end
- Reset transient state

**Agent actions:**
- Wait for next turn
- No actions needed

---

## Event Flow

### Event Types

| Event | Trigger | Handler | Agent Task |
|-------|---------|---------|------------|
| `game_started` | New turn begins | Refresh state, increment turn | - |
| `game_phase_changed` | Phase transition | Load recipes, refresh state | "Phase changed to X. Decide actions." |
| `client_spawned` | Customer arrives (serving phase) | Add to pending clients | "New client 'X' with order 'Y'. Serve them." |
| `preparation_complete` | Dish finished cooking | Add to prepared dishes | "Dish 'X' ready. Serve to waiting client." |
| `message` | Broadcast message | Log message | - |
| `new_message` | Direct message | Log message | - |
| `game_reset` | Admin resets game | Clear all state | - |
| `heartbeat` | Keepalive | Ignore | - |

### Event Flow Diagram

```
Game Server SSE Stream
        │
        ├──► game_started
        │      └──► refresh_state()
        │
        ├──► game_phase_changed: "speaking"
        │      ├──► refresh_state()
        │      ├──► load_recipes() (once)
        │      └──► ask_agent("Phase changed to speaking...")
        │             └──► Agent: set_menu, create_market_entries
        │
        ├──► game_phase_changed: "closed_bid"
        │      └──► ask_agent("Phase changed to closed_bid...")
        │             └──► Agent: closed_bid tool
        │
        ├──► game_phase_changed: "waiting"
        │      └──► ask_agent("Phase changed to waiting...")
        │             └──► Agent: save_menu, buy/sell on market
        │
        ├──► game_phase_changed: "serving"
        │      └──► ask_agent("Phase changed to serving...")
        │
        ├──► client_spawned
        │      ├──► Add to state.pending_clients
        │      └──► ask_agent("New client 'X' arrived...")
        │             └──► Agent: prepare_dish
        │
        ├──► preparation_complete
        │      ├──► Add to state.prepared_dishes
        │      └──► ask_agent("Dish 'X' ready...")
        │             └──► Agent: serve_dish
        │
        └──► game_phase_changed: "stopped"
               └──► Clear transient state
```

---

## API Reference

### REST API (`src/api.py`)

All functions are async and require authentication via `HEADERS`.

#### `get_restaurant_info() -> dict`
Get current restaurant state.

**Returns:**
```python
{
  "id": "restaurant-id",
  "name": "Restaurant Name",
  "balance": 1000.0,
  "inventory": [...],
  "menu": [...],
  "turn_id": 5
}
```

#### `get_recipes() -> list[dict]`
Get all available recipes in the game.

**Returns:**
```python
[
  {
    "id": "recipe_123",
    "name": "Cosmic Pizza",
    "ingredients": [{"name": "flour", "quantity": 2}, ...],
    "preparation_time": 30
  },
  ...
]
```

#### `get_menu() -> list[dict]`
Get current restaurant menu.

#### `get_meals(turn_id: int) -> list[dict]`
Get meals served in a specific turn.

#### `get_bid_history(turn_id: int) -> list[dict]`
Get bidding history for a turn.

#### `get_market_entries() -> list[dict]`
Get active market listings.

### MCP Tools

The agent uses MCP tools provided by the game server. Common tools include:

- `closed_bid` - Submit ingredient bid
- `save_menu` - Save menu configuration
- `prepare_dish` - Start cooking a dish
- `serve_dish` - Serve prepared dish to client
- `update_restaurant_is_open` - Open/close restaurant
- `create_market_entry` - List ingredients for sale
- `buy_from_market` - Purchase from market
- Various query tools for game state

Tools are dynamically loaded from `{SERVER_URL}/mcp` endpoint.

---

## Troubleshooting

### Agent not responding
- Check if MCP tools loaded successfully in logs
- Verify `REGOLO_API_KEY` is valid
- Check network connectivity to Regolo AI

### SSE connection issues
- **409 Conflict**: Another team member has the connection. Only one SSE per team allowed.
- **Connection drops**: Auto-reconnect will trigger. Check network stability.
- **File lock error**: Remove `sse.lock` file if process crashed without cleanup.

### Ingredients expiring
- Remember: **all inventory expires at turn end**
- Only buy what you can use in current turn
- Agent should account for this in bidding/purchasing decisions

### Client not served
- Check agent logs for errors
- Verify dish was prepared before attempting to serve
- Ensure intolerance checks passed

---

## Development

### Project Structure
```
hackapizzaiug-restaurant/
├── pyproject.toml          # Poetry dependencies
├── README.md               # This file
├── run.py                  # Entry point
├── .env                    # Configuration (not in git)
├── docs/
│   └── istruzioni.md       # Competition instructions (Italian)
└── src/
    ├── __init__.py
    ├── main.py             # Event loop & orchestration
    ├── agent.py            # AI agent setup
    ├── api.py              # REST API client
    ├── config.py           # Configuration loader
    ├── sse.py              # SSE listener
    └── state.py            # Game state tracker
```

### Adding Custom Logic

To add custom decision logic:

1. **Modify agent behavior**: Edit `SYSTEM_PROMPT` in [src/agent.py](src/agent.py)
2. **Add event handlers**: Add cases in `dispatch_events()` in [src/main.py](src/main.py)
3. **Extend state tracking**: Add fields to `GameState` in [src/state.py](src/state.py)
4. **Add API helpers**: Add wrappers in [src/api.py](src/api.py)

### Logging

Adjust log level in [src/main.py](src/main.py):
```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for verbose output
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

---

## Key Insights

### Strategy Tips
1. **Ingredient Management**: Never buy more than you can use – ingredients expire!
2. **Client Intolerances**: Always verify before serving. One mistake can tank your balance.
3. **Bidding**: Blind bids are risky. Balance aggression with budget conservation.
4. **Menu Pricing**: Monitor competitors, adjust prices dynamically.
5. **Market Timing**: Sell excess early (speaking phase), buy last-minute needs (waiting phase).

### Agent Tuning
- **Conservative**: Lower `max_steps`, shorter `SYSTEM_PROMPT`
- **Aggressive**: Higher `max_steps`, more detailed planning instructions
- **Defensive**: Add explicit checks for intolerances and balance limits

---

## License

See competition rules and terms.

## Credits

Built for Hackapizza 2.0 competition using:
- [datapizza-ai](https://pypi.org/project/datapizza-ai/) - Agent framework
- [Regolo AI](https://regolo.ai) - LLM provider
- [aiohttp](https://docs.aiohttp.org/) - Async HTTP client