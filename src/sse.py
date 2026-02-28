"""SSE listener — one connection per team enforced by the server (409 on duplicate).

Strategy:
- Try to connect; if 409 → another teammate already has the SSE slot.
- Local file-lock (sse.lock) prevents *local* duplication (two terminals).
- On disconnect, auto-retry with back-off.
- Events are pushed into an asyncio.Queue for the dispatcher.
"""
import asyncio
import json
import logging
import os
import fcntl
from pathlib import Path

import aiohttp

from src.config import SSE_URL, HEADERS

logger = logging.getLogger(__name__)

LOCK_FILE = Path(__file__).resolve().parent.parent / "sse.lock"
RECONNECT_DELAY = 3          # seconds between reconnect attempts
CONFLICT_RETRY_DELAY = 30    # seconds to wait before retrying after a 409


# ── Local file lock ──────────────────────────────────────────
class SSEFileLock:
    """
    Advisory file lock so two local processes don't both try to open the SSE
    stream and waste one connection attempt (the server rejects duplicates with 409).
    """

    def __init__(self):
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to grab the lock. Returns True on success."""
        try:
            self._fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(self._fd, f"{os.getpid()}\n".encode())
            logger.debug("SSE file-lock acquired (pid %d)", os.getpid())
            return True
        except (OSError, BlockingIOError):
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            return False

    def release(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            logger.debug("SSE file-lock released")


# ── SSE line parser (matches official template exactly) ──────
async def _parse_line(raw: bytes) -> dict | None:
    """Parse one SSE line. Matches the official client_template.py logic."""
    if not raw:
        return None

    line = raw.decode("utf-8", errors="ignore").strip()
    if not line:
        return None

    # Standard SSE data format: data: ...
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "connected":
            logger.info("SSE handshake OK")
            return None
        line = payload

    try:
        event_json = json.loads(line)
    except json.JSONDecodeError:
        logger.info("SSE raw: %s", line[:200])
        return None

    event_type = event_json.get("type", "unknown")
    event_data = event_json.get("data", {})
    if not isinstance(event_data, dict):
        event_data = {"value": event_data}

    return {"type": event_type, "data": event_data}


# ── Public entry point ───────────────────────────────────────
async def listen_sse(event_queue: asyncio.Queue) -> None:
    """
    Open a persistent SSE connection with automatic reconnect.

    - Uses a file-lock to prevent local duplication.
    - On HTTP 409 (connection already active) logs a clear warning and retries
      later in case the other instance drops.

    Events are placed on *event_queue* as dicts: {"type": ..., "data": ...}
    """
    lock = SSEFileLock()

    if not lock.acquire():
        logger.warning(
            "Another local process already holds the SSE lock (%s). "
            "Running in API-only mode — no live events.",
            LOCK_FILE,
        )
        # Keep the coroutine alive but idle so gather() doesn't exit
        while True:
            await asyncio.sleep(60)

    try:
        await _sse_loop(event_queue)
    finally:
        lock.release()


async def _sse_loop(event_queue: asyncio.Queue) -> None:
    """Core reconnecting SSE loop."""
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)

    while True:
        try:
            async with aiohttp.ClientSession(
                headers={"Accept": "text/event-stream", **HEADERS},
                timeout=timeout,
            ) as session:
                logger.info("\U0001f50c SSE connecting  →  %s", SSE_URL)
                async with session.get(SSE_URL) as resp:
                    if resp.status == 409:
                        logger.warning(
                            "SSE 409 Conflict — a teammate already has the connection. "
                            "Retrying in %ds …",
                            CONFLICT_RETRY_DELAY,
                        )
                        await asyncio.sleep(CONFLICT_RETRY_DELAY)
                        continue

                    resp.raise_for_status()
                    logger.info("\u2705 SSE connected")

                    async for raw_line in resp.content:
                        event = await _parse_line(raw_line)
                        if event is not None:
                            await event_queue.put(event)

        except aiohttp.ClientResponseError as exc:
            if exc.status == 409:
                logger.warning(
                    "SSE 409 Conflict — retrying in %ds …",
                    CONFLICT_RETRY_DELAY,
                )
                await asyncio.sleep(CONFLICT_RETRY_DELAY)
                continue
            logger.warning("SSE HTTP error %s — reconnecting in %ds …", exc.status, RECONNECT_DELAY)

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("SSE disconnected (%s) — reconnecting in %ds …", exc, RECONNECT_DELAY)

        except Exception as exc:
            logger.exception("SSE unexpected error: %s", exc)

        await asyncio.sleep(RECONNECT_DELAY)
