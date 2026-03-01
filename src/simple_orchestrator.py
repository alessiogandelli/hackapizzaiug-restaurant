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

        if phase == "stopped":
            await self._handle_stopped()
            return
        
        await self._refresh_state()
        self._log_state()


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