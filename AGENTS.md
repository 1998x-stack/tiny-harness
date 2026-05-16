# AGENTS.md

## Setup

```bash
pip install -e ".[dev]"
```

### Running tests
```bash
# All unit tests (excludes integration tests needing API keys)
pytest tests/ --ignore=tests/test_integration.py

# Single test file
pytest tests/test_tools.py -v

# Single test
pytest tests/test_tools.py::test_execute_tool_timeout -v

# Integration tests (needs ANTHROPIC_API_KEY or DEEPSEEK_API_KEY)
pytest tests/test_integration.py -v -m integration

# Run the agent CLI
python -m tiny_harness "hello"
python -m tiny_harness --tui --skills files
```

### Lint
```bash
ruff check tiny_harness/ tests/
ruff check --fix tiny_harness/ tests/
```

---

## Architecture

**Public API** (`tiny_harness/__init__.py`): `Agent`, `Prompt`, `Config`, `ToolDef`

**Module dependency order** (no cycles):
```
_config.py → _events.py → _guard.py → _llm.py → _messages.py → _tools.py → _loop.py → _core.py
   ↑                                                                                    │
   └─── cli.py, tui.py import only _core.py (never modules directly) ───────────────────┘
```

- `_core.py` (117 lines) — Agent class, the only integrator. Creates all components at `__init__`. Never add new cross-module wiring elsewhere.
- `_loop.py` (109 lines) — AgentLoop state machine. Zero intelligence: calls LLM, executes tools, loops. Never add planning logic here.
- `_llm.py` (341 lines) — All provider code (AnthropicProvider + OpenAIProvider + types). If adding a new provider, match the `LLMProvider` ABC.
- `tools/` and `skills/` — each is standalone. `tools/` has handlers (`def my_tool(args: dict) -> str`). `skills/` has `register(agent)` that wires tools + prompt sections together.

---

## Domain terms (see CONTEXT.md for full glossary)

| Term | Meaning |
|---|---|
| Agent | The whole runtime. Created, given tasks, discarded. |
| Agent Core | Loop + Messages + Config + LLMProvider + empty ToolRegistry. Zero tools built in. |
| Tool | External plugin registered into ToolRegistry. Handler signature: `def handler(args: dict) -> str`. |
| Prompt | First-class artifact, separate from `Config`. `Prompt("base").append("section")`. |
| Skill | `register(agent)` function that registers tools + appends prompt instructions. |
| Conversation | The message array — the Agent's memory. Owned by MessageManager. |
| Session | Multiple `run()` calls sharing one Conversation. `clear()` resets it. |

---

## Gotchas (see docs/gotchas.md for full list)

1. **Tool handlers take `args: dict`, NOT `**kwargs`.** The ToolExecutor calls `handler(args)`. Writing `def handler(path: str)` will fail with "unexpected keyword argument."

2. **AgentLoop must send tool definitions.** `ToolExecutor.get_definitions()` is called every iteration. Mocks must implement it.

3. **DeepSeek v4 models fail on iteration 2.** `deepseek-v4-flash` requires `reasoning_content` passthrough. Use `deepseek-chat` for tool calling.

4. **OpenAI/DeepSeek streaming tool calls are buffered.** `OpenAIProvider.generate_stream()` accumulates JSON deltas and emits complete `ToolCallRequest` at `tool_call_end`.

5. **Prompt is NOT a Config field.** `Agent(prompt=Prompt(...), config=Config(...))` — two separate arguments since ADR 002.

6. **Conversation accumulates across `run()` calls** within a session. Use `agent.clear()` to reset.

7. **`register_from_def(def, handler)` is the user-facing API.** `register(Tool(...))` is internal.

8. **Skills are resolved as:** `tiny_harness.skills.{name}` → direct import → file path. Loading same skill twice is a no-op.

---

## Code conventions

- Python 3.11+, async/await for I/O, dataclasses for data
- `_prefix` on internal modules, no prefix on public (`_core.py` vs `cli.py`)
- Functions over classes. Classes only when bundling state + behavior.
- No module exceeds 350 lines. `_llm.py` (341) is the largest.
- TDD: write test first (assert on behavior), run to see fail, implement, run to pass, commit.
- Tests in `tests/` mirror source. Test file per module: `tests/test_tools.py` tests `_tools.py`.
- Mock LLM providers for deterministic loop tests. See `FakeProvider` in `tests/test_loop.py`.

---

## Key files

| File | What it does |
|---|---|
| `tiny_harness/__init__.py` | Public exports |
| `tiny_harness/_core.py` | Agent class — orchestrator |
| `tiny_harness/_loop.py` | AgentLoop — while-loop state machine |
| `tiny_harness/_llm.py` | All LLM providers + types |
| `tiny_harness/_tools.py` | ToolRegistry, ToolExecutor, schema validator, ToolResult |
| `tiny_harness/_messages.py` | MessageManager, TokenBudget |
| `tiny_harness/_config.py` | AgentConfig, Prompt |
| `tiny_harness/_events.py` | StreamEvent, EventBus |
| `tiny_harness/_guard.py` | FilesystemGuard |
| `tiny_harness/cli.py` | CLI entry point |
| `tiny_harness/tui.py` | Rich TUI mode |
| `tiny_harness/tools/files.py` | File tool handlers (7 tools) |
| `tiny_harness/tools/search.py` | Code search tool |
| `tiny_harness/tools/shell.py` | Shell command tool |
| `tiny_harness/skills/files.py` | File skill (tools + prompt) |
| `tiny_harness/skills/search.py` | Search skill |
| `tiny_harness/skills/shell.py` | Shell skill |
