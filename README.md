# tiny-harness

**Minimal AI agent harness — wrap any LLM with tools and a streaming CLI.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-147%20passed-brightgreen)](https://github.com/1998x-stack/tiny-harness/actions)
[![Lines](https://img.shields.io/badge/code-1%2C350%20lines-lightgrey)](.)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`tiny-harness` is a ~1,100-line Python package that turns an LLM into an AI agent — giving it tools, a conversation loop, streaming events, and a CLI session. One dependency. One import.

```bash
pip install tiny-harness
```

```python
from tiny_harness import Agent, Prompt, Config
import os

agent = Agent(
    prompt=Prompt("You are a helpful coding assistant. Use tools when needed."),
    config=Config(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        workspace=".",
    )
)

agent.load_skill("files")                    # gives the agent file system access
result = await agent.run("Create hello.py")  # agent writes the file
```

## Features

- **Agent loop** — while-loop state machine with safety valves (max iterations, error budget, loop detection)
- **Tool system** — pluggable tools with JSON Schema validation, automatic error→result conversion, LLM self-correction
- **Streaming** — real-time SSE streaming from Anthropic and OpenAI-compatible APIs
- **Multi-provider** — Anthropic (native) and OpenAI/DeepSeek (compatible) providers
- **Skills** — packaged bundles of tools + prompt instructions, loaded with `agent.load_skill("files")`
- **CLI** — session REPL with streaming output, one-shot mode for scripts
- **Rich TUI** — optional `--tui` mode with panels, colors, real-time status bar (`pip install tiny-harness[tui]`)
- **Filesystem guard** — workspace boundary enforcement, path traversal protection
- **1,125 lines** — readable top-to-bottom, CleanRL-inspired code style

## Quick Start

### Install

```bash
pip install tiny-harness
```

### One-Shot Mode

```bash
# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Run a single prompt
tiny-harness "Create a hello.py file that prints 'Hello, world!'"
```

### Session Mode

```bash
tiny-harness --model claude-sonnet-4-20250514 --skills files
```

```
> Create hello.py
[Iter 1/25 | Tokens: 1.2K]
Let me create that file.
  ⚡ write_file  path=hello.py content=print(...)  (Created, 22B)
[Iter 2/25 | Tokens: 1.4K]
Done! Created hello.py.

> Add a shebang line for python3
[Iter 1/25 | Tokens: 2.1K]
...
```

Session commands: `/exit`, `/help`, `/tools`, `/clear`.

### TUI Mode

```bash
pip install tiny-harness[tui]
tiny-harness --tui --model claude-sonnet-4-20250514 --skills files
```

```
┌─ tiny-harness ─────────────────────────────────────────┐
│  claude-sonnet-4  │  Iter 3/25  │  4.2K tokens  │  12s │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  You: Create a hello.py file                           │
│                                                         │
│  Let me create that file for you.                       │
│    ⚡ write_file  path=hello.py content=print(...)     │
│       Created hello.py (1 line, 22B)                    │
│  Done! The file is ready.                               │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ > _                                                     │
└─────────────────────────────────────────────────────────┘
```

Rich-powered terminal UI with color-coded messages, tool call indicators, status bar with iteration/token/time tracking.

### DeepSeek

```bash
export DEEPSEEK_API_KEY="sk-..."
tiny-harness "Say hi" --model deepseek-chat --provider deepseek --api-base-url https://api.deepseek.com/v1
```

## Architecture

```
User Prompt
  │
  ▼
Agent.run(prompt)
  ├─ MessageManager  — conversation array (system + user + assistant + tool results)
  └─ AgentLoop       — while-loop state machine
       ├─ LLMProvider    — AnthropicProvider / OpenAIProvider (HTTP + SSE)
       └─ ToolExecutor   — validate → guard → execute → format → result
            ├─ ToolRegistry  — {name: (ToolDef, handler)}
            └─ FilesystemGuard — path resolution + boundary enforcement
```

**Core loop**: `prompt → LLM → tool calls → execute → results → LLM → ... → final answer`

### Package Layout

```
tiny_harness/
├── __init__.py          # Public API: Agent, Prompt, Config, ToolDef
├── _core.py             # Agent class — orchestrator, session management
├── _loop.py             # AgentLoop — state machine, error budget, loop detection
├── _llm.py              # LLMProvider ABC + AnthropicProvider + OpenAIProvider
├── _messages.py         # MessageManager — conversation, token counting
├── _tools.py            # ToolRegistry + ToolExecutor + schema validator
├── _config.py           # AgentConfig, Prompt dataclasses
├── _events.py           # StreamEvent types + EventBus
├── _guard.py            # FilesystemGuard — workspace boundaries
├── cli.py               # CLI entry point
├── tools/files.py       # File tool handlers (read, write, list, find, delete, mkdir, move)
└── skills/files.py      # register(agent) → file tools + prompt instructions
```

## API

### Creating an Agent

```python
from tiny_harness import Agent, Prompt, Config

agent = Agent(
    prompt=Prompt("You are a helpful assistant. Use tools when needed."),
    config=Config(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        workspace=".",                              # root dir for file operations
        provider="anthropic",                       # "anthropic" | "openai" | "deepseek"
        max_iterations=25,                          # safety cap on loop iterations
    )
)
```

### Running

```python
# Single prompt — returns final answer
result = await agent.run("Create a hello.py file")

# Streaming — yields events as they happen
async for event in agent.run_stream("Create hello.py"):
    if event.type == "text_delta":
        print(event.content, end="", flush=True)
    elif event.type == "tool_start":
        print(f"\n  ⚡ {event.tool_name}")
```

### Tools & Skills

```python
# Register a custom tool
from tiny_harness import ToolDef

agent.tools.register_from_def(
    ToolDef(
        name="weather",
        description="Get current weather for a city.",
        parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    ),
    handler=lambda city: f"Sunny, 22°C in {city}",
)

# Load built-in skills
agent.load_skill("files")     # file system access
```

### Events

```python
agent.on("tool_start", lambda e: print(f"Calling {e.tool_name}"))
agent.on("tool_end", lambda e: print(f"Done ({e.duration_ms}ms)"))
agent.on("error", lambda e: print(f"Error: {e.message}"))
```

## Configuration

| Field | Default | Description |
|---|---|---|
| `model` | required | Model identifier |
| `api_key` | required | Provider API key |
| `workspace` | required | Root directory for file operations |
| `provider` | `"anthropic"` | `"anthropic"`, `"openai"`, `"deepseek"` |
| `api_base_url` | provider default | Custom API endpoint |
| `max_iterations` | `25` | Max loop iterations |
| `max_errors` | `10` | Total tool error budget |
| `max_consecutive_errors` | `3` | Consecutive error budget |
| `timeout_ms` | `30_000` | Tool execution timeout |
| `max_tool_result_chars` | `50_000` | Truncate large results |

## Providers

### Anthropic (default)
```python
config = Config(model="claude-sonnet-4-20250514", api_key="...", workspace=".")
```

### OpenAI
```python
config = Config(model="gpt-4o", api_key="...", workspace=".", provider="openai")
```

### DeepSeek
```python
config = Config(
    model="deepseek-chat", api_key="...", workspace=".",
    provider="deepseek", api_base_url="https://api.deepseek.com/v1",
)
```

## Design Principles

This project follows [CleanRL](https://github.com/vwxyzjn/cleanrl) philosophy:

- **Single-file readability** — each module is focused and <300 lines
- **Functions over classes** — classes only when bundling state + behavior
- **Dataclasses for data** — no ORMs, no heavy frameworks
- **Explicit data flow** — no global state, no service locators
- **Zero magic** — read the source, understand it completely

Full design documentation in [`docs/`](docs/):
- [thoughts.md](docs/thoughts.md) — first principles of AI agent harness design
- [tools/](docs/tools/) — deep dive on tool system design (7 documents)
- [agent-loop/](docs/agent-loop/) — loop mechanics, state machine
- [cli.md](docs/cli.md) — CLI design, streaming format
- [skills.md](docs/skills.md) — skill system architecture
- [code-style.md](docs/code-style.md) — coding conventions
- [adr/](docs/adr/) — architectural decision records

## Development

```bash
git clone https://github.com/1998x-stack/tiny-harness.git
cd tiny-harness
pip install -e ".[dev]"

# Run tests (excludes integration tests that need API keys)
pytest tests/ --ignore=tests/test_integration.py

# Run integration tests (requires ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY="sk-ant-..." pytest tests/test_integration.py -v -m integration
```

## License

MIT
