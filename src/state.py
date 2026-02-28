"""Game state tracker — single source of truth for raw game server state.

Note: Transient cross-agent state (pending_clients, prepared_dishes, strategy)
lives in GameMemory, not here. This class tracks only what the server tells us.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


class GameState:
    """Mutable singleton that mirrors the game server's view of our restaurant."""

    def __init__(self):
        self.phase: str = "stopped"       # speaking | closed_bid | waiting | serving | stopped
        self.turn_id: int = 0
        self.restaurant_info: dict = {}
        self.recipes: list[dict] = []
        self.inventory: list[dict] = []
        self.menu: list[dict] = []
        self.balance: float = 0.0
        self.is_open: bool = True

    # ── Convenience ──────────────────────────────────────────
    def summary(self) -> str:
        """One-paragraph description any agent can reason about."""
        inv_names = [
            f"{i.get('name', i.get('ingredient_name', '?'))} x{i.get('quantity', 1)}"
            for i in self.inventory[:15]
        ]
        menu_names = [m.get("name", "?") for m in self.menu[:10]]

        return (
            f"Phase: {self.phase} | Turn: {self.turn_id} | "
            f"Balance: {self.balance:.1f} | "
            f"Open: {self.is_open} | "
            f"Inventory ({len(self.inventory)}): {inv_names} | "
            f"Menu ({len(self.menu)}): {menu_names}"
        )

    def update_from_restaurant_info(self, info: dict):
        """Refresh local cache from /restaurant/:id response."""
        if not isinstance(info, dict):
            logger.error("update_from_restaurant_info: expected dict, got %s — %r",
                         type(info).__name__, str(info)[:300])
            return

        self.restaurant_info = info
        self.balance = info.get("balance", self.balance)

        # Validate list fields — API sometimes returns unexpected types
        for field, attr in [("inventory", "inventory"), ("menu", "menu")]:
            val = info.get(field)
            if val is None:
                continue  # keep existing
            if isinstance(val, list):
                setattr(self, attr, val)
            elif isinstance(val, dict):
                # API quirks: inventory can be {} (empty), menu can be {'items': [...]}
                if not val:
                    # empty dict → empty list
                    logger.info("State: '%s' from API is empty dict → treating as []", field)
                    setattr(self, attr, [])
                elif "items" in val and isinstance(val["items"], list):
                    logger.info("State: '%s' from API is dict with 'items' key → unwrapping", field)
                    setattr(self, attr, val["items"])
                else:
                    # dict with unknown structure — try to extract any list value
                    extracted = None
                    for k, v in val.items():
                        if isinstance(v, list):
                            extracted = v
                            break
                    if extracted is not None:
                        logger.info("State: '%s' from API is dict, extracted list from key '%s'", field, k)
                        setattr(self, attr, extracted)
                    else:
                        logger.warning("State: '%s' from API is dict with no list inside: %r — treating as []",
                                       field, str(val)[:300])
                        setattr(self, attr, [])
            else:
                logger.error("State: '%s' from API is %s, not list! value=%r — keeping old value",
                             field, type(val).__name__, str(val)[:300])

        self.turn_id = info.get("turn_id", self.turn_id)
        self.is_open = info.get("is_open", self.is_open)

        inv_len = len(self.inventory) if isinstance(self.inventory, list) else f"?({type(self.inventory).__name__})"
        menu_len = len(self.menu) if isinstance(self.menu, list) else f"?({type(self.menu).__name__})"
        logger.info("State refreshed — balance=%.1f, inv=%s items, menu=%s items, turn=%s",
                     self.balance, inv_len, menu_len, self.turn_id)

    def save_to_file(self) -> None:
        """Save current state to logs/state.json for debugging."""
        LOGS_DIR.mkdir(exist_ok=True)
        path = LOGS_DIR / "state.json"
        try:
            inv_summary = []
            for item in (self.inventory if isinstance(self.inventory, list) else []):
                if isinstance(item, dict):
                    name = item.get("name") or item.get("ingredient_name", "?")
                    qty = item.get("quantity", 1)
                    inv_summary.append(f"{name} x{qty}")
                elif isinstance(item, str):
                    inv_summary.append(item)

            menu_summary = []
            for item in (self.menu if isinstance(self.menu, list) else []):
                if isinstance(item, dict):
                    menu_summary.append({"name": item.get("name", "?"), "price": item.get("price", 0)})

            data = {
                "phase": self.phase,
                "turn_id": self.turn_id,
                "balance": round(self.balance, 1),
                "is_open": self.is_open,
                "inventory_count": len(self.inventory) if isinstance(self.inventory, list) else 0,
                "inventory": inv_summary,
                "menu": menu_summary,
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug("State saved to %s", path.name)
        except Exception as exc:
            logger.warning("Failed to save state: %s", exc)
