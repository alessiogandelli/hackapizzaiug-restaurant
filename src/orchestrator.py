"""PhaseController — simplified deterministic orchestrator for the 5-recipe strategy.

Flow per turn:
    speaking  → Planner (once) → SpeakingAgent (sets fixed menu + opens restaurant)
    closed_bid→ BiddingAgent (bids on fixed ingredient list)
    waiting   → MarketAgent (defensive trades)
    serving   → ServingAgent (per client event, with intolerance checking)
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
    RECIPE_INGREDIENTS,
    DEFAULT_BIDS,
    MAX_BID_SPEND,
    MAX_TURN_SPEND,
    ALL_INGREDIENTS,
    MAX_MARKET_PRICE,
    compute_market_prices_from_history,
    get_competitive_bid_price,
)
from src.recipes import (
    get_our_recipes_from_server,
    compute_missing_ingredients,
    get_recipe_summary,
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

        # Build recipe block with ingredients for intolerance checking
        recipe_block = "\n".join(
            f"  - {name}: {', '.join(ings)}"
            for name, ings in RECIPE_INGREDIENTS.items()
        )

        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"OUR RECIPES AND THEIR INGREDIENTS:\n{recipe_block}\n\n"
            f"ALREADY PREPARED DISHES: {json.dumps(self.memory.prepared_dishes)}\n"
            f"ALREADY SERVED THIS TURN: {json.dumps(self.memory.served_this_turn, default=str)}\n\n"
            f"NEW CLIENT:\n"
            f"  Client name: {client_name}\n"
            f"  Order text: \"{order}\"\n"
            f"  Intolerances: {json.dumps(intolerances)}\n\n"
            f"TASK: Choose a dish to prepare for this client.\n"
            f"1. CHECK INTOLERANCES against EVERY ingredient in each recipe\n"
            f"2. If a safe dish exists, call prepare_dish with the EXACT recipe name\n"
            f"3. If NO dish is safe, skip this client (do nothing)"
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
        """Speaking: run planner once, then set fixed menu."""
        logger.info("── SPEAKING: Setting menu + running planner ──")

        # Run planner ONCE per turn
        if not self._planner_ran_this_turn:
            await self._run_planner()
            self._planner_ran_this_turn = True
            self.memory.start_turn(self.state.balance)

        # NOTE: opener agent call removed — speaking agent already opens the restaurant below

        # Log what we're about to set
        logger.info("MENU to set:")
        for item in MENU_ITEMS:
            logger.info("  %s  →  %d credits", item["name"], item["price"])

        # Run SpeakingAgent to set the menu and open the restaurant
        menu_json = json.dumps(MENU_ITEMS)
        context = (
            f"GAME STATE: {self.state.summary()}\n\n"
            f"TASK: You must do TWO things in order:\n"
            f"1. Call save_menu with exactly these items:\n{menu_json}\n"
            f"2. Call update_restaurant_is_open with is_open=true to open the restaurant.\n\n"
            f"Do NOT send any messages."
        )

        await self._run_agent("speaking", context, span_name="phase_speaking")

    async def _handle_bidding(self) -> None:
        """Closed bid: compute what we need, submit competitive bids based on market history."""
        logger.info("── BIDDING: Computing bid targets ──")

        # Get bid history to analyze market prices
        market_prices = {}
        try:
            # Get bid history from previous turns (current turn won't have data yet)
            if self.state.turn_id > 1:
                prev_turn_history = await self._safe_call(
                    lambda: get_bid_history(self.state.turn_id - 1), []
                )
                if prev_turn_history:
                    market_prices = compute_market_prices_from_history(prev_turn_history)
                    logger.info("Market prices from turn %d:", self.state.turn_id - 1)
                    for ing, price in sorted(market_prices.items()):
                        logger.info("  %s: %.1f credits", ing, price)
        except Exception as exc:
            logger.warning("Could not fetch market prices: %s", exc)

        # Check what we already have
        stock = compute_missing_ingredients(self.state.inventory)
        logger.info("Current stock of our ingredients:")
        for ing, qty in sorted(stock.items()):
            if qty > 0:
                logger.info("  %s: %d", ing, qty)

        # Build bid list: skip ingredients we already have enough of
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
                logger.info("  SKIP %s (have %d, need %d)", ing, have, want)
                continue

            need = want - have
            
            # Use FIXED price from constants — do NOT adjust based on market history
            fixed_price = bid_template["bid"]
            cost = need * fixed_price

            if total_cost + cost > budget:
                logger.info("  SKIP %s (budget exceeded: %.0f + %.0f > %.0f)", ing, total_cost, cost, budget)
                continue

            bids.append({
                "ingredient": ing,  # CRITICAL: preserve exact capitalization
                "quantity": need,
                "bid": fixed_price,
            })
            total_cost += cost
            logger.info("  BID  %s: qty=%d, price=%d (fixed, total: %.0f)", 
                       ing, need, fixed_price, total_cost)

        logger.info("FINAL BID: %d ingredients, total cost=%.0f, budget=%.0f", len(bids), total_cost, budget)

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
        """Waiting: refresh state after bids, scan market for deals."""
        logger.info("── WAITING: Post-bid analysis + market scan ──")

        await self._refresh_state()
        self._log_state()

        # Record bid outcomes
        try:
            bid_history = await self._safe_call(lambda: get_bid_history(self.state.turn_id), [])
            if bid_history:
                self.memory.record_bid_result(self.state.turn_id, [], bid_history)
                logger.info("Bid history recorded: %d entries", len(bid_history))
        except Exception as exc:
            logger.warning("Could not fetch bid history: %s", exc)

        # Get market entries
        market_entries = await self._safe_call(get_market_entries, [])
        logger.info("Market entries: %d total", len(market_entries) if isinstance(market_entries, list) else 0)

        # Check what we still need
        stock = compute_missing_ingredients(self.state.inventory)
        needed = [ing for ing, qty in stock.items() if qty == 0]
        surplus = []
        for item in self.state.inventory:
            if isinstance(item, dict):
                name = item.get("name") or item.get("ingredient_name", "")
                if name and name.strip() not in ALL_INGREDIENTS:
                    surplus.append(name)

        logger.info("Still need: %s", needed[:10])
        logger.info("Surplus (not in our recipes): %s", surplus[:10])

        # Market agent (buy/sell) is DISABLED — observation only
        logger.info("Market agent disabled — skipping buy/sell actions")
        logger.info("Turn spending so far: %.0f / %d", self.memory.turn_total_spent, MAX_TURN_SPEND)

        # # Build context for market agent
        # market_budget = self.memory.remaining_turn_budget(MAX_TURN_SPEND)
        # context = (
        #     f"GAME STATE: {self.state.summary()}\n\n"
        #     f"INGREDIENTS WE STILL NEED (have 0 in stock): {json.dumps(needed)}\n"
        #     f"SURPLUS INGREDIENTS (not in our recipes): {json.dumps(surplus)}\n"
        #     f"CURRENT BALANCE: {self.state.balance}\n"
        #     f"REMAINING TURN BUDGET: {market_budget:.0f} credits (HARD LIMIT — do NOT exceed this)\n\n"
        #     f"MAX BUY PRICES PER INGREDIENT (do NOT exceed these):\n"
        #     f"  - Polvere di Pulsar: 42 credits\n"
        #     f"  - Foglie di Mandragora: 38 credits\n"
        #     f"  - Spaghi del Sole: 42 credits\n"
        #     f"  - Farina di Nettuno: 58 credits\n"
        #     f"  - Plasma Vitale: 92 credits\n"
        #     f"  - Essenza di Tachioni: 98 credits\n\n"
        #     f"MARKET ENTRIES:\n{json.dumps(market_entries[:20], default=str)}\n\n"
        #     f"TASK: Scan market entries.\n"
        #     f"- BUY: execute_transaction on SELL entries for our 6 ingredients ONLY, if price is at or below the per-ingredient max listed above\n"
        #     f"- SELL: create_market_entry for ANY surplus ingredient (not in our 6) at a fair price\n"
        #     f"- Total market purchases this turn must NOT exceed {market_budget:.0f} credits\n"
        #     f"- If nothing good is available, do nothing."
        # )
        # await self._run_agent("market", context, span_name="phase_waiting")

    async def _handle_serving_phase(self) -> None:
        """Serving start: restaurant should already be open (from speaking phase)."""
        logger.info("── SERVING: Ready to serve clients ──")

        if not isinstance(self.state.recipes, list) or not self.state.recipes:
            logger.warning("No recipes loaded — cannot serve")
            return

        recipe_block = "\n".join(
            f"  - {name}: {', '.join(ings)}"
            for name, ings in RECIPE_INGREDIENTS.items()
        )

        logger.info("Restaurant is open. Waiting for client events.")
        logger.info("Available recipes:\n%s", recipe_block)

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
            ours = get_our_recipes_from_server(self.state.recipes)
            logger.info("Our recipes found on server: %s",
                        [r.get("name", "?") for r in ours])
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
