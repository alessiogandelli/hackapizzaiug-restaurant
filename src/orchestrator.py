"""PhaseController — deterministic orchestrator that routes phases to specialist agents.

The LLM never guesses phase logic. This module owns the routing.

Flow per turn:
    speaking  → Planner (once) → SpeakingAgent
    closed_bid→ BiddingAgent
    waiting   → MarketAgent
    serving   → ServingAgent (per client event)
    stopped   → Record results, reset turn data
"""
from __future__ import annotations

import json
import logging

from datapizza.agents import Agent

from src.state import GameState
from src.memory import GameMemory
from src.recipes import (
    filter_feasible_recipes,
    compute_ingredient_demand,
    compute_bid_targets,
    get_recipe_summary,
)
from src.api import (
    get_restaurant_info,
    get_all_restaurants,
    get_recipes,
    get_market_entries,
    get_bid_history,
    get_meals,
)

logger = logging.getLogger(__name__)


class PhaseController:
    """Deterministic phase router — no LLM decides which agent runs when."""

    def __init__(
        self,
        agents: dict[str, Agent],
        state: GameState,
        memory: GameMemory,
        tracer=None,
    ):
        self.agents = agents
        self.state = state
        self.memory = memory
        self.tracer = tracer
        self._planner_ran_this_turn = False

    # ── Main phase dispatcher ────────────────────────────────
    async def handle_phase(self, phase: str) -> None:
        """Route to the correct handler based on phase."""
        if not phase or not isinstance(phase, str):
            logger.warning("Invalid phase value: %r", phase)
            return

        self.state.phase = phase
        logger.info("PhaseController handling: %s", phase)

        if phase == "stopped":
            await self._handle_stopped()
            return

        # Refresh state at every phase transition
        await self._refresh_state()

        # Log state after refresh for debugging
        logger.info("  state after refresh — balance=%.1f, inv type=%s len=%s, menu type=%s len=%s, recipes type=%s len=%s",
                     self.state.balance,
                     type(self.state.inventory).__name__, len(self.state.inventory) if isinstance(self.state.inventory, list) else '?',
                     type(self.state.menu).__name__, len(self.state.menu) if isinstance(self.state.menu, list) else '?',
                     type(self.state.recipes).__name__, len(self.state.recipes) if isinstance(self.state.recipes, list) else '?')

        # Load recipes once (immutable across game)
        if not self.state.recipes:
            await self._load_recipes()

        try:
            if phase == "speaking":
                await self._handle_speaking()
            elif phase == "closed_bid":
                await self._handle_bidding()
            elif phase == "waiting":
                await self._handle_waiting()
            elif phase == "serving":
                await self._handle_serving_phase()
            else:
                logger.warning("Unknown phase: %s", phase)
        except Exception as exc:
            logger.exception(
                "Error in %s handler: %s\n"
                "  → state.phase=%s, turn_id=%s\n"
                "  → inventory type=%s, sample=%r\n"
                "  → menu type=%s, sample=%r\n"
                "  → recipes type=%s, count=%s\n"
                "  → balance=%s, is_open=%s",
                phase, exc,
                self.state.phase, self.state.turn_id,
                type(self.state.inventory).__name__, str(self.state.inventory[:3])[:200] if isinstance(self.state.inventory, list) else str(self.state.inventory)[:200],
                type(self.state.menu).__name__, str(self.state.menu[:3])[:200] if isinstance(self.state.menu, list) else str(self.state.menu)[:200],
                type(self.state.recipes).__name__, len(self.state.recipes) if isinstance(self.state.recipes, list) else f'NOT A LIST: {str(self.state.recipes)[:200]}',
                self.state.balance, self.state.is_open,
            )

    # ── Client events (called from main.py directly) ────────
    async def handle_client(self, client_data: dict) -> None:
        """Handle a client_spawned event during serving phase."""
        logger.info("handle_client called — data type=%s, data=%r",
                     type(client_data).__name__, str(client_data)[:500])

        if not isinstance(client_data, dict):
            logger.error("handle_client: client_data is NOT a dict! type=%s, value=%r",
                         type(client_data).__name__, str(client_data)[:500])
            return

        self.memory.record_client(client_data)
        client_name = client_data.get("clientName", "unknown")
        order = client_data.get("orderText", "")
        intolerances = client_data.get("intolerances", [])

        logger.info("Serving client %s — order: %s, intolerances: %s",
                     client_name, order, intolerances)

        recipes_type = type(self.state.recipes).__name__
        recipes_len = len(self.state.recipes) if isinstance(self.state.recipes, list) else '?'
        logger.debug("  recipes type=%s len=%s, feasible=%d",
                     recipes_type, recipes_len, len(self.memory.feasible_recipes))

        context = (
            f"SERVING CONTEXT:\n{self.memory.get_serving_context(self.state.summary(), client_data)}\n\n"
            f"RECIPES:\n{get_recipe_summary(self.state.recipes, 20)}\n\n"
            f"TASK: Client '{client_name}' arrived with order: \"{order}\".\n"
            f"Client intolerances: {json.dumps(intolerances)}\n"
            f"Decide which dish to prepare (prepare_dish). Check intolerances carefully!"
        )

        await self._run_agent("serving", context, span_name="serve_client")

    async def handle_preparation_complete(self, data: dict) -> None:
        """Handle a preparation_complete event — serve the ready dish."""
        logger.info("handle_preparation_complete called — data type=%s, data=%r",
                     type(data).__name__, str(data)[:500])

        if not isinstance(data, dict):
            logger.error("handle_preparation_complete: data is NOT a dict! type=%s, value=%r",
                         type(data).__name__, str(data)[:500])
            return

        dish = data.get("dish", "")
        self.memory.record_dish_prepared(dish)

        # Find the client waiting for this dish
        context = (
            f"SERVING CONTEXT:\n{self.memory.get_serving_context(self.state.summary())}\n\n"
            f"TASK: Dish '{dish}' is ready. Serve it to the appropriate waiting client.\n"
            f"Pending clients: {json.dumps(self.memory.pending_clients, default=str)}\n"
            f"Use serve_dish with the correct client_id."
        )

        await self._run_agent("serving", context, span_name="serve_prepared_dish")

    # ── Phase handlers ───────────────────────────────────────
    async def _handle_speaking(self) -> None:
        """Speaking phase: Plan strategy (once per turn) → set menu → send messages."""
        # Update recipe feasibility
        market_entries = await self._safe_call(get_market_entries, [])
        logger.debug("  speaking — market_entries type=%s, len=%s",
                     type(market_entries).__name__,
                     len(market_entries) if isinstance(market_entries, list) else '?')

        # Validate data before filter
        if not isinstance(self.state.recipes, list):
            logger.error("  ⚠️  state.recipes is %s, not list! value=%r",
                         type(self.state.recipes).__name__, str(self.state.recipes)[:200])
        if not isinstance(self.state.inventory, list):
            logger.error("  ⚠️  state.inventory is %s, not list! value=%r",
                         type(self.state.inventory).__name__, str(self.state.inventory)[:200])

        self.memory.feasible_recipes = filter_feasible_recipes(
            self.state.recipes, self.state.inventory, market_entries,
        )

        # Run planner ONCE per turn at start of speaking phase
        if not self._planner_ran_this_turn:
            await self._run_planner()
            self._planner_ran_this_turn = True
            self.memory.start_turn(self.state.balance)

        # Update competitor profiles
        await self._update_competitors()

        # Run SpeakingAgent
        context = (
            f"SPEAKING CONTEXT:\n{self.memory.get_speaking_context(self.state.summary())}\n\n"
            f"FEASIBLE RECIPES:\n{get_recipe_summary(self.memory.feasible_recipes, 15)}\n\n"
            f"PLANNER DIRECTIVES:\n"
            f"- Speaking strategy: {self.memory.current_strategy.get('speaking_strategy', 'bluff_premium')}\n"
            f"- Segment: {self.memory.current_strategy.get('segment', 'balanced')}\n"
            f"- Target margin: {self.memory.current_strategy.get('target_margin', 0.4)}\n"
            f"- Menu suggestions: {json.dumps(self.memory.current_strategy.get('menu_suggestions', []))}\n\n"
            f"COMPETITOR INFO:\n{json.dumps(dict(list(self.memory.competitor_profiles.items())[:5]), default=str)}\n\n"
            f"TASK: Execute speaking phase. Set the menu and send strategic messages based on directives."
        )

        await self._run_agent("speaking", context, span_name="phase_speaking")

    async def _handle_bidding(self) -> None:
        """Closed bid phase: compute demand → bid."""
        # Recompute ingredient demand based on current menu
        self.memory.ingredient_demand = compute_ingredient_demand(
            self.memory.feasible_recipes, self.state.menu,
        )
        bid_targets = compute_bid_targets(
            self.memory.ingredient_demand, self.state.inventory,
        )

        context = (
            f"BIDDING CONTEXT:\n{self.memory.get_bidding_context(self.state.summary(), self.state.inventory)}\n\n"
            f"BID TARGETS (ingredients you need):\n{json.dumps(bid_targets, default=str)}\n\n"
            f"PLANNER DIRECTIVES:\n"
            f"- Bid aggression: {self.memory.current_strategy.get('bid_aggression', 0.5)}\n"
            f"- Inventory risk limit: {self.memory.current_strategy.get('inventory_risk_limit', 500)}\n"
            f"- Current balance: {self.state.balance}\n\n"
            f"TASK: Submit your closed_bid for the ingredients you need. "
            f"Bid prices should reflect aggression level. Stay within risk limit."
        )

        await self._run_agent("bidding", context, span_name="phase_closed_bid")

    async def _handle_waiting(self) -> None:
        """Waiting phase: check bid outcomes → trade on market."""
        # Refresh state to see bid results
        await self._refresh_state()

        # Record bid outcomes
        try:
            bid_history = await get_bid_history(self.state.turn_id)
            logger.debug("  bid_history type=%s, len=%s, sample=%r",
                         type(bid_history).__name__,
                         len(bid_history) if isinstance(bid_history, list) else '?',
                         str(bid_history[:2])[:300] if isinstance(bid_history, list) else str(bid_history)[:300])

            # Validate data shapes before passing
            demand = self.memory.ingredient_demand
            logger.debug("  ingredient_demand type=%s, value=%r",
                         type(demand).__name__, str(demand)[:300])

            self.memory.record_bid_result(
                self.state.turn_id,
                self.memory.ingredient_demand,
                bid_history,
            )
        except Exception as exc:
            logger.warning("Could not fetch/record bid history: %s\n"
                           "  → turn_id=%s, ingredient_demand type=%s",
                           exc, self.state.turn_id,
                           type(self.memory.ingredient_demand).__name__)

        # Recompute demand with updated inventory
        self.memory.ingredient_demand = compute_ingredient_demand(
            self.memory.feasible_recipes if self.memory.feasible_recipes else self.state.recipes,
            self.state.menu,
        )

        # Get market entries
        market_entries = await self._safe_call(get_market_entries, [])

        # Update feasible recipes with new inventory
        self.memory.feasible_recipes = filter_feasible_recipes(
            self.state.recipes, self.state.inventory, market_entries,
        )

        context = (
            f"MARKET CONTEXT:\n{self.memory.get_market_context(self.state.summary(), self.state.inventory, market_entries)}\n\n"
            f"INGREDIENT SHORTAGES:\n{json.dumps(compute_bid_targets(self.memory.ingredient_demand, self.state.inventory), default=str)}\n\n"
            f"PLANNER DIRECTIVES:\n"
            f"- Market strategy: {self.memory.current_strategy.get('market_strategy', 'defensive')}\n"
            f"- Current balance: {self.state.balance}\n\n"
            f"TASK: Handle market trades. Buy missing ingredients if available. "
            f"Sell surplus if strategy allows. Follow market_strategy directive."
        )

        await self._run_agent("market", context, span_name="phase_waiting")

    async def _handle_serving_phase(self) -> None:
        """Serving phase start — open restaurant and wait for client events."""
        logger.debug("  serving_phase — recipes type=%s len=%s, inventory type=%s len=%s",
                     type(self.state.recipes).__name__,
                     len(self.state.recipes) if isinstance(self.state.recipes, list) else '?',
                     type(self.state.inventory).__name__,
                     len(self.state.inventory) if isinstance(self.state.inventory, list) else '?')

        # Validate recipes before passing to get_recipe_summary
        if not isinstance(self.state.recipes, list):
            logger.error("  ⚠️  Cannot serve — state.recipes is %s! value=%r",
                         type(self.state.recipes).__name__, str(self.state.recipes)[:300])
            return

        # Ensure restaurant is open
        context = (
            f"SERVING CONTEXT:\n{self.memory.get_serving_context(self.state.summary())}\n\n"
            f"RECIPES:\n{get_recipe_summary(self.state.recipes, 20)}\n\n"
            f"TASK: The serving phase has started. Ensure the restaurant is open. "
            f"Clients will arrive via separate events — you will be called for each one."
        )

        await self._run_agent("serving", context, span_name="phase_serving_start")

    async def _handle_stopped(self) -> None:
        """Turn ended — record results, clear turn data."""
        # Refresh final state for accurate balance
        await self._refresh_state()

        # Record turn result
        self.memory.record_turn_result(
            turn=self.state.turn_id,
            balance_before=self.memory.turn_balance_start,
            balance_after=self.state.balance,
            clients_served=self.memory.clients_served_this_turn,
        )

        # Reset for next turn
        self.memory.reset_turn()
        self._planner_ran_this_turn = False

        logger.info("Turn %d ended — balance: %.1f", self.state.turn_id, self.state.balance)

    # ── Planner ──────────────────────────────────────────────
    async def _run_planner(self) -> None:
        """Run the StrategicPlanner to set turn-level strategy."""
        # Gather context for planner
        all_restaurants = await self._safe_call(get_all_restaurants, [])
        bid_history = []
        if self.state.turn_id > 1:
            bid_history = await self._safe_call(
                lambda: get_bid_history(self.state.turn_id - 1), []
            )

        context = (
            f"FULL GAME ANALYSIS:\n{self.memory.get_planner_context(self.state.summary(), all_restaurants, bid_history)}\n\n"
            f"FEASIBLE RECIPES ({len(self.memory.feasible_recipes)}):\n"
            f"{get_recipe_summary(self.memory.feasible_recipes, 20)}\n\n"
            f"TURN {self.state.turn_id} — Analyse the situation and output your strategy as JSON."
        )

        logger.info("Running StrategicPlanner for turn %d …", self.state.turn_id)

        try:
            result = await self._run_agent_raw("planner", context, span_name="planner_run")
            if result and result.text:
                strategy = self._parse_planner_output(result.text)
                self.memory.update_strategy(strategy)
                logger.info("Planner strategy: %s", self.memory.current_strategy)
            else:
                logger.warning("Planner returned no output — using default strategy")
        except Exception as exc:
            logger.exception("Planner error: %s — using default strategy", exc)

    def _parse_planner_output(self, text: str) -> dict:
        """Extract JSON from planner output, handling markdown code blocks."""
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse planner JSON: %s", text[:200])
            return {}

    # ── Agent execution helpers ──────────────────────────────
    async def _run_agent(self, agent_name: str, context: str, span_name: str = "") -> None:
        """Run a named agent with context. Logs and traces the call."""
        agent = self.agents.get(agent_name)
        if agent is None:
            logger.error("Agent '%s' not found!", agent_name)
            return

        try:
            logger.info("▶ %s ← %s", agent_name, context[:100])

            if self.tracer and span_name:
                with self.tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("agent.name", agent_name)
                    span.set_attribute("agent.prompt_preview", context[:200])
                    result = await agent.a_run(context)
                    if result and result.text:
                        span.set_attribute("agent.response_preview", result.text[:200])
            else:
                result = await agent.a_run(context)

            response_preview = result.text[:200] if result and result.text else "(no text)"
            logger.info("◀ %s → %s", agent_name, response_preview)

        except Exception as exc:
            logger.exception("Agent %s error: %s", agent_name, exc)

    async def _run_agent_raw(self, agent_name: str, context: str, span_name: str = ""):
        """Run a named agent and return the raw StepResult."""
        agent = self.agents.get(agent_name)
        if agent is None:
            logger.error("Agent '%s' not found!", agent_name)
            return None

        try:
            logger.info("▶ %s ← %s", agent_name, context[:100])

            if self.tracer and span_name:
                with self.tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("agent.name", agent_name)
                    result = await agent.a_run(context)
                    if result and result.text:
                        span.set_attribute("agent.response_preview", result.text[:200])
            else:
                result = await agent.a_run(context)

            response_preview = result.text[:200] if result and result.text else "(no text)"
            logger.info("◀ %s → %s", agent_name, response_preview)
            return result

        except Exception as exc:
            logger.exception("Agent %s error: %s", agent_name, exc)
            return None

    # ── Helpers ──────────────────────────────────────────────
    async def _refresh_state(self) -> None:
        """Pull fresh restaurant info from REST API."""
        try:
            info = await get_restaurant_info()
            logger.debug("  _refresh_state got info type=%s, keys=%s, sample=%r",
                         type(info).__name__,
                         list(info.keys())[:15] if isinstance(info, dict) else 'N/A',
                         {k: type(v).__name__ for k, v in info.items()} if isinstance(info, dict) else str(info)[:300])

            # Validate critical fields before updating
            if isinstance(info, dict):
                self.state.update_from_restaurant_info(info)
            else:
                logger.error("  ⚠️  get_restaurant_info returned %s instead of dict! value=%r",
                             type(info).__name__, str(info)[:300])
        except Exception as exc:
            logger.warning("Could not refresh state: %s", exc)

    async def _load_recipes(self) -> None:
        """Load recipes once (immutable across game)."""
        try:
            self.state.recipes = await get_recipes()
            logger.info("Loaded %d recipes", len(self.state.recipes))
        except Exception as exc:
            logger.warning("Could not load recipes: %s", exc)

    async def _update_competitors(self) -> None:
        """Update competitor profiles from public data."""
        try:
            all_restaurants = await get_all_restaurants()
            for r in all_restaurants:
                rid = str(r.get("id", r.get("restaurant_id", "")))
                if rid and rid != str(self.state.restaurant_info.get("id", "")):
                    self.memory.update_competitor(rid, {
                        "name": r.get("name", ""),
                        "balance": r.get("balance", 0),
                        "menu": r.get("menu", []),
                        "is_open": r.get("is_open", True),
                        "reputation": r.get("reputation", 0),
                    })
        except Exception as exc:
            logger.warning("Could not update competitors: %s", exc)

    @staticmethod
    async def _safe_call(coro_or_func, default=None):
        """Call an async function safely, returning default on error."""
        try:
            if callable(coro_or_func):
                result = coro_or_func()
                if hasattr(result, "__await__"):
                    return await result
                return result
            return await coro_or_func
        except Exception as exc:
            logger.warning("Safe call failed: %s", exc)
            return default
