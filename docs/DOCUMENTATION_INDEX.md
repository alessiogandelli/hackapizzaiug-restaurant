# Documentation Index

Welcome to the Hackapizza 2.0 Restaurant Agent documentation! This index will help you find the right information quickly.

---

## 📚 Documentation Structure

```
docs/
├── QUICK_START.md          ⚡ Get running in 5 minutes
├── TECHNICAL_DOCS.md       🔧 Deep dive into architecture
├── API_EXAMPLES.md         📖 Code examples and patterns
├── istruzioni.md           🇮🇹 Game rules (Italian)
└── DOCUMENTATION_INDEX.md  📋 This file

../README.md                🏠 Main documentation
```

---

## 🚀 Quick Navigation

### I want to...

#### **Get Started Immediately**
→ Read [QUICK_START.md](QUICK_START.md) (5 minutes)

#### **Understand How It Works**
→ Read [README.md](../README.md) - Architecture & Flow sections

#### **Understand the Game Rules**
→ Read [istruzioni.md](istruzioni.md) (Italian)

#### **Dive Deep into Implementation**
→ Read [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)

#### **See Code Examples**
→ Browse [API_EXAMPLES.md](API_EXAMPLES.md)

#### **Troubleshoot Issues**
→ Check [README.md#troubleshooting](../README.md#troubleshooting)

#### **Customize Agent Behavior**
→ See [API_EXAMPLES.md#agent-prompting-examples](API_EXAMPLES.md#agent-prompting-examples)

#### **Add New Features**
→ See [API_EXAMPLES.md#custom-event-handlers](API_EXAMPLES.md#custom-event-handlers)

---

## 📖 Documentation by Topic

### Setup & Configuration

| Topic | Document | Section |
|-------|----------|---------|
| Installation | [QUICK_START.md](QUICK_START.md) | Steps 1-3 |
| Environment Variables | [README.md](../README.md) | Configuration |
| Python Environment | [QUICK_START.md](QUICK_START.md) | Prerequisites |

### Architecture

| Topic | Document | Section |
|-------|----------|---------|
| System Overview | [README.md](../README.md) | Architecture |
| Component Diagram | [README.md](../README.md) | Architecture |
| Concurrency Model | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) | Concurrency Model |
| State Management | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) | State Management |

### Components

| Component | Main Doc | Technical Details |
|-----------|----------|-------------------|
| SSE Listener | [README.md](../README.md) | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#sse-connection-management) |
| Event Dispatcher | [README.md](../README.md) | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#concurrency-model) |
| Agent | [README.md](../README.md) | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#agent-decision-pipeline) |
| State Tracker | [README.md](../README.md) | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#state-management) |
| API Client | [README.md](../README.md) | [API_EXAMPLES.md](API_EXAMPLES.md#rest-api-examples) |

### Game Mechanics

| Topic | Document | Section |
|-------|----------|---------|
| Game Phases | [README.md](../README.md) | Game Phases |
| Turn Lifecycle | [istruzioni.md](istruzioni.md) | Challenge Description |
| Ingredients & Expiry | [istruzioni.md](istruzioni.md) | Regola fondamentale |
| Client Serving | [README.md](../README.md) | Serving Phase |

### Development

| Topic | Document | Section |
|-------|----------|---------|
| Adding Event Handlers | [API_EXAMPLES.md](API_EXAMPLES.md) | Custom Event Handlers |
| Agent Prompting | [API_EXAMPLES.md](API_EXAMPLES.md) | Agent Prompting Examples |
| State Queries | [API_EXAMPLES.md](API_EXAMPLES.md) | State Queries |
| Testing | [API_EXAMPLES.md](API_EXAMPLES.md) | Testing Examples |
| Production Patterns | [API_EXAMPLES.md](API_EXAMPLES.md) | Production Patterns |

### Operations

| Topic | Document | Section |
|-------|----------|---------|
| Running the Agent | [QUICK_START.md](QUICK_START.md) | Quick Commands |
| Monitoring | [QUICK_START.md](QUICK_START.md) | Monitoring |
| Troubleshooting | [README.md](../README.md) | Troubleshooting |
| Debugging | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) | Debugging Tips |

---

## 🎯 Learning Paths

### Path 1: Beginner (Just Want It Running)

1. ✅ [QUICK_START.md](QUICK_START.md) - Get it running
2. ✅ [README.md](../README.md) - Understand basics
3. ✅ [QUICK_START.md#monitoring](QUICK_START.md#monitoring-your-agent) - Watch it work

**Time**: ~15 minutes

### Path 2: Developer (Want to Customize)

1. ✅ [README.md](../README.md) - Full overview
2. ✅ [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) - Architecture deep dive
3. ✅ [API_EXAMPLES.md](API_EXAMPLES.md) - Code patterns
4. ✅ Source code in `src/`

**Time**: ~1 hour

### Path 3: Competitor (Want to Win)

1. ✅ [istruzioni.md](istruzioni.md) - Learn game rules
2. ✅ [README.md#game-phases](../README.md#game-phases) - Understand phases
3. ✅ [API_EXAMPLES.md#agent-prompting](API_EXAMPLES.md#agent-prompting-examples) - Optimize strategy
4. ✅ [README.md#key-insights](../README.md#key-insights) - Strategy tips

**Time**: ~1 hour

### Path 4: Debugger (Something's Wrong)

1. ✅ [README.md#troubleshooting](../README.md#troubleshooting) - Common issues
2. ✅ [QUICK_START.md#common-issues](QUICK_START.md#common-issues) - Quick fixes
3. ✅ [TECHNICAL_DOCS.md#debugging-tips](TECHNICAL_DOCS.md#debugging-tips) - Advanced debugging
4. ✅ [API_EXAMPLES.md#debugging-helpers](API_EXAMPLES.md#debugging-helpers) - Debug tools

**Time**: ~30 minutes

---

## 📝 Document Descriptions

### [README.md](../README.md)
**Main documentation** covering:
- Project overview and architecture
- Component descriptions
- Setup instructions
- Game phase explanations
- Event flow diagrams
- API reference
- Troubleshooting guide
- Strategy tips

**Audience**: Everyone  
**Length**: ~20 min read

### [QUICK_START.md](QUICK_START.md)
**Fast-track guide** for:
- 5-minute setup
- Configuration quick reference
- Common commands
- Phase cheat sheet
- Monitoring tips

**Audience**: Beginners, impatient developers  
**Length**: ~5 min read

### [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)
**Deep technical dive** covering:
- Concurrency model
- State management patterns
- Error handling strategies
- SSE connection details
- Agent pipeline internals
- Performance considerations
- Design decisions

**Audience**: Developers, contributors  
**Length**: ~30 min read

### [API_EXAMPLES.md](API_EXAMPLES.md)
**Practical cookbook** with:
- REST API usage examples
- Custom event handlers
- Agent prompting patterns
- State queries
- Testing strategies
- Production patterns
- Debugging helpers

**Audience**: Developers customizing the system  
**Length**: ~45 min read (browse as needed)

### [istruzioni.md](istruzioni.md)
**Game rules** (Italian) including:
- Competition overview
- Game mechanics
- Turn structure
- Scoring system
- Constraints and rules

**Audience**: Competitors  
**Length**: ~45 min read (Italian required)

---

## 🔍 Search by Keyword

### Authentication
- Setup: [QUICK_START.md](QUICK_START.md#2-configure-environment-1-min)
- Details: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#authentication)

### Agent
- Overview: [README.md](../README.md#srcagentpy)
- Prompting: [API_EXAMPLES.md](API_EXAMPLES.md#agent-prompting-examples)
- Pipeline: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#agent-decision-pipeline)

### Asyncio
- Model: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#concurrency-model)
- Examples: [API_EXAMPLES.md](API_EXAMPLES.md#custom-event-handlers)

### Balance
- Tracking: [README.md](../README.md#srcstatepy)
- Queries: [API_EXAMPLES.md](API_EXAMPLES.md#check-if-we-can-afford-something)

### Bidding
- Phase: [README.md](../README.md#2-closed-bid-phase)
- Strategy: [API_EXAMPLES.md](API_EXAMPLES.md#strategic-phase-specific-prompts)

### Clients
- Handling: [README.md](../README.md#4-serving-phase)
- Events: [README.md](../README.md#event-flow)
- Custom logic: [API_EXAMPLES.md](API_EXAMPLES.md#context-aware-client-handling)

### Configuration
- Quick: [QUICK_START.md](QUICK_START.md#2-configure-environment-1-min)
- Full: [README.md](../README.md#configuration)
- Details: [README.md](../README.md#srcconfigpy)

### Debugging
- Quick tips: [QUICK_START.md](QUICK_START.md#common-issues)
- Advanced: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#debugging-tips)
- Tools: [API_EXAMPLES.md](API_EXAMPLES.md#debugging-helpers)

### Events
- Types: [README.md](../README.md#event-types)
- Flow: [README.md](../README.md#event-flow-diagram)
- Custom handlers: [API_EXAMPLES.md](API_EXAMPLES.md#custom-event-handlers)

### Ingredients
- Expiry rules: [README.md](../README.md#ingredients-expiring)
- Management: [API_EXAMPLES.md](API_EXAMPLES.md#inventory-analysis)

### Inventory
- State tracking: [README.md](../README.md#srcstatepy)
- Analysis: [API_EXAMPLES.md](API_EXAMPLES.md#inventory-analysis)

### Intolerances
- Critical checks: [README.md](../README.md#4-serving-phase)
- Handling: [API_EXAMPLES.md](API_EXAMPLES.md#context-aware-client-handling)

### MCP Tools
- Overview: [README.md](../README.md#mcp-tools)
- Integration: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#mcp-tool-integration)

### Market
- Phase: [README.md](../README.md#3-waiting-phase)
- API: [API_EXAMPLES.md](API_EXAMPLES.md#query-market-entries)

### Menu
- Setting: [README.md](../README.md#1-speaking-phase)
- API: [API_EXAMPLES.md](API_EXAMPLES.md#check-menu-and-pricing)

### Phases
- Overview: [README.md](../README.md#game-phases)
- Cheat sheet: [QUICK_START.md](QUICK_START.md#game-phases-cheat-sheet)
- Strategy: [API_EXAMPLES.md](API_EXAMPLES.md#strategic-phase-specific-prompts)

### Recipes
- Loading: [README.md](../README.md#srcmainpy)
- API: [API_EXAMPLES.md](API_EXAMPLES.md#list-all-available-recipes)
- Queries: [API_EXAMPLES.md](API_EXAMPLES.md#find-recipes-we-can-make)

### SSE
- Overview: [README.md](../README.md#srcssepy)
- Deep dive: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#sse-connection-management)
- 409 Errors: [QUICK_START.md](QUICK_START.md#sse-409-conflict)

### State
- Management: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#state-management)
- Queries: [API_EXAMPLES.md](API_EXAMPLES.md#state-queries)

### Testing
- Examples: [API_EXAMPLES.md](API_EXAMPLES.md#testing-examples)
- Strategies: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md#testing-strategies)

### Troubleshooting
- Quick: [QUICK_START.md](QUICK_START.md#common-issues)
- Full: [README.md](../README.md#troubleshooting)

---

## 🛠️ Code References

### Main Entry Points
- [run.py](../run.py) - Start here
- [src/main.py](../src/main.py) - Main event loop

### Core Components
- [src/agent.py](../src/agent.py) - AI agent setup
- [src/sse.py](../src/sse.py) - Event listener
- [src/state.py](../src/state.py) - State tracker
- [src/api.py](../src/api.py) - REST client
- [src/config.py](../src/config.py) - Configuration

---

## 📊 Quick Stats

- **Total documentation**: ~15,000 words
- **Code examples**: 50+
- **Diagrams**: 3
- **Topics covered**: 40+

---

## 🤝 Contributing

Found an error or want to improve the docs?

1. Document is out of date → File an issue
2. Want to add examples → Submit a PR
3. Found a typo → Quick fix PR welcome

---

## 📞 Getting Help

**Still stuck?** Follow this escalation:

1. ✅ Search this index for your topic
2. ✅ Read the relevant documentation
3. ✅ Check [troubleshooting guides](../README.md#troubleshooting)
4. ✅ Review [code examples](API_EXAMPLES.md)
5. ✅ Consult your team
6. ✅ Ask competition organizers

---

**Happy coding! May your restaurant prosper! 🍕🚀**

*Last Updated: 2026-02-28*
