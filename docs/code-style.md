# Code Style & Architecture

## 1. CleanRL Philosophy Applied

CleanRL's principles, adapted for an agent harness:

| CleanRL Principle | Applied Here |
|---|---|
| Single-file readability | Package with clean `__init__.py` re-exports so users see one surface |
| Functions over classes | Functions for stateless operations; classes only when bundling state + behavior |
| Dataclasses for config | `Config`, `Prompt`, `ToolDef` are plain dataclasses |
| No framework — just code | `from tiny_harness import Agent` — no decorators, no DI containers |
| Explicit data flow | Arguments passed explicitly; no hidden globals, no service locators |
| Research-friendly | Easy to fork, modify, experiment. Read the source, understand it. |

The test: can a new contributor read `tiny_harness/__init__.py` and the first 100 lines of `_core.py` and understand the entire architecture?

## 2. Package Layout

```
tiny_harness/
├── __init__.py              # Public API: Agent, Prompt, Config, Tool
├── _core.py                 # Agent class (orchestrator)
├── _loop.py                 # AgentLoop state machine
├── _messages.py             # MessageManager
├── _llm.py                  # LLMProvider + AnthropicProvider
├── _config.py               # AgentConfig, Prompt, ToolDef
├── _tools.py                # ToolRegistry, ToolExecutor
├── _events.py               # Event types, EventBus
├── _guard.py                # FilesystemGuard
├── cli.py                   # CLI entry point (separate from core)
│
├── tools/                   # Tool implementations (not auto-loaded)
│   ├── __init__.py
│   ├── files.py             # read_file, write_file, list_directory, etc.
│   ├── shell.py             # run_command
│   └── search.py            # search_code, search_files
│
└── skills/                  # Built-in skills (bundled, not auto-loaded)
    ├── __init__.py
    ├── files.py             # register(agent) → file tools + prompt
    ├── shell.py             # register(agent) → shell tools + prompt
    └── search.py            # register(agent) → search tools + prompt
```

**Rule**: `_prefix` = internal module (not imported directly by users). No prefix = public (part of the API surface).

### Public API (`__init__.py`)

```python
# tiny_harness/__init__.py
from tiny_harness._core import Agent
from tiny_harness._config import Prompt, Config
from tiny_harness._tools import ToolDef, Tool

__all__ = ["Agent", "Prompt", "Config", "ToolDef", "Tool"]
```

Users only import from `tiny_harness`:
```python
from tiny_harness import Agent, Prompt, Config
```

## 3. Coding Conventions

### 3.1 Python Version

Python 3.11+. Use modern features:
- `match`/`case` for event handling and state machines
- `async`/`await` for all I/O (LLM calls, file ops, subprocess)
- `dataclasses` for data containers
- Type hints everywhere (strict mode compatible)

### 3.2 Functions > Classes

```python
# GOOD: Plain function for stateless operation
def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated]"

# GOOD: Class only when bundling state + behavior
class MessageManager:
    def __init__(self, system_prompt: str):
        self.messages: list[dict] = []

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

# AVOID: Class with only static methods (just use functions)
# AVOID: Inheritance hierarchies (ABC for interfaces is fine)
```

### 3.3 Dataclasses for Data

```python
# Configuration, definitions, results — all dataclasses
@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-20250514"
    max_iterations: int = 25
    context_limit: int = 200_000

@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict

# NOT: classes with __init__ and __repr__ (use dataclass)
# NOT: dicts with string keys for structured data (use dataclass)
```

### 3.4 Explicit Dependencies

```python
# GOOD: Pass dependencies explicitly
class Agent:
    def __init__(self, prompt: Prompt, config: AgentConfig):
        self.config = config
        self.messages = MessageManager(prompt)
        self.tools = ToolRegistry()
        self.llm = AnthropicProvider(config)

# AVOID: Global state, singletons, service locators
# AVOID: _global_agent = None; def get_agent(): ...
```

### 3.5 Async Where It Counts

```python
# Async: I/O-bound operations
async def generate(self, messages, tools) -> LLMResponse: ...
async def execute(self, tool_name, args) -> ToolResult: ...
async def run(self, prompt: str) -> str: ...

# Sync: Pure computation, data transformation
def format_result(raw: Any) -> str: ...
def estimate_tokens(text: str) -> int: ...
def resolve_path(path: str, cwd: str) -> str: ...
```

### 3.6 Type Hints

```python
# Always annotate function signatures
async def run(self, prompt: str) -> str: ...

# Use modern syntax (Python 3.10+)
def get(self, name: str) -> Tool | None: ...
def register(self, tool: Tool) -> None: ...

# Dataclass fields are typed
@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCallRequest]
    usage: TokenUsage
```

### 3.7 Naming

```python
# Modules: snake_case, _prefix for internal
_core.py, _loop.py, _messages.py

# Classes: PascalCase
Agent, MessageManager, ToolRegistry

# Functions/methods: snake_case, verb-first
register_tool(), add_user(), estimate_tokens()

# Constants: UPPER_SNAKE_CASE
MAX_TOOL_RESULT_CHARS = 50_000
DEFAULT_TIMEOUT_MS = 30_000
```

## 4. Interface Design Patterns

### 4.1 The Agent Surface

```python
class Agent:
    """The complete runtime system. The only user-facing entry point."""

    def __init__(self, prompt: Prompt, config: AgentConfig):
        ...

    # --- Tool Management ---
    @property
    def tools(self) -> ToolRegistry:
        """The tool registry. Use agent.tools.register(...) to add tools."""
        ...

    # --- Skill Loading ---
    def load_skill(self, skill_ref: str) -> None:
        """Load a skill by name, path, or module reference."""
        ...

    # --- Execution ---
    async def run(self, prompt: str) -> str:
        """Run a single prompt within the current session. Returns final answer."""
        ...

    async def run_stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Run a single prompt, yielding events as they occur."""
        ...

    # --- Session ---
    def clear(self) -> None:
        """Reset the conversation (keep tools, prompt, config)."""
        ...
```

### 4.2 Immutable Where Possible

```python
@dataclass(frozen=True)
class StreamEvent:
    type: str
    content: str | None = None
    tool_name: str | None = None
    ...

@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
```

### 4.3 Result Types Over Exceptions

```python
# Tool system: return structured results, don't throw
@dataclass
class ToolResult:
    success: bool
    content: str
    tool_call_id: str

    @classmethod
    def ok(cls, call_id: str, content: str) -> "ToolResult":
        return cls(success=True, content=content, tool_call_id=call_id)

    @classmethod
    def error(cls, call_id: str, message: str) -> "ToolResult":
        return cls(success=False, content=message, tool_call_id=call_id)


# Agent: return result, don't throw (except for fatal errors)
async def run(self, prompt: str) -> str:
    """Returns final answer string. Raises only for fatal/system errors."""
    ...

# Fatal errors: raise exceptions
class FatalAgentError(Exception):
    """The agent cannot continue. Auth failure, model unavailable, harness bug."""
    ...
```

## 5. Extensibility Rules

### 5.1 Adding a Tool

```python
# 1. Define the tool
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict

# 2. Write the handler
async def my_tool(args: dict) -> str: ...

# 3. Register
agent.tools.register(ToolDef(...), my_tool)
```

No base classes, no decorators, no YAML config for tool definitions. Pure Python.

### 5.2 Creating a Skill

```python
# my_skill.py
def register(agent: Agent):
    agent.tools.register(tool_a)
    agent.tools.register(tool_b)
    agent.prompt.append(MY_PROMPT_SECTION)
```

One function. No subclassing `Skill`.

### 5.3 Adding an LLM Provider

```python
class MyProvider(LLMProvider):
    async def generate(self, messages, tools=None) -> LLMResponse: ...
    async def generate_stream(self, messages, tools=None): ...
```

Implement the ABC. Pass to Agent via Config.

## 6. Dependencies

### 6.1 Required

```
anthropic >= 0.39.0     # Primary LLM provider
```

That's it for MVP. No web frameworks, no ORMs, no CLI libraries.

### 6.2 Optional

```
openai >= 1.0.0         # Alternative LLM provider
rich >= 13.0.0          # Future: TUI mode
tiktoken >= 0.5.0       # Future: exact token counting
```

All optional. The core Agent has exactly one required dependency.

## 7. File Size Limits

```
Module          Max Lines    Rationale
───────         ─────────    ──────────
_core.py        300          Agent orchestration, readable in one session
_loop.py        150          State machine, focused
_messages.py    200          Message management + token counting
_llm.py         200          Provider interface + Anthropic impl
_config.py      100          Dataclasses, simple
_tools.py       200          Registry + executor
_events.py      80           Event types + bus
_guard.py       100          Path safety
cli.py          200          REPL + argument parsing
─────────────────────────────────────────
Total           ~1,530      Full agent core
```

If a module exceeds its limit, split it. Complexity should be in the LLM's reasoning, not in the harness code.

## 8. Testing Conventions

```python
# Test file mirrors source: tests/test_core.py
# One test class per public class, one test function per behavior

class TestAgent:
    async def test_simple_answer_no_tools(self):
        """Agent answers directly when tools aren't needed."""
        ...

    async def test_single_tool_call(self):
        """Agent calls a tool and uses the result."""
        ...

    async def test_max_iterations_reached(self):
        """Agent terminates gracefully at max iterations."""
        ...

# Mock the LLM, not the network
class MockLLMProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.call_count = 0

    async def generate(self, messages, tools=None) -> LLMResponse:
        response = self.responses[self.call_count]
        self.call_count += 1
        return response
```

## 9. Anti-Patterns (Forbidden)

| Anti-Pattern | Why Forbidden |
|---|---|
| `as Any`, `@ts-ignore` equivalents | Type safety is non-negotiable |
| Empty `except:` or `except Exception: pass` | All errors must be handled or explicitly propagated |
| Global mutable state | Agent instances are self-contained; no module-level globals |
| Class inheritance beyond ABC | Composition and functions over hierarchies |
| Service locator / DI container | Pass dependencies explicitly |
| Circular imports | Package layout prevents this naturally |
| `**kwargs` without explicit parameters | Tool handlers take typed `args: dict`; no splatting |
| Singleton pattern | Create new Agent instances; don't reuse a global |
