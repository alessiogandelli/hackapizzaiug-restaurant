"""Game state tracker — single source of truth for the current turn."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class GameState:
    """Mutable singleton that tracks the game's evolving state."""

    def __init__(self):
        self.phase: str = "stopped"       # speaking | closed_bid | waiting | serving | stopped
        self.turn_id: int = 0
        self.restaurant_info: dict = {}
        self.recipes: list[dict] = []
        self.inventory: list[dict] = []
        self.menu: list[dict] = []
        self.balance: float = 0.0
        self.pending_clients: list[dict] = []      # clients waiting to be served
        self.prepared_dishes: list[str] = []        # dishes ready to serve

    # ── Convenience ──────────────────────────────────────────
    def summary(self) -> str:
        """One-paragraph description the agent can reason about."""
        clients_txt = ", ".join(
            f"{c.get('clientName','?')} (order: {c.get('orderText','?')})"
            for c in self.pending_clients
        ) or "none"

        return (
            f"Phase: {self.phase} | Turn: {self.turn_id} | "
            f"Balance: {self.balance} | "
            f"Inventory items: {len(self.inventory)} | "
            f"Menu items: {len(self.menu)} | "
            f"Pending clients: {clients_txt} | "
            f"Prepared dishes: {self.prepared_dishes}"
        )

    def update_from_restaurant_info(self, info: dict):
        """Refresh local cache from /restaurant/:id response."""
        self.restaurant_info = info
        self.balance = info.get("balance", self.balance)
        self.inventory = info.get("inventory", self.inventory)
        self.menu = info.get("menu", self.menu)
        self.turn_id = info.get("turn_id", self.turn_id)
        logger.info("State refreshed — balance=%.1f, inv=%d items", self.balance, len(self.inventory))
