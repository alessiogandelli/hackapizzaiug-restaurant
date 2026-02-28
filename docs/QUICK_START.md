# Quick Start Guide

Get your Hackapizza 2.0 agent running in 5 minutes.

---

## Prerequisites

- Python 3.12 or 3.13
- Poetry installed ([installation guide](https://python-poetry.org/docs/#installation))
- Your team credentials (API_KEY, RESTAURANT_ID, REGOLO_API_KEY)

---

## 5-Minute Setup

### 1. Install Dependencies (2 min)

```bash
cd hackapizzaiug-restaurant
poetry install
```

### 2. Configure Environment (1 min)

Create `.env` file in project root:

```bash
cat > .env << EOF
SERVER_URL=https://hackapizza.datapizza.tech
API_KEY=your-api-key-here
RESTAURANT_ID=your-restaurant-id
REGOLO_API_KEY=your-regolo-api-key
REGOLO_MODEL=gpt-oss-120b
EOF
```

**Important**: Replace the placeholder values with your actual credentials!

### 3. Run the Agent (1 min)

```bash
poetry run python run.py
```

### 4. Verify Connection (1 min)

You should see logs like:

```
2026-02-28 10:00:00 [INFO] hackapizza: ═══ Hackapizza 2.0 — Restaurant Agent ═══
2026-02-28 10:00:06 [INFO] src.agent: Loaded 12 MCP tools
2026-02-28 10:00:08 [INFO] src.sse: SSE connected (status 200)
```

**Success!** Your agent is now running and will automatically respond to game events.

---

## What Happens Next?

The agent will:

1. ✅ Connect to the game server
2. ✅ Load available recipes and MCP tools
3. ✅ Listen for game events
4. ✅ Make decisions automatically when:
   - Game phase changes
   - Clients arrive
   - Dishes finish cooking

---

## Common Issues

### "Failed to build agent"

**Cause**: Server is down or wrong credentials.

**Fix**:
1. Check `SERVER_URL` is correct
2. Verify `API_KEY` is valid
3. Test manually:
   ```bash
   curl -H "x-api-key: YOUR_API_KEY" https://hackapizza.datapizza.tech/mcp
   ```

### "SSE 409 Conflict"

**Cause**: Another teammate already has the SSE connection active.

**Fix**: Only one team member can run the agent at a time. Coordinate with your team or wait for their connection to drop.

### "Module not found"

**Cause**: Dependencies not installed.

**Fix**:
```bash
poetry install
```

---

## Next Steps

- **Monitor logs**: Watch the console for agent decisions
- **Read**: [README.md](../README.md) for full documentation
- **Customize**: Edit `src/agent.py` to change agent behavior
- **Compete**: Let it run and maximize your restaurant's balance!

---

## Quick Commands

```bash
# Start agent
poetry run python run.py

# Or with Poetry shell
poetry shell
python run.py

# Run in background (Unix/Mac)
poetry run python run.py &

# Stop background agent
pkill -f "python run.py"

# Check if agent is running
ps aux | grep "run.py"

# View logs in real-time (if redirected to file)
tail -f agent.log
```

---

## Configuration Quick Reference

| Variable | Example | Required |
|----------|---------|----------|
| `SERVER_URL` | `https://hackapizza.datapizza.tech` | No (has default) |
| `API_KEY` | `sk_abc123...` | **Yes** |
| `RESTAURANT_ID` | `restaurant_xyz` | **Yes** |
| `REGOLO_API_KEY` | `rgl_xyz789...` | **Yes** |
| `REGOLO_MODEL` | `gpt-oss-120b` | No (has default) |

---

## Game Phases Cheat Sheet

| Phase | Agent Role | Key Actions |
|-------|-----------|-------------|
| **speaking** | Price setter | Set menu prices, create market listings |
| **closed_bid** | Buyer | Submit ingredient bids (blind) |
| **waiting** | Finalizer | Confirm menu, buy/sell on market |
| **serving** | Chef | Prepare dishes, serve clients |
| **stopped** | Idle | Wait for next turn |

---

## Monitoring Your Agent

### Check Balance
Look for log lines like:
```
[INFO] State refreshed — balance=1250.5, inv=8 items
```

### Track Agent Actions
Look for:
```
[INFO] Agent invoked: Phase changed to serving...
[INFO] Agent response: I will prepare a Cosmic Pizza...
```

### Watch for Errors
Look for:
```
[ERROR] or [WARNING] or [EXCEPTION]
```

---

## Performance Tips

1. **Run on a stable server**, not laptop (avoids disconnections)
2. **Keep logs** for post-game analysis
3. **Monitor balance trend** - is it increasing?
4. **Adjust strategy** in `SYSTEM_PROMPT` if needed

---

## Getting Help

- **Full docs**: See [README.md](../README.md)
- **Technical details**: See [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)
- **Game rules**: See [istruzioni.md](istruzioni.md) (Italian)

---

**Have fun and may your restaurant prosper! 🍕🚀**
