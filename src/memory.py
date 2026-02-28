"""GameMemory — simplified shared memory for the multi-agent architecture.

Tracks turn results, pending clients, prepared dishes, and saves to JSON files.
No complex context builders — the orchestrator builds context directly.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.constants import DEFAULT_STRATEGY

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


@dataclass
class GameMemory:
    """Cross-turn, cross-agent shared memory — simplified."""

    # ── Strategy (planner output) ────────────────────────────
    current_strategy: dict = field(default_factory=lambda: dict(DEFAULT_STRATEGY))

    # ── Historical data (persists across turns, capped) ──────
    profit_history: list[dict] = field(default_factory=list)
    previous_bids: list[dict] = field(default_factory=list)

    # ── Current turn data (cleared on stopped) ───────────────
    pending_clients: list[dict] = field(default_factory=list)
    prepared_dishes: list[str] = field(default_factory=list)
    served_this_turn: list[dict] = field(default_factory=list)
    turn_balance_start: float = 0.0
    clients_served_this_turn: int = 0
    messages_received: list[dict] = field(default_factory=list)

    # ── Recording methods ────────────────────────────────────
    def update_strategy(self, strategy: dict) -> None:
        """Merge new strategy from planner, keeping defaults for missing keys."""
        valid_keys = set(DEFAULT_STRATEGY.keys())
        for k, v in strategy.items():
            if k in valid_keys:
                self.current_strategy[k] = v
        logger.info("MEMORY | Strategy updated: %s", self.current_strategy)

    def record_client(self, client_data: dict) -> None:
        self.pending_clients.append(client_data)
        logger.info("MEMORY | Client recorded: %s (total pending: %d)",
                     client_data.get("clientName", "?"), len(self.pending_clients))

    def record_dish_prepared(self, dish_name: str) -> None:
        self.prepared_dishes.append(dish_name)
        logger.info("MEMORY | Dish prepared: %s (total: %d)", dish_name, len(self.prepared_dishes))

    def record_dish_served(self, dish_name: str, client_id: str) -> None:
        self.served_this_turn.append({"dish": dish_name, "client_id": client_id})
        self.clients_served_this_turn += 1
        logger.info("MEMORY | Dish served: %s → client %s (total served: %d)",
                     dish_name, client_id, self.clients_served_this_turn)

    def record_message(self, sender: str, text: str) -> None:
        self.messages_received.append({"sender": sender, "text": text})

    def record_bid_result(self, turn: int, bids: list, outcomes: list) -> None:
        self.previous_bids.append({"turn": turn, "bids": bids, "outcomes": outcomes})
        if len(self.previous_bids) > 10:
            self.previous_bids = self.previous_bids[-10:]

    def record_turn_result(self, turn: int, balance_before: float, balance_after: float, clients_served: int) -> None:
        delta = balance_after - balance_before
        self.profit_history.append({
            "turn": turn,
            "balance_before": round(balance_before, 1),
            "balance_after": round(balance_after, 1),
            "delta": round(delta, 1),
            "clients_served": clients_served,
        })
        if len(self.profit_history) > 20:
            self.profit_history = self.profit_history[-20:]
        logger.info("MEMORY | Turn %d result: delta=%.1f, served=%d, balance=%.1f→%.1f",
                     turn, delta, clients_served, balance_before, balance_after)

    def start_turn(self, balance: float) -> None:
        self.turn_balance_start = balance
        logger.info("MEMORY | Turn started — balance_start=%.1f", balance)

    # ── Turn lifecycle ───────────────────────────────────────
    def reset_turn(self) -> None:
        self.pending_clients.clear()
        self.prepared_dishes.clear()
        self.served_this_turn.clear()
        self.messages_received.clear()
        self.clients_served_this_turn = 0
        logger.info("MEMORY | Turn data cleared")

    # ── Serialization ────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "current_strategy": self.current_strategy,
            "profit_history": self.profit_history,
            "previous_bids": self.previous_bids[-3:],
            "pending_clients": self.pending_clients,
            "prepared_dishes": self.prepared_dishes,
            "served_this_turn": self.served_this_turn,
            "turn_balance_start": self.turn_balance_start,
            "clients_served_this_turn": self.clients_served_this_turn,
            "messages_received": self.messages_received,
        }

    def save_to_file(self, turn_id: int) -> None:
        """Save memory state to logs/memory_turn_N.json."""
        LOGS_DIR.mkdir(exist_ok=True)
        path = LOGS_DIR / f"memory_turn_{turn_id}.json"
        try:
            with open(path, "w") as f:
                json.dump(self.to_dict(), f, indent=2, default=str)
            logger.info("MEMORY | Saved to %s", path.name)
        except Exception as exc:
            logger.warning("MEMORY | Failed to save: %s", exc)
