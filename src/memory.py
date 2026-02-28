"""GameMemory — structured shared memory for the multi-agent architecture.

The StrategicPlanner writes strategy here.
Executor agents read their relevant slices via get_*_context() helpers.
No agent-to-agent chat — all coordination flows through this object.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GameMemory:
    """Cross-turn, cross-agent shared memory."""

    # ── Planner output ───────────────────────────────────────
    current_strategy: dict = field(default_factory=lambda: {
        "segment": "balanced",
        "bid_aggression": 0.5,
        "target_margin": 0.4,
        "inventory_risk_limit": 500,
        "market_strategy": "defensive",
        "speaking_strategy": "bluff_premium",
    })

    # ── Historical data (persists across turns) ──────────────
    previous_bids: list[dict] = field(default_factory=list)        # [{turn, bids, outcomes}]
    competitor_profiles: dict[str, dict] = field(default_factory=dict)  # {restaurant_id: {...}}
    profit_history: list[dict] = field(default_factory=list)       # [{turn, balance_before, balance_after, delta, clients_served}]
    demand_stats: dict[str, Any] = field(default_factory=lambda: {
        "archetype_counts": {},       # {archetype: count}
        "avg_order_value": 0.0,
        "total_clients_seen": 0,
        "intolerance_incidents": 0,
    })

    # ── Current turn data (cleared on stopped) ───────────────
    feasible_recipes: list[dict] = field(default_factory=list)
    ingredient_demand: dict[str, int] = field(default_factory=dict)  # {ingredient_name: qty_needed}
    pending_clients: list[dict] = field(default_factory=list)
    prepared_dishes: list[str] = field(default_factory=list)
    served_this_turn: list[dict] = field(default_factory=list)
    turn_balance_start: float = 0.0
    clients_served_this_turn: int = 0

    # ── Messages received this turn ──────────────────────────
    messages_received: list[dict] = field(default_factory=list)  # [{sender, text}]

    # ── Planner interface ────────────────────────────────────
    def update_strategy(self, strategy: dict) -> None:
        """Called by StrategicPlanner after each planning run."""
        # Validate and merge — keep defaults for missing keys
        valid_keys = {
            "segment", "bid_aggression", "target_margin",
            "inventory_risk_limit", "market_strategy", "speaking_strategy",
        }
        for k, v in strategy.items():
            if k in valid_keys:
                self.current_strategy[k] = v
        logger.info("Strategy updated: %s", self.current_strategy)

    # ── Recording methods ────────────────────────────────────
    def record_bid_result(self, turn: int, bids: list[dict], outcomes: list[dict]) -> None:
        """Store bid history for learning."""
        self.previous_bids.append({
            "turn": turn,
            "bids": bids,
            "outcomes": outcomes,
        })
        # Keep last 10 turns
        if len(self.previous_bids) > 10:
            self.previous_bids = self.previous_bids[-10:]

    def record_turn_result(self, turn: int, balance_before: float, balance_after: float, clients_served: int) -> None:
        """Called on stopped phase to record performance."""
        delta = balance_after - balance_before
        self.profit_history.append({
            "turn": turn,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "delta": delta,
            "clients_served": clients_served,
        })
        if len(self.profit_history) > 20:
            self.profit_history = self.profit_history[-20:]
        logger.info("Turn %d result: delta=%.1f, served=%d", turn, delta, clients_served)

    def update_competitor(self, restaurant_id: str, observations: dict) -> None:
        """Update competitor profile with latest observations."""
        if restaurant_id not in self.competitor_profiles:
            self.competitor_profiles[restaurant_id] = {}
        self.competitor_profiles[restaurant_id].update(observations)

    def record_client(self, client_data: dict) -> None:
        """Track demand statistics from a client spawn event."""
        self.pending_clients.append(client_data)
        archetype = client_data.get("archetype", "unknown")
        self.demand_stats["archetype_counts"][archetype] = (
            self.demand_stats["archetype_counts"].get(archetype, 0) + 1
        )
        self.demand_stats["total_clients_seen"] += 1

    def record_dish_prepared(self, dish_name: str) -> None:
        """Track a dish that completed preparation."""
        self.prepared_dishes.append(dish_name)

    def record_dish_served(self, dish_name: str, client_id: str) -> None:
        """Track a served dish."""
        self.served_this_turn.append({"dish": dish_name, "client_id": client_id})
        self.clients_served_this_turn += 1

    def record_message(self, sender: str, text: str) -> None:
        """Track incoming messages for the planner/speaking agent."""
        self.messages_received.append({"sender": sender, "text": text})

    # ── Context builders (read-only slices for executors) ────
    def get_planner_context(self, state_summary: str, all_restaurants: list, bid_history: list) -> str:
        """Full context for the StrategicPlanner."""
        import json
        return json.dumps({
            "game_state": state_summary,
            "current_strategy": self.current_strategy,
            "profit_history": self.profit_history[-5:],
            "previous_bids": self.previous_bids[-3:],
            "competitor_profiles": dict(list(self.competitor_profiles.items())[:5]),
            "demand_stats": self.demand_stats,
            "all_restaurants": all_restaurants[:10],
            "recent_bid_history": bid_history[:20],
            "messages_received": self.messages_received[-10:],
        }, default=str, indent=1)

    def get_speaking_context(self, state_summary: str) -> str:
        """Context for SpeakingAgent — competitor info + directives."""
        import json
        return json.dumps({
            "game_state": state_summary,
            "speaking_strategy": self.current_strategy.get("speaking_strategy", "bluff_premium"),
            "segment": self.current_strategy.get("segment", "balanced"),
            "target_margin": self.current_strategy.get("target_margin", 0.4),
            "competitor_profiles": dict(list(self.competitor_profiles.items())[:5]),
            "messages_received": self.messages_received[-5:],
        }, default=str, indent=1)

    def get_bidding_context(self, state_summary: str, inventory: list) -> str:
        """Context for BiddingAgent — aggression + demand + history."""
        import json
        return json.dumps({
            "game_state": state_summary,
            "bid_aggression": self.current_strategy.get("bid_aggression", 0.5),
            "inventory_risk_limit": self.current_strategy.get("inventory_risk_limit", 500),
            "ingredient_demand": self.ingredient_demand,
            "current_inventory": inventory,
            "previous_bids": self.previous_bids[-3:],
            "feasible_recipes": [r.get("name", "") for r in self.feasible_recipes[:15]],
        }, default=str, indent=1)

    def get_market_context(self, state_summary: str, inventory: list, market_entries: list) -> str:
        """Context for MarketAgent — surplus/shortage + strategy."""
        import json
        return json.dumps({
            "game_state": state_summary,
            "market_strategy": self.current_strategy.get("market_strategy", "defensive"),
            "ingredient_demand": self.ingredient_demand,
            "current_inventory": inventory,
            "market_entries": market_entries[:20],
            "segment": self.current_strategy.get("segment", "balanced"),
        }, default=str, indent=1)

    def get_serving_context(self, state_summary: str, client_data: dict | None = None) -> str:
        """Context for ServingAgent — client + intolerances + dishes."""
        import json
        ctx = {
            "game_state": state_summary,
            "pending_clients": self.pending_clients,
            "prepared_dishes": self.prepared_dishes,
            "served_this_turn": self.served_this_turn,
            "feasible_recipes": self.feasible_recipes[:10],
        }
        if client_data:
            ctx["current_client"] = client_data
        return json.dumps(ctx, default=str, indent=1)

    # ── Turn lifecycle ───────────────────────────────────────
    def reset_turn(self) -> None:
        """Clear transient per-turn data on stopped phase."""
        self.pending_clients.clear()
        self.prepared_dishes.clear()
        self.served_this_turn.clear()
        self.messages_received.clear()
        self.ingredient_demand.clear()
        self.feasible_recipes.clear()
        self.clients_served_this_turn = 0
        logger.info("Memory: turn data cleared")

    def start_turn(self, balance: float) -> None:
        """Mark the start of a new turn for profit tracking."""
        self.turn_balance_start = balance
