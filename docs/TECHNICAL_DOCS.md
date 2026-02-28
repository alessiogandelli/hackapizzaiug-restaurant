# Technical Documentation

## System Architecture Deep Dive

This document provides technical details about the implementation, design decisions, and internal workings of the Hackapizza 2.0 autonomous restaurant agent.

---

## Table of Contents

1. [Concurrency Model](#concurrency-model)
2. [State Management](#state-management)
3. [Error Handling & Resilience](#error-handling--resilience)
4. [SSE Connection Management](#sse-connection-management)
5. [Agent Decision Pipeline](#agent-decision-pipeline)
6. [MCP Tool Integration](#mcp-tool-integration)
7. [Performance Considerations](#performance-considerations)
8. [Security](#security)
9. [Testing Strategies](#testing-strategies)

---

## Concurrency Model

### Asyncio Architecture

The application uses Python's `asyncio` for concurrent operations. The main event loop manages two primary coroutines:

```python
await asyncio.gather(
    listen_sse(event_queue),      # Producer: SSE events
    dispatch_events(event_queue),  # Consumer: Event processor
)
```

#### Producer-Consumer Pattern

```
┌──────────────────┐
│   SSE Listener   │ (Producer)
│   - Persistent   │
│   - Blocking I/O │
└────────┬─────────┘
         │ puts events
         ↓
    ┌─────────┐
    │  Queue  │ (asyncio.Queue - thread-safe)
    └────┬────┘
         │ gets events
         ↓
┌────────────────────┐
│ Event Dispatcher   │ (Consumer)
│ - Event routing    │
│ - Agent invocation │
└────────────────────┘
```

### Why This Design?

1. **Separation of Concerns**: SSE handling is isolated from business logic
2. **Resilience**: If event handling fails, SSE connection remains stable
3. **Buffering**: Queue provides backpressure handling
4. **Testability**: Components can be tested independently

### Blocking Operations

The agent's LLM calls are I/O-bound and can be slow (seconds). We use `await agent.a_run()` to prevent blocking the event loop, allowing SSE events to continue being processed.

---

## State Management

### Single Source of Truth

The `GameState` class is a **mutable singleton** that serves as the application's memory:

```python
state = GameState()  # Module-level, shared across all handlers
```

#### Why Not Immutable State?

- **Simplicity**: No need for complex state diffing or Redux-like patterns
- **Performance**: Direct mutation is faster for rapid updates
- **Single-threaded**: asyncio is single-threaded, no race conditions

### State Lifecycle

```
Turn N starts
    ↓
[game_started] → state.turn_id += 1
    ↓
[game_phase_changed: speaking] → state.phase = "speaking"
    ↓
refresh_state() → state.update_from_restaurant_info(...)
    ↓
    ... (phases continue) ...
    ↓
[game_phase_changed: stopped] → Clear transient data
    ↓
Turn N+1 starts
```

### Transient vs. Persistent Data

| Transient (cleared each turn) | Persistent (cumulative) |
|-------------------------------|-------------------------|
| `pending_clients` | `turn_id` |
| `prepared_dishes` | `balance` |
| | `inventory` (refreshed) |
| | `menu` |

Transient data is cleared in the `stopped` phase:

```python
if phase == "stopped":
    state.pending_clients.clear()
    state.prepared_dishes.clear()
```

---

## Error Handling & Resilience

### Layered Error Handling

#### 1. **Event Handler Level**
Each event handler is wrapped in try-except:

```python
async def dispatch_events(event_queue: asyncio.Queue):
    while True:
        event = await event_queue.get()
        try:
            # ... handle event ...
        except Exception as exc:
            logger.exception("Error handling event %s: %s", etype, exc)
            # Continue processing next event
```

**Rationale**: One bad event shouldn't crash the entire system.

#### 2. **SSE Connection Level**
The SSE loop catches connection errors and auto-reconnects:

```python
async def _sse_loop(event_queue: asyncio.Queue):
    while True:
        try:
            # ... SSE connection ...
        except aiohttp.ClientError as exc:
            logger.warning("SSE disconnected — reconnecting in %ds", RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)
```

**Rationale**: Network issues are transient; retry is often successful.

#### 3. **Agent Level**
Agent invocations are isolated:

```python
async def ask_agent(prompt: str):
    try:
        result = await agent.a_run(context)
    except Exception as exc:
        logger.exception("Agent error: %s", exc)
        # System continues without agent output
```

**Rationale**: AI model errors shouldn't break the event loop.

### Graceful Degradation

If the agent fails to build (server down, wrong API key, etc.):

```python
try:
    agent = build_agent()
except Exception as exc:
    logger.error("Failed to build agent: %s", exc)
    logger.info("Running in listen-only mode")
    agent = None  # Subsequent ask_agent calls do nothing
```

The system still processes events and logs state changes, allowing manual intervention or later recovery.

---

## SSE Connection Management

### The Duplicate Connection Problem

The game server **allows only one SSE connection per team**. Multiple connections return HTTP 409 Conflict.

### Two-Layer Protection

#### 1. **Local File Lock** (prevents local duplicates)

```python
class SSEFileLock:
    def acquire(self) -> bool:
        try:
            self._fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Non-blocking
            return True
        except BlockingIOError:
            return False  # Another local process has the lock
```

If lock acquisition fails:
```python
if not lock.acquire():
    logger.warning("Another local process holds SSE lock — API-only mode")
    while True:
        await asyncio.sleep(60)  # Keep coroutine alive
```

#### 2. **Server-Side Conflict Detection** (handles remote duplicates)

```python
async with session.get(SSE_URL) as resp:
    if resp.status == 409:
        logger.warning("SSE 409 — teammate has connection")
        await asyncio.sleep(CONFLICT_RETRY_DELAY)
        continue  # Retry later
```

### Reconnection Strategy

| Scenario | Delay | Behavior |
|----------|-------|----------|
| Network error | 3s | Exponential backoff (not implemented, constant for simplicity) |
| HTTP 409 | 30s | Longer delay to avoid spam |
| Other HTTP errors | 3s | Quick retry |

### SSE Event Parsing

Standard SSE format:

```
data: {"type": "client_spawned", "data": {...}}

data: connected

data: {"type": "heartbeat"}
```

Parser extracts `data:` lines and deserializes JSON:

```python
async def _parse_line(raw: bytes) -> dict | None:
    line = raw.decode("utf-8", errors="ignore").strip()
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "connected":
            return None  # Handshake, not an event
        return json.loads(payload)
```

---

## Agent Decision Pipeline

### Agent Invocation Flow

```
Event occurs (e.g., client_spawned)
    ↓
ask_agent(prompt) called
    ↓
Build context:
    - state.summary() (current game state)
    - state.recipes (available recipes)
    - prompt (specific task)
    ↓
agent.a_run(context)
    ↓
Agent thinks (LLM reasoning)
    ↓
Agent executes tools (MCP calls)
    ↓
Agent returns result
    ↓
Log agent response
```

### Context Construction

The agent receives a consolidated context string:

```python
context = (
    f"GAME STATE:\n{state.summary()}\n\n"
    f"RECIPES AVAILABLE: {json.dumps(state.recipes[:10], default=str)}\n\n"
    f"YOUR TASK:\n{prompt}"
)
```

**Trade-off**: Recipes are truncated to first 10 to save tokens. Full list is loaded once and cached.

### Agent Configuration

```python
agent = Agent(
    name="Galactic_Chef",
    client=OpenAILikeClient(...),
    system_prompt=SYSTEM_PROMPT,  # See src/agent.py
    tools=mcp_tools,               # Loaded from server
    max_steps=15,                  # Prevents infinite loops
    planning_interval=3,           # Re-evaluate every 3 steps
)
```

#### `max_steps`
Limits tool calls to prevent:
- Infinite loops
- Excessive token usage
- Timeout on slow models

#### `planning_interval`
Agent re-evaluates its strategy every N steps:
- Step 1-3: Execute initial plan
- Step 3: Re-plan based on results
- Step 4-6: Execute revised plan
- ...

This allows adaptive behavior when initial assumptions fail.

---

## MCP Tool Integration

### Model Context Protocol (MCP)

MCP is a protocol for exposing tools to LLM agents. The game server implements an MCP endpoint:

```
GET https://hackapizza.datapizza.tech/mcp
```

Returns tool definitions in OpenAI function-calling format:

```json
{
  "tools": [
    {
      "name": "closed_bid",
      "description": "Submit a blind bid for ingredients",
      "parameters": {
        "type": "object",
        "properties": {
          "ingredient": {"type": "string"},
          "amount": {"type": "number"}
        }
      }
    },
    ...
  ]
}
```

### Tool Loading

```python
def build_mcp_tools() -> list:
    mcp = MCPClient(url=MCP_URL, headers=HEADERS)
    tools = mcp.list_tools()  # Fetches from server
    return tools
```

### Tool Execution

When the agent decides to use a tool:

1. **LLM generates tool call** with function name and arguments
2. **datapizza-ai framework** intercepts the call
3. **MCPClient** sends HTTP request to server:
   ```
   POST https://hackapizza.datapizza.tech/mcp/{tool_name}
   Headers: x-api-key: {API_KEY}
   Body: {tool_arguments}
   ```
4. **Server executes** game action (e.g., submits bid)
5. **Response** is returned to LLM as tool result
6. **LLM continues reasoning** with the result

### Authentication

All MCP tool calls include the `x-api-key` header from `HEADERS`:

```python
HEADERS = {"x-api-key": API_KEY}
mcp = MCPClient(url=MCP_URL, headers=HEADERS)
```

---

## Performance Considerations

### Token Budget

Each agent invocation consumes tokens:
- System prompt: ~500 tokens
- Context (state + recipes): ~1000 tokens
- Tool definitions: ~2000 tokens (depends on number of tools)
- Conversation history: Grows with each step

**Optimization**: Truncate recipe list to 10 items.

### API Rate Limits

- **Regolo AI**: Check model tier for rate limits
- **Game Server**: Has rate limiting per team (specifics TBD)

**Mitigation**: The agent naturally throttles itself via event-driven architecture (only acts when events occur).

### Memory Usage

- `GameState`: Minimal (<1MB)
- `event_queue`: Bounded by event rate (~10 events/turn)
- `agent`: Stateless (no conversation history stored)

**Footprint**: ~50MB runtime memory.

### Network Bandwidth

- **SSE**: Low bandwidth (~1KB/event, <100 events/turn)
- **REST API**: Only called on phase changes (~5/turn)
- **MCP tools**: Variable (depends on agent actions)

---

## Security

### Authentication

All requests use API key authentication:

```python
HEADERS = {"x-api-key": API_KEY}
```

### Secret Management

Secrets stored in `.env` file (**never commit to git**):

```env
API_KEY=secret123
REGOLO_API_KEY=sk-xxxx
```

**Best Practice**: Use environment variables in production:

```bash
export API_KEY=secret123
export REGOLO_API_KEY=sk-xxxx
python run.py
```

### Input Validation

The game server validates:
- Tool parameters (type checking)
- Restaurant ID in URLs
- Turn/phase constraints

Client-side validation is minimal (trust the server).

### Injection Risks

**LLM Prompt Injection**: The agent's context includes user-generated content (client orders, broadcast messages). The system prompt instructs the agent to be cautious, but sophisticated attacks may still work.

**Mitigation**:
- Clear system prompt separating instructions from data
- Server-side validation of tool calls
- Monitoring for anomalous behavior

---

## Testing Strategies

### Unit Testing

Test individual components in isolation:

```python
# test_state.py
def test_state_summary():
    state = GameState()
    state.phase = "serving"
    state.balance = 100.0
    summary = state.summary()
    assert "serving" in summary
    assert "100" in summary

# test_api.py
@pytest.mark.asyncio
async def test_get_restaurant_info(mock_server):
    info = await get_restaurant_info()
    assert "balance" in info
```

### Integration Testing

Test SSE + dispatcher integration:

```python
@pytest.mark.asyncio
async def test_event_flow():
    queue = asyncio.Queue()
    await queue.put({"type": "game_phase_changed", "data": {"phase": "serving"}})
    
    # Run dispatcher briefly
    task = asyncio.create_task(dispatch_events(queue))
    await asyncio.sleep(0.1)
    task.cancel()
    
    assert state.phase == "serving"
```

### End-to-End Testing

Run against a test game server:

```bash
export SERVER_URL=https://test.hackapizza.datapizza.tech
export API_KEY=test-key
python run.py
```

Monitor logs for expected behavior.

### Agent Testing

Test agent with mock MCP tools:

```python
def test_agent_decides_to_bid():
    mock_tools = [MockTool("closed_bid")]
    agent = build_agent_with_tools(mock_tools)
    
    result = agent.run("Submit a bid for flour")
    
    assert mock_tools[0].called
    assert mock_tools[0].args["ingredient"] == "flour"
```

---

## Design Decisions

### Why Not a Database?

**Decision**: Use in-memory `GameState` instead of persistent storage.

**Rationale**:
- State is ephemeral (resets with game restart)
- No need for historical queries
- Simplifies deployment (no DB setup)
- Fast access (no I/O overhead)

**Trade-off**: Restart loses state (acceptable for a competition).

### Why SSE Over WebSockets?

**Decision**: Server uses Server-Sent Events, not WebSockets.

**Rationale** (server-side):
- Simpler protocol (one-way push)
- HTTP-compatible (easier proxying)
- Auto-reconnect built into browsers/clients

**Client handling**: We implement auto-reconnect and 409 handling.

### Why datapizza-ai Framework?

**Decision**: Use datapizza-ai instead of raw OpenAI SDK or LangChain.

**Rationale**:
- MCP integration built-in
- Planning interval feature
- Simpler API for agentic workflows
- Competition-specific tooling

**Trade-off**: Less flexibility than raw SDK.

### Why Async Everywhere?

**Decision**: Use `asyncio` and `aiohttp` instead of synchronous code.

**Rationale**:
- SSE requires long-lived connections (blocking in sync code)
- LLM calls are I/O-bound (benefit from async)
- Multiple concurrent operations (SSE + API calls + agent)

**Trade-off**: More complex code (but necessary for requirements).

---

## Future Enhancements

### Potential Improvements

1. **Logging to File**
   - Persist logs for post-game analysis
   - Implement log rotation

2. **Metrics/Telemetry**
   - Track agent decision latency
   - Monitor tool call success rates
   - Dashboard for real-time monitoring

3. **State Persistence**
   - Save state to JSON file periodically
   - Recover from crashes without losing turn data

4. **Multi-Agent Coordination**
   - If team runs multiple agents (different strategies)
   - Coordination protocol via game server messages

5. **Adaptive Strategy**
   - Learn from past turns
   - Adjust bidding strategy based on win rate

6. **Simulator Mode**
   - Test agent against mock game server
   - Evaluate strategies offline

7. **Configuration UI**
   - Web interface to adjust agent parameters live
   - Monitor state without parsing logs

---

## Debugging Tips

### Enable Debug Logging

```python
# src/main.py
logging.basicConfig(
    level=logging.DEBUG,  # Was INFO
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

### Inspect Agent Reasoning

The agent framework may log LLM thoughts. Check datapizza-ai docs for verbose mode.

### Simulate Events

Manually push events to the queue for testing:

```python
# In main.py, after building event_queue:
await event_queue.put({
    "type": "client_spawned",
    "data": {"clientName": "Test", "orderText": "pizza"}
})
```

### Monitor Network Traffic

Use a proxy like `mitmproxy` to inspect HTTP traffic:

```bash
mitmproxy -p 8080
export HTTPS_PROXY=http://localhost:8080
python run.py
```

### Check SSE Lock

If script won't connect:

```bash
ls -la sse.lock
# If exists and shouldn't:
rm sse.lock
```

---

## Performance Profiling

### Measure Agent Latency

```python
import time

async def ask_agent(prompt: str):
    start = time.time()
    result = await agent.a_run(context)
    elapsed = time.time() - start
    logger.info("Agent took %.2fs for %d steps", elapsed, len(result.steps))
```

### Profile with cProfile

```bash
python -m cProfile -o profile.out run.py
# Analyze with snakeviz:
snakeviz profile.out
```

### Memory Profiling

```bash
pip install memory-profiler
python -m memory_profiler run.py
```

---

## Conclusion

This document covers the technical internals of the Hackapizza 2.0 autonomous agent. Key takeaways:

- **Event-driven architecture** with asyncio enables responsive, resilient operation
- **SSE connection management** handles network issues and team coordination
- **Agent pipeline** integrates MCP tools with LLM reasoning
- **Error handling** at multiple layers ensures system stability
- **Minimal dependencies** keep deployment simple

For questions or contributions, refer to the main [README.md](../README.md).

---

**Last Updated**: 2026-02-28  
**Version**: 0.1.0
