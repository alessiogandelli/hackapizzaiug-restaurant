"""Configurazione centralizzata — API keys, URL, headers."""
from __future__ import annotations

import os

# ── Regolo / OpenAI-compatible endpoint ──────────────────────
REGOLO_API_KEY = os.getenv("REGOLO_API_KEY", "sk-0EGRxDbYqhCSdacO97-Brw")
REGOLO_BASE_URL = os.getenv("REGOLO_BASE_URL", "https://api.regolo.ai/v1")

# ── MCP game server ──────────────────────────────────────────
TEAM_ID = os.getenv("TEAM_ID", "15")
TEAM_API_KEY = os.getenv("TEAM_API_KEY", "dTpZhKpZ02-b91de4ab95c9fa33d6c7c9c0")
MCP_URL = os.getenv("MCP_URL", "https://hackapizza.datapizza.tech/mcp")

HEADERS = {
    "x-api-key": TEAM_API_KEY,
    "Content-Type": "application/json",
}
