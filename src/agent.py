"""Agent setup — builds the datapizza-ai Agent wired to the game-server MCP tools."""
from __future__ import annotations
import logging

from datapizza.agents import Agent
from datapizza.clients.openai_like import OpenAILikeClient
from datapizza.tools.mcp_client import MCPClient

from src.config import (
    REGOLO_API_KEY,
    REGOLO_MODEL,
    REGOLO_BASE_URL,
    MCP_URL,
    HEADERS,
)

logger = logging.getLogger(__name__)

# ── System prompt ────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are the autonomous manager of a galactic restaurant in the Hackapizza 2.0 competition (Cosmic Cycle 790).

## Your goal
Maximise the restaurant's balance by making smart decisions every phase.

## Turn phases (in order)
1. **speaking** — negotiate with other restaurants, set/update the menu, create market entries.
2. **closed_bid** — submit blind bids for ingredients (`closed_bid` tool). Last submission wins.
3. **waiting** — finalise the menu (`save_menu`), analyse inventory, buy/sell on market.
4. **serving** — clients arrive. For each client:
   a. Read their order and check for intolerances.
   b. `prepare_dish` (takes preparation time).
   c. After `preparation_complete` event → `serve_dish` to the client.
5. **stopped** — do nothing, wait for the next turn.

## Key rules
- Ingredients **expire at end of turn** — only buy what you'll cook.
- Serving an intolerant client is catastrophic — always check before serving.
- You can close the restaurant (`update_restaurant_is_open` false) if overwhelmed.
- Market entries expire at end of turn.
- `closed_bid`: last call per turn counts. Bids are blind — spend wisely.

## Available information
You'll receive a JSON state summary each time you're asked to act.
Use the MCP tools to interact with the game server.
Think step-by-step, pick the right tool for the current phase, and explain your reasoning briefly.
"""


def build_llm_client() -> OpenAILikeClient:
    return OpenAILikeClient(
        api_key=REGOLO_API_KEY,
        model=REGOLO_MODEL,
        base_url=REGOLO_BASE_URL,
    )


def build_mcp_tools() -> list:
    """Fetch available MCP tools from the game server."""
    logger.info("Fetching MCP tools from %s …", MCP_URL)
    mcp = MCPClient(url=MCP_URL, headers=HEADERS)
    tools = mcp.list_tools()
    logger.info("Loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools


def build_agent() -> Agent:
    """Create and return the datapizza-ai Agent ready to play."""
    client = build_llm_client()
    mcp_tools = build_mcp_tools()

    agent = Agent(
        name="Galactic_Chef",
        client=client,
        system_prompt=SYSTEM_PROMPT,
        tools=mcp_tools,
        max_steps=15,
        planning_interval=3,       # re-plan every 3 steps
    )
    logger.info("Agent built with %d tools", len(mcp_tools))
    return agent
