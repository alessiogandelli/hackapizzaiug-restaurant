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
from src.prompts import (
    build_speaking_prompt,
    build_serving_prompt,
)
from src.api import (
    get_restaurant_info,
    get_all_restaurants,
    get_recipes,
    get_market_entries,
    get_bid_history,
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

        if not self._current_recipe_ingredients:
            logger.warning("No feasible recipes — cannot serve client %s", client_name)
            return

        # Build recipe block from DYNAMIC feasible recipes
        recipe_block = "\n".join(
            f"  - {name}: {', '.join(ings)}"
            for name, ings in self._current_recipe_ingredients.items()
        )

        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"OUR AVAILABLE RECIPES AND THEIR INGREDIENTS:\n{recipe_block}\n\n"
            f"ALREADY PREPARED DISHES: {json.dumps(self.memory.prepared_dishes)}\n"
            f"ALREADY SERVED THIS TURN: {json.dumps(self.memory.served_this_turn, default=str)}\n\n"
            f"NEW CLIENT:\n"
            f"  Client name: {client_name}\n"
            f"  Order text: \"{order}\"\n"
            f"  Intolerances: {json.dumps(intolerances)}\n\n"
            f"TASK: Choose the BEST dish for this client from our available recipes.\n"
            f"1. CHECK INTOLERANCES against the ingredients of EACH recipe\n"
            f"2. If a safe dish exists, call prepare_dish with the EXACT recipe name (case-sensitive!)\n"
            f"3. If NO dish is safe, skip this client (do nothing)\n"
            f"4. Dish names must be copied CHARACTER BY CHARACTER"
        )

        await self._run_agent("serving", context, span_name="serve_client")

    async def handle_preparation_complete(self, data: dict) -> None:
        if not isinstance(data, dict):
            logger.error("handle_preparation_complete: not a dict!")
            return

        dish = data.get("dish", "")
        self.memory.record_dish_prepared(dish)

        logger.info("─── DISH READY ───")
        logger.info("  Dish:     %s", dish)
        logger.info("  Pending:  %d clients", len(self.memory.pending_clients))

        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"DISH READY: '{dish}'\n"
            f"PENDING CLIENTS: {json.dumps(self.memory.pending_clients, default=str)}\n"
            f"ALREADY SERVED: {json.dumps(self.memory.served_this_turn, default=str)}\n\n"
            f"TASK: Serve the dish '{dish}' to the appropriate waiting client.\n"
            f"Use serve_dish with the dish_name and the client_id of the matching client."
        )

        await self._run_agent("serving", context, span_name="serve_prepared_dish")

    # ── Phase handlers ───────────────────────────────────────
    async def _handle_speaking(self) -> None:
        """Speaking: run planner once, then set dynamic menu based on inventory."""
        logger.info("── SPEAKING: Running planner + setting dynamic menu ──")

        # Run planner ONCE per turn
        if not self._planner_ran_this_turn:
            await self._run_planner()
            self._planner_ran_this_turn = True
            self.memory.start_turn(self.state.balance)

        # Build dynamic menu from inventory + recipes
        await self._rebuild_feasible_menu()

        if not self._current_menu:
            logger.warning("No feasible recipes — menu will be empty, but still opening restaurant")
            # Still open the restaurant so we can receive clients after bids
        
        # Log what we're about to set
        logger.info("DYNAMIC MENU to set (%d items):", len(self._current_menu))
        for item in self._current_menu:
            logger.info("  %s  →  %d credits", item["name"], item["price"])

        # Build the speaking prompt with the dynamic menu
        speaking_system_prompt = build_speaking_prompt(self._current_menu)
        
        # Temporarily update the speaking agent's system prompt
        speaking_agent = self.agents.get("speaking")
        if speaking_agent:
            speaking_agent._system_prompt = speaking_system_prompt

        menu_json = json.dumps(self._current_menu, ensure_ascii=False)
        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"TASK: You must do TWO things in order:\n"
            f"1. Call save_menu with exactly these items:\n{menu_json}\n"
            f"2. Call update_restaurant_is_open with is_open=true to open the restaurant.\n\n"
            f"CRITICAL: Copy each dish name CHARACTER BY CHARACTER — they are case-sensitive!\n"
            f"Do NOT send any messages."
        )

        await self._run_agent("speaking", context, span_name="phase_speaking")

    async def _handle_bidding(self) -> None:
        """Closed bid: UNDERCUTTING — bid 3 credits × 3 units on ALL ingredients."""
        logger.info("── BIDDING: UNDERCUTTING STRATEGY — 3 credits on everything ──")

        # Check what we already have
        stock = get_inventory_stock(self.state.inventory)
        logger.info("Current stock: %d unique ingredients", len([k for k, v in stock.items() if v > 0]))

        # Build bid list: bid on everything we don't have enough of
        turn_remaining = self.memory.remaining_turn_budget(MAX_TURN_SPEND)
        budget = min(MAX_BID_SPEND, self.state.balance * 0.95, turn_remaining)
        logger.info("  Budget: %.0f (bid cap=%.0f, balance*0.95=%.0f, turn remaining=%.0f)",
                    budget, MAX_BID_SPEND, self.state.balance * 0.95, turn_remaining)
        
        bids = []
        total_cost = 0.0

        for bid_template in DEFAULT_BIDS:
            ing = bid_template["ingredient"]
            have = stock.get(ing, 0)
            want = bid_template["quantity"]

            if have >= want:
                logger.debug("  SKIP %s (have %d, need %d)", ing, have, want)
                continue

            need = want - have
            price = bid_template["bid"]  # 3 credits per unit
            cost = need * price

            if total_cost + cost > budget:
                logger.info("  SKIP %s (budget exceeded: %.0f + %.0f > %.0f)", ing, total_cost, cost, budget)
                continue

            bids.append({
                "ingredient": ing,  # CRITICAL: preserve exact capitalization
                "quantity": need,
                "bid": price,
            })
            total_cost += cost

        logger.info("FINAL BID: %d ingredients, %d credits each, total cost=%.0f, budget=%.0f", 
                    len(bids), BID_PRICE_PER_UNIT, total_cost, budget)

        # Record bid spending against the turn cap
        self.memory.record_spending(total_cost, "bids")

        if not bids:
            logger.info("Nothing to bid on — skipping")
            return

        bids_json = json.dumps(bids, ensure_ascii=False, indent=2)
        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"TASK: Submit these bids by calling closed_bid.\n\n"
            f"USE THIS EXACT JSON (copy character-by-character):\n"
            f"```json\n{bids_json}\n```\n\n"
            f"CRITICAL:\n"
            f"- Ingredient names are case-sensitive\n"
            f"- Copy the ingredient field EXACTLY as shown above\n"
            f"- Do NOT change any capitalization\n"
            f"- Call: closed_bid(bids=<paste the JSON array above>)"
        )

        await self._run_agent("bidding", context, span_name="phase_closed_bid")

    async def _handle_waiting(self) -> None:
        """Waiting: CRITICAL — rebuild feasible menu after bids resolved, update menu."""
        logger.info("── WAITING: Post-bid → rebuilding dynamic menu ──")

        await self._refresh_state()
        self._log_state()

        # Record bid outcomes
        try:
            bid_history = await self._safe_call(lambda: get_bid_history(self.state.turn_id), [])
            if bid_history:
                self.memory.record_bid_result(self.state.turn_id, [], bid_history)
                won = [b for b in bid_history if b.get("status") == "COMPLETED"]
                lost = [b for b in bid_history if b.get("status") != "COMPLETED"]
                logger.info("Bid results: %d WON, %d LOST out of %d total", 
                           len(won), len(lost), len(bid_history))
                for b in won:
                    ing = b.get("ingredient", {}).get("name", "?")
                    price = b.get("priceForEach", "?")
                    logger.info("  WON: %s at %s credits", ing, price)
        except Exception as exc:
            logger.warning("Could not fetch bid history: %s", exc)

        # ═══ KEY STEP: Rebuild feasible menu from inventory + recipes ═══
        await self._rebuild_feasible_menu()

        if self._current_menu:
            logger.info("MENU UPDATED after bids — %d dishes available", len(self._current_menu))
            
            # Update menu via Speaking Agent
            speaking_system_prompt = build_speaking_prompt(self._current_menu)
            speaking_agent = self.agents.get("speaking")
            if speaking_agent:
                speaking_agent._system_prompt = speaking_system_prompt

            menu_json = json.dumps(self._current_menu, ensure_ascii=False)
            context = (
                f"GAME STATE: {self.state.summary()}\n\n"
                f"TASK: Update our menu with these items (we got new ingredients from bids):\n"
                f"Call save_menu with exactly these items:\n{menu_json}\n\n"
                f"CRITICAL: Copy each dish name CHARACTER BY CHARACTER — case-sensitive!\n"
                f"Do NOT send any messages. Do NOT call update_restaurant_is_open."
            )
            await self._run_agent("speaking", context, span_name="phase_waiting_update_menu")
        else:
            logger.warning("No feasible recipes after bids — menu stays empty")
        
        logger.info("Turn spending so far: %.0f / %d", self.memory.turn_total_spent, MAX_TURN_SPEND)

    async def _handle_serving_phase(self) -> None:
        """Serving start: rebuild menu one more time, update serving agent prompts."""
        logger.info("── SERVING: Ready to serve clients with dynamic menu ──")

        if not isinstance(self.state.recipes, list) or not self.state.recipes:
            logger.warning("No recipes loaded — cannot serve")
            return

        # Refresh inventory and rebuild feasible menu
        await self._refresh_state()
        await self._rebuild_feasible_menu()

        if not self._current_recipe_ingredients:
            logger.warning("No feasible recipes — closing restaurant")
            return

        # Update serving agent system prompt with current feasible recipes
        serving_agent = self.agents.get("serving")
        if serving_agent:
            serving_prompt = build_serving_prompt(self._current_recipe_ingredients, self._current_menu)
            serving_agent._system_prompt = serving_prompt

        recipe_block = "\n".join(
            f"  - {name}: {', '.join(ings)}"
            for name, ings in self._current_recipe_ingredients.items()
        )

        logger.info("Restaurant is open. %d dishes available:", len(self._current_recipe_ingredients))
        logger.info("%s", recipe_block)
        logger.info("Waiting for client events.")

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
        
        # Update module-level constants so other code can reference them
        MENU_ITEMS.clear()
        MENU_ITEMS.extend(self._current_menu)
        OUR_RECIPE_NAMES.clear()
        OUR_RECIPE_NAMES.update(r["name"] for r in self._feasible_recipes)
        RECIPE_INGREDIENTS.clear()
        RECIPE_INGREDIENTS.update(self._current_recipe_ingredients)
        
        logger.info("═══ DYNAMIC MENU REBUILT ═══")
        logger.info("  Feasible recipes: %d / %d total", 
                    len(self._feasible_recipes), len(self.state.recipes))
        for item in self._current_menu:
            logger.info("  → %s @ %d credits", item["name"], item["price"])
        if not self._current_menu:
            logger.info("  (no dishes feasible with current inventory)")

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
