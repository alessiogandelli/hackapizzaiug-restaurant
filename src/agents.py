"""Agent factory — builds all 5 agents with role-restricted tool subsets.

Simplified architecture:
    StrategicPlanner  (20b, no tools)   — outputs conservative JSON strategy
    SpeakingAgent     (20b, save_menu)  — sets fixed menu
    BiddingAgent      (20b, closed_bid) — submits pre-computed bids
    MarketAgent       (20b, market ops) — defensive trades
    ServingAgent      (120b, serving)   — critical: intolerance checking
"""
from __future__ import annotations

import logging

from datapizza.agents import Agent
from datapizza.clients.openai_like import OpenAILikeClient
from datapizza.tools.mcp_client import MCPClient

from src.config import (
    REGOLO_API_KEY,
    REGOLO_BASE_URL,
    MCP_URL,
    HEADERS,
)
from src.prompts import (
    PLANNER_PROMPT,
    BIDDING_PROMPT,
    MARKET_PROMPT,
    SERVING_PROMPT,
    OPENER_PROMPT,
)

logger = logging.getLogger(__name__)

# ── Model config ─────────────────────────────────────────────
FAST_MODEL = "gpt-oss-120b"         # cheap for simple tasks
SMART_MODEL = "gpt-oss-120b"       # smart for serving (intolerance checking)

# ── Tool name sets per agent ─────────────────────────────────
SPEAKING_TOOLS = {"send_message", "save_menu", "update_restaurant_is_open"}
BIDDING_TOOLS = {"closed_bid"}
MARKET_TOOLS = {"create_market_entry", "execute_transaction", "delete_market_entry"}
SERVING_TOOLS = {"prepare_dish", "serve_dish", "get_meals", "update_restaurant_is_open"}
OPENER_TOOLS = {"update_restaurant_is_open"}
MENU_TOOLS = {"save_menu", "update_restaurant_is_open"}

# Tools all executor agents can read (info only)
INFO_TOOLS = {"restaurant_info", "get_meals"}


def _build_client(model: str) -> OpenAILikeClient:
    """Create an LLM client for a specific model."""
    return OpenAILikeClient(
        api_key=REGOLO_API_KEY,
        model=model,
        base_url=REGOLO_BASE_URL,
    )


def _load_mcp_tools() -> list:
    """Fetch all MCP tools from the game server."""
    logger.info("Fetching MCP tools from %s …", MCP_URL)
    mcp = MCPClient(url=MCP_URL, headers=HEADERS)
    tools = mcp.list_tools()
    logger.info("Loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools


def _filter_tools(all_tools: list, allowed_names: set) -> list:
    """Filter tools to only those in the allowed set."""
    filtered = [t for t in all_tools if t.name in allowed_names]
    logger.debug("Filtered tools: %s", [t.name for t in filtered])
    return filtered


def build_agents() -> dict[str, Agent]:
    """Build and return all 5 agents with role-restricted tool access."""
    # Load tools once, share filtered subsets
    all_tools = _load_mcp_tools()

    fast_client = _build_client(FAST_MODEL)
    smart_client = _build_client(SMART_MODEL)

    # ── StrategicPlanner (NO tools, fast model) ──────────────
    planner = Agent(
        name="StrategicPlanner",
        client=fast_client,
        system_prompt=PLANNER_PROMPT,
        tools=[],
        max_steps=2,
        planning_interval=0,
    )

    opener_tools = _filter_tools(all_tools, OPENER_TOOLS | INFO_TOOLS)
    opener = Agent( name="Opener", 
                   client=fast_client, 
                   system_prompt=OPENER_PROMPT, 
                   tools=opener_tools, 
                   max_steps=1)

    # ── SpeakingAgent (sets dynamic menu) ─────────────────────
    speaking_tools = _filter_tools(all_tools, SPEAKING_TOOLS | INFO_TOOLS)
    # Start with empty menu prompt — will be updated by orchestrator at runtime
    speaking = Agent(
        name="SpeakingAgent",
        client=fast_client,
        system_prompt='parla',
        tools=speaking_tools,
        max_steps=3,
        planning_interval=0,
    )

    # ── BiddingAgent (just submits bids) ─────────────────────
    bidding_tools = _filter_tools(all_tools, BIDDING_TOOLS | INFO_TOOLS)
    bidding = Agent(
        name="BiddingAgent",
        client=fast_client,
        system_prompt=BIDDING_PROMPT,
        tools=bidding_tools,
        max_steps=3,
        planning_interval=0,
    )

    # ── Menu Agent (create menu) ───────────────────────
    menu_tools = _filter_tools(all_tools, MENU_TOOLS)
    menu = Agent(
        name="MenuAgent",
        client=fast_client,
        system_prompt="You are the Menu Agent. Your job is to set the restaurant menu using save_menu tool. Use the provided menu items in the context to build the menu. Do NOT modify names or prices. Do NOT add other dishes. Just call save_menu with the provided items. if there are no feasable menu close the restaurant",
        tools=menu_tools,
        max_steps=3,
        planning_interval=0,
    )

    # ── MarketAgent (defensive trades) ───────────────────────
    market_tools = _filter_tools(all_tools, MARKET_TOOLS | INFO_TOOLS)
    market = Agent(
        name="MarketAgent",
        client=fast_client,
        system_prompt=MARKET_PROMPT,
        tools=market_tools,
        max_steps=5,
        planning_interval=0,
    )

    # ── ServingAgent (SMART model — critical for safety) ─────
    serving_tools = _filter_tools(all_tools, SERVING_TOOLS | INFO_TOOLS)
    # Start with empty recipe prompt — will be updated by orchestrator at runtime
    serving = Agent(
        name="ServingAgent",
        client=smart_client,
        system_prompt=SERVING_PROMPT,
        tools=serving_tools,
        max_steps=15,
        planning_interval=0,
    )

    agents = {
        "planner": planner,
        "speaking": speaking,
        "bidding": bidding,
        "market": market,
        "serving": serving,
        "opener": opener,
        "menu": menu,
    }

    for name, ag in agents.items():
        model = SMART_MODEL if name == "serving" else FAST_MODEL
        tool_names = [t.name for t in ag._tools] if ag._tools else []
        logger.info("Built agent [%s] — model=%s, tools=%s", name, model, tool_names)

    return agents
