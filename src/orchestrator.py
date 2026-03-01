"""PhaseController — dynamic orchestrator for the undercutting strategy.

Flow per turn:
    speaking  → Planner (once) → Bid ALL ingredients at 3 credits
              → After bids resolve, check inventory vs /recipes
              → Build menu from feasible recipes → SpeakingAgent sets it
    closed_bid→ BiddingAgent (bids 3 credits × 3 units on ALL ingredients)
    waiting   → Refresh inventory → Rebuild feasible menu → Update menu
    serving   → ServingAgent (dynamic: serves from feasible recipes)
    stopped   → Record results, save state, reset turn data
"""
from __future__ import annotations

import json
import logging

from datapizza.agents import Agent
from src.data.ingredienti import ingredienti
from src.state import GameState
from src.memory import GameMemory
from src.constants import (
    MENU_ITEMS,
    OUR_RECIPE_NAMES,
    RECIPE_INGREDIENTS,
    DEFAULT_BIDS,
    MAX_BID_SPEND,
    MAX_TURN_SPEND,
    ALL_INGREDIENTS,
    MAX_MARKET_PRICE,
    BID_PRICE_PER_UNIT,
    BID_QUANTITY_PER_INGREDIENT,
)
from src.recipes import (
    find_feasible_recipes,
    build_menu_from_feasible,
    build_recipe_ingredients_map,
    compute_missing_ingredients,
    get_inventory_stock,
    get_recipe_summary,
)

from src.api import (
    get_restaurant_info,
    get_all_restaurants,
    get_recipes,
    get_market_entries,
    get_bid_history,
    get_meals
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
        
        # Dynamic menu state — rebuilt each turn based on inventory + recipes
        self._feasible_recipes: list[dict] = []
        self._current_menu: list[dict] = []
        self._current_recipe_ingredients: dict[str, list[str]] = {}

    # ── Main phase dispatcher ────────────────────────────────
    async def handle_phase(self, phase: str) -> None:
        if not phase or not isinstance(phase, str):
            logger.warning("Invalid phase value: %r", phase)
            return

        self.state.phase = phase
        logger.info("=" * 60)
        logger.info("PHASE HANDLER: %s", phase.upper())
        logger.info("=" * 60)

        if phase == "stopped":
            await self._handle_stopped()
            return

        # Refresh state at every phase transition
        await self._refresh_state()
        self._log_state()

        # Load recipes once
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
            logger.exception("Error in %s handler: %s", phase, exc)

        # Save state after every phase
        self.state.save_to_file()
        self.memory.save_to_file(self.state.turn_id)

    # ── Client events (called from main.py) ──────────────────
    async def handle_client(self, client_data: dict) -> None:
        if not isinstance(client_data, dict):
            logger.error("handle_client: not a dict! type=%s", type(client_data).__name__)
            return

        self.memory.record_client(client_data)
        client_name = client_data.get("clientName", "unknown")
        order = client_data.get("orderText", "")
        intolerances = client_data.get("intolerances", [])

        logger.info("─── CLIENT ARRIVED ───")
        logger.info("  Name:         %s", client_name)
        logger.info("  Order:        %s", order)
        logger.info("  Intolerances: %s", intolerances)
        logger.info("  Inventory:    %d items", len(self.state.inventory))
        logger.info("  Prepared:     %s", self.memory.prepared_dishes)
        logger.info("  Available dishes: %d", len(self._current_recipe_ingredients))

        # Fetch client ID from meals API
        client_id = await self._get_client_id(client_name)
        if not client_id:
            logger.error("Could not find client ID for %s", client_name)
            return
        
        logger.info("  Client ID:    %s", client_id)

        # Call serving agent to check allergies and prepare dish
        context = (
            f"CLIENT ORDER:\n"
            f"  Name: {client_name}\n"
            f"  Client ID: {client_id}\n"
            f"  Order: {order}\n"
            f"  Intolerances: {intolerances}\n\n"
            f"AVAILABLE RECIPES: {json.dumps(self._current_recipe_ingredients)}\n\n"
            f"INVENTORY: {json.dumps(self.state.inventory)}\n\n"
            f"TASK: Check if the ordered dish is safe for this client (no allergens). "
            f"If safe, call prepare_dish with the exact dish name from the order. "
            f"Store the mapping: dish -> client_id={client_id} for when it's ready to serve."
        )
        await self._run_agent("serving", context, span_name="handle_client_order")







    async def handle_preparation_complete(self, data: dict) -> None:
        if not isinstance(data, dict):
            logger.error("handle_preparation_complete: not a dict!")
            return

        dish = data.get("dish", "")
        meal_id = data.get("id", "")
        self.memory.record_dish_prepared(dish)

        logger.info("─── DISH READY ───")
        logger.info("  Dish:     %s", dish)
        logger.info("  Meal ID:  %s", meal_id)
        logger.info("  Pending:  %d clients", len(self.memory.pending_clients))

        # Find client waiting for this dish
        client_id = await self._find_client_for_dish(dish)
        if not client_id:
            logger.error("No client found waiting for dish: %s", dish)
            return
        
        logger.info("  Client ID:    %s", client_id)

        # Call serving agent to serve the prepared dish
        context = (
            f"PREPARED DISH:\n"
            f"  Dish: {dish}\n"
            f"  Meal ID: {meal_id}\n"
            f"  Client ID: {client_id}\n\n"
            f"TASK: Call serve_dish with dish_name='{dish}' and client_id='{client_id}'"
        )
        await self._run_agent("serving", context, span_name="serve_prepared_dish")

    # ── Phase handlers ───────────────────────────────────────
    async def _handle_speaking(self) -> None:
        """Speaking: run planner once, then set dynamic menu based on inventory."""
        logger.info("── SPEAKING: non facciamo un cazzo stiamo zitti──")
        await self._run_agent("opener", "apriamo il ristorante", span_name="opener_open")



    async def _handle_bidding(self) -> None:
        """Closed bid: UNDERCUTTING — bid 3 credits × 3 units on ALL ingredients."""
        logger.info("── BIDDING: UNDERCUTTING STRATEGY — 3 credits on everything ──")
        logger.info('gli ingredienti da biddare sono: ' + str(ingredienti))

        # Bid on all ingredients in a single call
        logger.info("Bidding on all ingredients: %s", ingredienti)
        await self._run_agent("bidding", "offer 3 for each one of these ingredients: " + str(ingredienti), span_name="bidder_undercut_all")

        # Check what we already have
       
    async def _handle_waiting(self) -> None:
        """Waiting: refresh inventory, rebuild feasible menu, update menu agent."""
        logger.info("── WAITING: Refresh inventory, rebuild feasible menu ──")
        await self._refresh_state()
        await self._rebuild_feasible_menu()

        logger.info('')

        # Update menu agent with new menu
        if self._current_menu:
            logger.info('updating menu based onthe bids')
            await self._run_agent("menu", ' the current menu is' + self._current_menu, span_name="menu_update")
        else:
            logger.warning("No feasible menu to update!")

    async def _handle_serving_phase(self) -> None:
        """Serving start: rebuild menu one more time, update serving agent prompts."""
        logger.info("── SERVING: Ready to serve clients with dynamic menu ──")

        if not isinstance(self.state.recipes, list) or not self.state.recipes:
            logger.warning("No recipes loaded — cannot serve")
            return

        # Refresh inventory and rebuild feasible menu
        await self._refresh_state()
        await self._rebuild_feasible_menu()

        

    async def _handle_stopped(self) -> None:
        """Turn ended — record results, save everything, reset."""
        await self._refresh_state()

        self.memory.record_turn_result(
            turn=self.state.turn_id,
            balance_before=self.memory.turn_balance_start,
            balance_after=self.state.balance,
            clients_served=self.memory.clients_served_this_turn,
        )

        # Save state files
        self.state.save_to_file()
        self.memory.save_to_file(self.state.turn_id)

        logger.info("=" * 60)
        logger.info("TURN %d SUMMARY", self.state.turn_id)
        logger.info("  Balance:  %.1f → %.1f (delta: %.1f)",
                     self.memory.turn_balance_start, self.state.balance,
                     self.state.balance - self.memory.turn_balance_start)
        logger.info("  Served:   %d clients", self.memory.clients_served_this_turn)
        logger.info("  Dishes:   %s", self.memory.served_this_turn)
        logger.info("=" * 60)

        # Reset for next turn
        self.memory.reset_turn()
        self._planner_ran_this_turn = False
        self._feasible_recipes = []
        self._current_menu = []
        self._current_recipe_ingredients = {}

    # ── Dynamic menu builder ─────────────────────────────────
    async def _rebuild_feasible_menu(self) -> None:
        """Rebuild the feasible menu from current inventory + server recipes.
        
        This is the CORE of the dynamic strategy:
        1. Fetch all recipes from /recipes
        2. Check which ones we can make with current inventory
        3. Build menu from feasible recipes
        """
        # Ensure recipes are loaded
        if not self.state.recipes:
            await self._load_recipes()
        
        if not self.state.recipes:
            logger.warning("No recipes from server — cannot build menu")
            return

        # Find feasible recipes
        self._feasible_recipes = find_feasible_recipes(self.state.recipes, self.state.inventory)
        
        # Build menu
        self._current_menu = build_menu_from_feasible(self._feasible_recipes)
        
        # Build ingredients map for serving agent
        self._current_recipe_ingredients = build_recipe_ingredients_map(self._feasible_recipes)
        

    # ── Planner ──────────────────────────────────────────────
    async def _run_planner(self) -> None:
        logger.info("Running planner for turn %d...", self.state.turn_id)

        # Simple context for the planner
        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"PROFIT HISTORY (last 5 turns): {json.dumps(self.memory.profit_history[-5:], default=str)}\n\n"
            f"CURRENT STRATEGY: {json.dumps(self.memory.current_strategy)}\n\n"
            f"TASK: Output your strategy as JSON. Be conservative."
        )

        try:
            result = await self._run_agent_raw("planner", context, span_name="planner_run")
            if result and result.text:
                strategy = self._parse_planner_output(result.text)
                if strategy:
                    self.memory.update_strategy(strategy)
                    logger.info("Planner strategy: %s", json.dumps(self.memory.current_strategy))
                else:
                    logger.warning("Planner returned no valid JSON — using defaults")
            else:
                logger.warning("Planner returned no output — using defaults")
        except Exception as exc:
            logger.exception("Planner error: %s — using defaults", exc)

    def _parse_planner_output(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse planner JSON: %s", text[:200])
            return {}

    # ── Agent execution ──────────────────────────────────────
    async def _run_agent(self, agent_name: str, context: str, span_name: str = "") -> None:
        agent = self.agents.get(agent_name)
        if agent is None:
            logger.error("Agent '%s' not found!", agent_name)
            return

        try:
            logger.info("▶ AGENT [%s] ← %s", agent_name, context[:120].replace("\n", " "))

            if self.tracer and span_name:
                with self.tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("agent.name", agent_name)
                    span.set_attribute("agent.prompt_preview", context[:200])
                    result = await agent.a_run(context)
                    if result and result.text:
                        span.set_attribute("agent.response_preview", result.text[:200])
            else:
                result = await agent.a_run(context)

            response_text = result.text[:300] if result and result.text else "(no text)"
            logger.info("◀ AGENT [%s] → %s", agent_name, response_text.replace("\n", " "))

        except Exception as exc:
            logger.exception("Agent %s error: %s", agent_name, exc)

    async def _run_agent_raw(self, agent_name: str, context: str, span_name: str = ""):
        agent = self.agents.get(agent_name)
        if agent is None:
            logger.error("Agent '%s' not found!", agent_name)
            return None

        try:
            logger.info("▶ AGENT [%s] ← %s", agent_name, context[:120].replace("\n", " "))

            if self.tracer and span_name:
                with self.tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("agent.name", agent_name)
                    result = await agent.a_run(context)
                    if result and result.text:
                        span.set_attribute("agent.response_preview", result.text[:200])
            else:
                result = await agent.a_run(context)

            response_text = result.text[:300] if result and result.text else "(no text)"
            logger.info("◀ AGENT [%s] → %s", agent_name, response_text.replace("\n", " "))
            return result

        except Exception as exc:
            logger.exception("Agent %s error: %s", agent_name, exc)
            return None

    # ── Helpers ──────────────────────────────────────────────
    async def _get_client_id(self, client_name: str) -> str | None:
        """Fetch client ID from meals API by matching client name."""
        try:
            meals = await get_meals(self.state.turn_id)
            logger.debug("get_meals returned %d entries", len(meals))
            
            for meal in meals:
                customer = meal.get("customer") or {}
                meal_name = customer.get("name", "")
                executed = meal.get("executed", False)
                
                if meal_name == client_name and not executed:
                    client_id = meal.get("customerId") or meal.get("id")
                    logger.debug("Found client_id=%s for %s", client_id, client_name)
                    return str(client_id) if client_id else None
            
            logger.warning("Client %s not found in meals", client_name)
            return None
            
        except Exception as exc:
            logger.exception("Error fetching client ID for %s: %s", client_name, exc)
            return None
    
    async def _find_client_for_dish(self, dish_name: str) -> str | None:
        """Find the client ID who ordered this dish from pending clients."""
        try:
            meals = await get_meals(self.state.turn_id)
            
            for meal in meals:
                # The dish name is in the "request" field, not "dish"
                meal_request = meal.get("request", "")
                executed = meal.get("executed", False)
                
                # Check if the dish name is in the request (exact match or contained within)
                if meal_request and not executed:
                    # Try exact match first
                    if meal_request == dish_name or dish_name in meal_request:
                        customer = meal.get("customer") or {}
                        client_id = meal.get("customerId") or meal.get("id")
                        client_name = customer.get("name", "unknown")
                        logger.debug("Found client_id=%s (%s) for dish %s", client_id, client_name, dish_name)
                        return str(client_id) if client_id else None
            
            logger.warning("No pending order found for dish: %s", dish_name)
            return None
            
        except Exception as exc:
            logger.exception("Error finding client for dish %s: %s", dish_name, exc)
            return None

    async def _refresh_state(self) -> None:
        try:
            info = await get_restaurant_info()
            if isinstance(info, dict):
                self.state.update_from_restaurant_info(info)
            else:
                logger.error("get_restaurant_info returned %s!", type(info).__name__)
        except Exception as exc:
            logger.warning("Could not refresh state: %s", exc)

    async def _load_recipes(self) -> None:
        try:
            self.state.recipes = await get_recipes()
            logger.info("Loaded %d recipes from server", len(self.state.recipes))
            # Log all recipe names for debugging
            for r in self.state.recipes:
                if isinstance(r, dict):
                    logger.debug("  Recipe: %s", r.get("name", "?"))
        except Exception as exc:
            logger.warning("Could not load recipes: %s", exc)

    def _log_state(self) -> None:
        """Log current state in a readable way."""
        logger.info("── STATE ──")
        logger.info("  Phase:     %s", self.state.phase)
        logger.info("  Turn:      %d", self.state.turn_id)
        logger.info("  Balance:   %.1f", self.state.balance)
        logger.info("  Open:      %s", self.state.is_open)
        logger.info("  Inventory: %d items", len(self.state.inventory) if isinstance(self.state.inventory, list) else 0)
        if isinstance(self.state.inventory, list):
            for item in self.state.inventory[:15]:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("ingredient_name", "?")
                    qty = item.get("quantity", 1)
                    logger.info("    %s x%d", name, qty)
        logger.info("  Menu:      %d items", len(self.state.menu) if isinstance(self.state.menu, list) else 0)
        logger.info("  Strategy:  %s", json.dumps(self.memory.current_strategy))

    @staticmethod
    async def _safe_call(coro_or_func, default=None):
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
