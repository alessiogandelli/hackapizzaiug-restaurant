"""Configuration — loads .env and exposes settings."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Game server ──────────────────────────────────────────────
SERVER_URL = os.getenv("SERVER_URL", "https://hackapizza.datapizza.tech").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "")

# ── Regolo AI ────────────────────────────────────────────────
REGOLO_API_KEY = os.getenv("REGOLO_API_KEY", "")
REGOLO_MODEL = os.getenv("REGOLO_MODEL", "gpt-oss-120b")
REGOLO_BASE_URL = "https://api.regolo.ai/v1"

# ── Monitoring (Datapizza) ────────────────────────────────────
MONITORING_KEY = os.getenv("MONITORING_KEY", "")
PROJECT_ID = os.getenv("PROJECT_ID", "")
DATAPIZZA_OTLP_ENDPOINT = os.getenv(
    "DATAPIZZA_OTLP_ENDPOINT",
    "https://datapizza-monitoring.datapizza.tech/gateway/v1/traces",
)

# ── Derived ──────────────────────────────────────────────────
HEADERS = {"x-api-key": API_KEY}
MCP_URL = f"{SERVER_URL}/mcp"
SSE_URL = f"{SERVER_URL}/events/{RESTAURANT_ID}"
