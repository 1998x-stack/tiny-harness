# Spec: tiny-harness MVP

**Date**: 2026-05-16
**Status**: Draft
**References**: CONTEXT.md, docs/adr/0001-0003, docs/tools/, docs/agent-loop/, docs/message-manager/, docs/config/, docs/llm-provider/, docs/filesystem/, docs/cli.md, docs/skills.md, docs/code-style.md

---

## 1. Purpose

`tiny-harness` is a minimal Python package (~1,400 lines) that wraps an LLM into an AI agent — giving it tools, a conversation loop, and a streaming CLI session. One import: `from tiny_harness import Agent`.

## 2. Scope

### In Scope

| Subsystem | What |
|---|---|
| Agent Core (`_core.py`) | Orchestrator, session management, `run()`/`run_stream()`, skill loading |
| Agent Loop (`_loop.py`) | While-loop state machine, error budget, loop detection, degraded finish |
| Message Manager (`_messages.py`) | Conversation array, token counting, context warnings |
| LLM Provider (`_llm.py`) | Anthropic API via raw HTTP + SSE, retry with backoff |
| Tool System (`_tools.py`) | Registry, executor, minimal JSON Schema validator |
| Config + Prompt (`_config.py`) | AgentConfig, Prompt dataclasses |
| Events (`_events.py`) | StreamEvent types, EventBus |
| Path Safety (`_guard.py`) | FilesystemGuard, workspace boundary enforcement |
| File Tools (`tools/files.py`) | read_file, write_file, list_directory, find_files, delete_file, create_directory, move_file |
| Skills (`skills/files.py`) | Built-in "files" skill: `register(agent)` |
| CLI (`cli.py`) | Session REPL, one-shot mode, metadata-rich streaming |

### Out of Scope (MVP)

- Multi-model routing (single Anthropic provider)
- MCP servers (future skill source)
- Shell tools, search tools (separate skills, post-MVP)
- Third-party skill loading (`tiny-harness-skill-*` packages)
- TUI, config files (TOML), plugin discovery
- Context compaction, memory persistence
- Sub-agent spawning, task planning
- Container sandboxing, OS-level isolation
- Circuit breaker, multi-provider fallback

## 3. Architecture

### 3.1 Package Layout

```
tiny_harness/
├── __init__.py                 # Public API: Agent, Prompt, Config, ToolDef (not Tool)
├── _core.py                    # Agent class — orchestrator, session management
├── _loop.py                    # AgentLoop — while-loop state machine
├── _messages.py                # MessageManager — Conversation + token counting
├── _llm.py                     # LLMProvider ABC + AnthropicProvider
├── _config.py                  # AgentConfig, Prompt
├── _tools.py                   # ToolRegistry + ToolExecutor + minimal validator
├── _events.py                  # StreamEvent + EventBus
├── _guard.py                   # FilesystemGuard — path resolution + boundary checks
├── tools/
│   ├── __init__.py
│   └── files.py                # File operation tool handlers
├── skills/
│   ├── __init__.py
│   └── files.py                # register(agent) → file tools + prompt section
└── cli.py                      # CLI entry point
```

### 3.2 Module Dependencies (no cycles)

```
cli.py
  └── _core.py (Agent)
        ├── _loop.py (AgentLoop)
        │     ├── _llm.py (LLMProvider)
        │     └── _tools.py (ToolRegistry, ToolExecutor)
        ├── _messages.py (MessageManager)
        ├── _config.py (AgentConfig, Prompt)
        └── _events.py (StreamEvent, EventBus)

tools/files.py                  # depends on _guard.py only
skills/files.py                 # imports tools/files.py, registers on Agent
_guard.py                       # no internal dependencies
```

### 3.3 Data Flow

```
User prompt
  │
  ▼
Agent.run(prompt)
  ├─ MessageManager.add_user(prompt)
  └─ AgentLoop.run(messages, tools)
       │
       ├─ LLMProvider.generate_stream(messages, tool_defs)
       │     ├─ HTTP POST to Anthropic /v1/messages
       │     ├─ SSE stream parsed → LLMStreamChunk
       │     └─ Emit StreamEvent("text_delta") → EventBus → user
       │
       ├─ Parse ToolCallRequest[] from stream
       │
       ├─ For each tool_call:
       │     ├─ LoopDetector.check(name, args)
       │     ├─ ToolExecutor.execute(name, args, call_id)
       │     │     ├─ lookup → validate schema → guard.check → handler(**args)
       │     │     └─ Return ToolResult (success or error)
       │     ├─ ErrorBudget.record_error/success()
       │     ├─ Emit StreamEvent("tool_start"/"tool_end")
       │     └─ MessageManager.add_tool_result(result)
       │
       └─ Loop back to LLM call with updated messages
            ...until final answer or safety limit
```

## 4. Component Specifications

### 4.1 Config + Prompt (`_config.py`, `_events.py`, `_guard.py`)

**AgentConfig** — dataclass
- `model: str` — model identifier
- `api_key: str` — Anthropic API key
- `workspace: str` — root directory boundary
- `max_iterations: int = 25`
- `max_errors: int = 10`
- `max_consecutive_errors: int = 3`
- `timeout_ms: int = 30_000`
- `max_tool_result_chars: int = 50_000`

**Prompt** — class
- `__init__(base: str)` — base system prompt
- `append(section: str) -> None` — skills add sections
- `to_string() -> str` — joined with `\n\n`

**StreamEvent** — frozen dataclass
- `type: str` — "text_delta" | "tool_start" | "tool_end" | "iteration" | "error"
- `content: str | None`, `tool_name: str | None`, `duration_ms: int | None`
- `num: int | None`, `max: int | None`, `message: str | None`

**EventBus** — async pub/sub
- `subscribe(handler: Callable) -> None`
- `async emit(event: StreamEvent) -> None`

**FilesystemGuard**
- `__init__(workspace: str)`
- `resolve(path: str) -> str` — normalize + resolve symlinks to canonical path
- `guard(path: str, operation: str) -> str` — resolve → boundary check → return safe path
- Raises `PathAccessError` on violation (good error message for LLM)

### 4.2 LLM Provider (`_llm.py`)

**LLMProvider** — ABC
- `async generate(messages: list[dict], tools: list[dict] | None) -> LLMResponse`
- `async generate_stream(...) -> AsyncIterator[LLMStreamChunk]`

**AnthropicProvider** — concrete
- HTTP POST to `https://api.anthropic.com/v1/messages`
- Headers: `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`
- Request body: `{model, max_tokens, messages, system, tools, stream: true}`
- SSE parsing: `event: content_block_start/delta/stop`, `event: message_start/delta/stop`
- Converts Anthropic SSE events to uniform `LLMStreamChunk` types
- Retry: 3 attempts, exponential backoff (1s→2s→4s) with jitter
- Retryable: 429, 5xx, 529, network errors
- Fatal: 401, 403, 400 (context overflow)
- Dependency: `httpx` (async HTTP client)

**LLMResponse** — dataclass
- `text: str | None`
- `tool_calls: list[ToolCallRequest]`
- `usage: TokenUsage`
- `finish_reason: str`
- `is_final() -> bool` — True if no tool_calls

**ToolCallRequest** — dataclass: `id: str, name: str, arguments: dict`

**TokenUsage** — dataclass: `input_tokens: int, output_tokens: int`

**LLMStreamChunk** — dataclass: `type: str, content: str | None, tool_call: ToolCallRequest | None`

### 4.3 Message Manager (`_messages.py`)

**MessageManager**
- `__init__(prompt: Prompt)` — initializes with system message from prompt
- `add_user(content: str) -> None`
- `add_assistant(text: str | None, tool_calls: list | None) -> None`
- `add_tool_result(tool_call_id: str, content: str) -> None`
- `add_system_notice(notice: str) -> None` — injects as user message with `[System Notice]` prefix
- `to_list() -> list[dict]`
- `estimate_tokens() -> int` — approximate: `sum(len(json.dumps(m)) // 4 for m in messages)`. Not exact model tokenizer; good enough for warnings with 200K context window margin.
- `check_context() -> TokenStatus` — OK | NEAR_CAPACITY (>80%, approximate) | OVER_CAPACITY
- `clear() -> None` — reset conversation, keep prompt

**TokenBudget** — `check(messages) -> TokenStatus`

**Message array invariant**: system[0] → user[1] → [assistant → tool_result*]* → assistant(final). Tool results must reference valid `tool_call_id` from the preceding assistant message.

### 4.4 Tool System (`_tools.py`)

**ToolDef** — dataclass: `name: str, description: str, parameters: dict, risk_level: str = "read_only"`

**Tool** — dataclass: `definition: ToolDef, handler: Callable`

**ToolRegistry**
- `register_from_def(def: ToolDef, handler: Callable) -> None` — primary user-facing API
- `register(tool: Tool) -> None` — internal (pre-constructed Tool)
- `get(name: str) -> Tool | None`
- `get_definitions() -> list[dict]` — LLM-compatible `{name, description, input_schema}`
- `names() -> list[str]`

**ToolExecutor**
- `__init__(registry, guard, timeout_ms, max_output_chars)`
- `async execute(name: str, args: dict, call_id: str) -> ToolResult`
- Pipeline: lookup → validate schema → guard.check → execute with timeout → format → truncate
- Schema validation: minimal validator (~50 lines) supporting `type`, `required`, `properties`, `enum`, `default`, nested objects up to 2 levels
- Semantic validation (path exists? URL reachable?) is NOT done here — delegated to the handler. Handler catches errors and returns them; executor converts exceptions to ToolResult.error()
- Timeout via `asyncio.wait_for`
- All exceptions caught → converted to `ToolResult.error()`

**ToolResult** — dataclass
- `success: bool, tool_call_id: str, content: str`
- `@classmethod ok(call_id, content) -> ToolResult`
- `@classmethod error(call_id, message) -> ToolResult`

### 4.5 Agent Loop (`_loop.py`)

**AgentLoop** — while-loop state machine
- `__init__(config, messages, llm, tools, events)`
- `async run(user_prompt: str) -> str`

Phases per iteration:
1. Emit iteration event (num, max, token estimate)
2. `llm.generate_stream()` → emit text_delta events → collect tool_calls
3. If no tool_calls → return accumulated text (final answer)
4. `messages.add_assistant(text, tool_calls)`
5. For each tool_call: loop detector → executor → error budget → events → add tool_result
6. If error budget exhausted → degraded finish
7. If context > 80% → emit warning
8. Loop continues

Safety valves:
- Max iterations: inject notice, ask LLM for final answer without tools
- Error budget: 10 total / 3 consecutive → degraded finish
- Loop detection: 3 identical failing calls → warn LLM

**ErrorBudget**: `record_error() -> bool`, `record_success() -> None`

**LoopDetector**: `check(tool_name, args) -> bool`

Events emitted: `iteration`, `text_delta`, `tool_start`, `tool_end`, `error`

Edge cases handled:
- Empty LLM response (zero text, zero tool calls): treated as error, emit error event, continue loop
- Concurrent `run()` / `run_stream()` calls: raise RuntimeError (not supported)
- Loop state resets per `run()` call (error budget, loop detector, iteration counter)
- `clear()` resets both Conversation and loop state (tools/config/prompt/LLM connection persist)

### 4.6 Agent Core (`_core.py`)

**Agent** — sole user-facing class
- `__init__(prompt: Prompt, config: AgentConfig)`
- Creates all components at init (no lazy loading, no API validation at init — auth errors surface on first `run()`)

Properties/Methods:
- `tools: ToolRegistry` — `agent.tools.register_from_def(tool_def, handler)`
- `load_skill(skill_ref: str) -> None` — resolves ref, calls `skill.register(self)`
- `async run(prompt: str) -> str` — session-scoped (appends to Conversation; resets loop state per call)
- `async run_stream(prompt: str) -> AsyncIterator[StreamEvent]` — raises RuntimeError if called concurrently
- `clear() -> None` — reset Conversation AND loop state (error budget, detectors); keep tools/config/prompt
- `events: EventBus` — `agent.events.subscribe(handler)`
- `on(event_type: str, handler) -> None` — shorthand subscription

Session model: Agent is session-scoped. Multiple `run()` calls append to same Conversation but reset loop state (error budget, loop detector, iteration counter) per call. `clear()` resets both Conversation and loop state.

### 4.7 File Tools (`tools/files.py`)

Seven tool handlers, each: `ToolDef + async (args: dict) -> str`

| Tool | Operation | Guard Level |
|---|---|---|
| `read_file(path, offset=1, limit=None)` | Read file with line range | read |
| `write_file(path, content)` | Create/overwrite, auto-create parents | write |
| `list_directory(path=".", pattern=None, recursive=False)` | List entries with sizes | read |
| `find_files(pattern, path=".", max_results=200)` | Glob search | read |
| `delete_file(path)` | Permanent delete | delete |
| `create_directory(path)` | mkdir -p | write |
| `move_file(source, destination)` | Rename/move | read+write |

All handlers: guard path → operate → format result → truncate at max_chars.

### 4.8 Skills (`skills/files.py`)

```python
def register(agent: Agent) -> None:
    # Register all 7 file tools
    # Append FILES_PROMPT_SECTION to agent prompt
```

Prompt section: tool descriptions + usage guidelines + safety rules.

### 4.9 CLI (`cli.py`)

Entry point: `tiny-harness [prompt] [--model X] [--workspace Y] [--skills a,b]`

- No prompt arg: Session REPL (banner → input loop → stream events)
- Prompt arg: One-shot mode (stream events, exit)

Session commands: `/exit`, `/help`, `/tools`, `/clear`, `/stats`, `/save`

Streaming renderer:
```
[Iter N/M | Tokens: used/limit]          ← iteration event
Let me create that file.                   ← text_delta
  ⚡ write_file  path=hello.py content=...  ← tool_start
  ⚡ write_file  (Created, 22B, 3ms)       ← tool_end
Done!                                      ← text_delta (final)
```

Dependencies: stdlib only (`asyncio`, `sys`, `os`). `async_input` via `asyncio.to_thread(sys.stdin.readline)`.

## 5. Dependencies

### Required
- `httpx >= 0.27.0` — async HTTP client for Anthropic API

### Dev
- `pytest >= 8.0.0` — testing
- `pytest-asyncio >= 0.23.0` — async test support

### Zero additional runtime deps
JSON Schema validation, SSE parsing, and CLI are all implemented in-package (~50 lines each).

## 6. Implementation Phases

| Phase | Deliverable | Lines | Verification |
|---|---|---|---|
| P1 | `_config.py`, `_events.py`, `_guard.py` | ~180 | Import, create, print |
| P2 | `_llm.py` | ~180 | `provider.generate([user_msg])` → text |
| P3 | `_messages.py` | ~150 | Build messages, estimate tokens |
| P4 | `_tools.py` | ~180 | Register tool, execute, get result |
| P5 | `_loop.py` | ~130 | Mock LLM+tools → loop completes |
| P6 | `_core.py` (+ `__init__.py`) | ~150 | `agent.run("Hi")` → string |
| P7 | `tools/files.py`, `skills/files.py` | ~260 | `agent.run("Create hello.py")` → file exists |
| P8 | `cli.py` | ~150 | `tiny-harness "Create hello.py"` → streams, creates file |

**Total**: ~1,380 lines. Dependencies: P1→P2→P3→P4→P5→P6→(P7∥P8).

## 7. Success Criteria

| # | Criterion | Phase |
|---|---|---|
| 1 | Accept a prompt, call LLM, return response text | P2 |
| 2 | Stream LLM output in real time (SSE parsed correctly) | P2 |
| 3 | Messages in correct order (system → user → assistant → tool) | P3 |
| 4 | Warn when conversation >80% of context limit | P3 |
| 5 | Register tools, validate args against JSON Schema, execute | P4 |
| 6 | Return tool errors as structured results (not crashes) | P4 |
| 7 | LLM self-corrects after tool errors (reads error, retries) | P5 |
| 8 | Terminate gracefully at max iterations (final answer without tools) | P5 |
| 9 | Terminate when error budget exhausted (10 total / 3 consecutive) | P5 |
| 10 | Detect repeated identical failing tool calls, warn LLM | P5 |
| 11 | Read/write files within workspace boundary | P7 |
| 12 | Reject file operations outside workspace (PathGuard) | P7 |
| 13 | `agent.load_skill("files")` registers tools + augments prompt | P7 |
| 14 | CLI session: input box → streaming output → multiple prompts | P8 |
| 15 | CLI one-shot: `tiny-harness "prompt"` → streams, exits | P8 |
| 16 | Ctrl+C returns partial results gracefully | P8 |

## 8. Non-Functional Requirements

- **Python**: 3.11+ (uses `match/case`, `asyncio`, `dataclasses`)
- **Type hints**: All public functions and dataclass fields
- **Async**: All I/O operations are async; pure computation is sync
- **Error handling**: No bare `except:`; no `pass` in except blocks
- **File size**: No module exceeds 300 lines
- **Naming**: `snake_case` modules/functions, `PascalCase` classes, `_prefix` for internal modules

## 9. Testing Approach

- **Unit tests per module**: `tests/test_config.py`, `tests/test_messages.py`, `tests/test_tools.py`, etc.
- **Mock LLM provider** for deterministic loop testing: `MockLLMProvider` returns pre-programmed responses (text, tool calls, errors).
- **Mock tool handlers** for executor testing: verify that args are validated, results are formatted, errors are caught.
- **Integration test**: `agent.run("Create hello.py")` with real Anthropic API (requires API key environment variable; skipped in CI).
- **CLI smoke test**: `python -m tiny_harness.cli "Say hi"` exits 0, produces output.
- **Test runner**: `pytest` with `pytest-asyncio` for async test functions.
- **Coverage target**: >80% on agent core modules (not on I/O-heavy tools/files.py or cli.py).

## 10. Provider-Specific Notes

- **Anthropic API**: Uses separate `system` parameter (not a message role). The `AnthropicProvider` extracts the first system-role message from the messages array and passes it as `system`. Non-system messages are passed as `messages`.
- **Message format**: Anthropic uses `content: [{type: "text", text: "..."}, {type: "tool_use", ...}]` (content blocks). The provider converts between our flat format and Anthropic's block format.
- **SSE event types**: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`. Tool calls arrive as `content_block_start` (type: `tool_use`) with name, then `content_block_delta` with partial JSON arguments, then `content_block_stop`.
