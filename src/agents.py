"""Agent factory — builds all 5 agents with role-restricted tool subsets.

Architecture:
    StrategicPlanner  (120b, no tools)  — brain
    SpeakingAgent     (20b, messaging)  — psychology
    BiddingAgent      (20b, closed_bid) — math
    MarketAgent       (20b, market ops) — arbitrage
    ServingAgent      (20b, serving)    — risk-control
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
    SPEAKING_PROMPT,
    BIDDING_PROMPT,
    MARKET_PROMPT,
    SERVING_PROMPT,
)

logger = logging.getLogger(__name__)

# ── Model config ─────────────────────────────────────────────
PLANNER_MODEL = "gpt-oss-120b"     # big brain for strategic planning
EXECUTOR_MODEL = "gpt-oss-120b"     # fast + cheap for execution

# ── Tool name sets per agent ─────────────────────────────────
SPEAKING_TOOLS = {"send_message", "save_menu"}
BIDDING_TOOLS = {"closed_bid"}
MARKET_TOOLS = {"create_market_entry", "execute_transaction", "delete_market_entry"}
SERVING_TOOLS = {"prepare_dish", "serve_dish", "update_restaurant_is_open"}

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
    """Build and return all 5 agents with role-restricted tool access.

    Returns:
        Dict with keys: planner, speaking, bidding, market, serving
    """
    # Load tools once, share filtered subsets
    all_tools = _load_mcp_tools()

    # Create separate LLM clients for planner vs executors
    planner_client = _build_client(PLANNER_MODEL)
    executor_client = _build_client(EXECUTOR_MODEL)

    # ── StrategicPlanner (NO tools, big model) ───────────────
    planner = Agent(
        name="StrategicPlanner",
        client=planner_client,
        system_prompt=PLANNER_PROMPT,
        tools=[],                   # no tools — pure reasoning
        max_steps=3,
        planning_interval=0,        # no re-planning needed
    )

    # ── SpeakingAgent ────────────────────────────────────────
    speaking_tools = _filter_tools(all_tools, SPEAKING_TOOLS | INFO_TOOLS)
    speaking = Agent(
        name="SpeakingAgent",
        client=executor_client,
        system_prompt=SPEAKING_PROMPT,
        tools=speaking_tools,
        max_steps=5,
        planning_interval=0,
    )

    # ── BiddingAgent ─────────────────────────────────────────
    bidding_tools = _filter_tools(all_tools, BIDDING_TOOLS | INFO_TOOLS)
    bidding = Agent(
        name="BiddingAgent",
        client=executor_client,
        system_prompt=BIDDING_PROMPT,
        tools=bidding_tools,
        max_steps=5,
        planning_interval=0,
    )

    # ── MarketAgent ──────────────────────────────────────────
    market_tools = _filter_tools(all_tools, MARKET_TOOLS | INFO_TOOLS)
    market = Agent(
        name="MarketAgent",
        client=executor_client,
        system_prompt=MARKET_PROMPT,
        tools=market_tools,
        max_steps=8,
        planning_interval=0,
    )

    # ── ServingAgent ─────────────────────────────────────────
    serving_tools = _filter_tools(all_tools, SERVING_TOOLS | INFO_TOOLS)
    serving = Agent(
        name="ServingAgent",
        client=executor_client,
        system_prompt=SERVING_PROMPT,
        tools=serving_tools,
        max_steps=10,               # needs more steps for multiple clients
        planning_interval=0,
    )

    agents = {
        "planner": planner,
        "speaking": speaking,
        "bidding": bidding,
        "market": market,
        "serving": serving,
    }

    for name, ag in agents.items():
        tool_names = [t.name for t in ag._tools] if ag._tools else []
        logger.info("Built %s — model=%s, tools=%s",
                     name, PLANNER_MODEL if name == "planner" else EXECUTOR_MODEL, tool_names)

    return agents
