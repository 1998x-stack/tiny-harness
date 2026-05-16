# tiny-harness User Guide

A complete guide to using tiny-harness in all modes: Python API, CLI, TUI, and programmatic integration.

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Python API](#python-api)
4. [CLI Modes](#cli-modes)
5. [TUI Mode](#tui-mode)
6. [Tools & Skills](#tools--skills)
7. [Streaming & Events](#streaming--events)
8. [Configuration](#configuration)
9. [Session Persistence](#session-persistence)
10. [Building Custom Tools](#building-custom-tools)
11. [Building Skills](#building-skills)
12. [Troubleshooting](#troubleshooting)
13. [Examples](#examples)

---

## Installation

```bash
pip install tiny-harness

# Optional: Rich TUI mode
pip install tiny-harness[tui]

# Development install
pip install -e ".[dev]"
```

**Requirements**: Python 3.11+, `httpx` (auto-installed).

**API keys**: Set your provider's API key as an environment variable:
- DeepSeek (default): `export DEEPSEEK_API_KEY="sk-..."`
- Anthropic: `export ANTHROPIC_API_KEY="sk-ant-..."`
- OpenAI: `export OPENAI_API_KEY="sk-..."`

---

## Quick Start

### One-liner (CLI one-shot)

```bash
tiny-harness "Explain quantum computing in one sentence"
```

### Interactive session (CLI)

```bash
tiny-harness
```

### Rich terminal UI

```bash
tiny-harness --tui --skills files
```

### Python script

```python
import asyncio, os
from tiny_harness import Agent, Prompt, Config

async def main():
    agent = Agent(
        prompt=Prompt("You are a helpful assistant. Be concise."),
        config=Config(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"], workspace="."),
    )
    result = await agent.run("What is 2+2?")
    print(result)

asyncio.run(main())
```

---

## Python API

### Creating an Agent

```python
from tiny_harness import Agent, Prompt, Config

agent = Agent(
    prompt=Prompt("You are a helpful coding assistant. Use tools when needed."),
    config=Config(
        model="deepseek-chat",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        workspace=".",                    # root directory for file operations
        provider="deepseek",              # "deepseek" | "anthropic" | "openai"
        api_base_url="https://api.deepseek.com/v1",
        max_iterations=25,                # safety cap
    ),
)
```

### Loading Skills

Skills give the agent capabilities. Load them before running:

```python
agent.load_skill("files")     # file system access (read, write, list, find, delete, mkdir, move)
agent.load_skill("shell")     # shell command execution
agent.load_skill("search")    # code search with regex
```

Multiple skills can be loaded — their prompts accumulate:

```python
agent.load_skill("files")
agent.load_skill("shell")
agent.load_skill("search")
# Agent now has 9 tools across 3 skill domains
```

### Running a Prompt

```python
# Blocking — returns the final answer
result = await agent.run("Create a hello.py file")
print(result)
```

### Streaming

```python
async for event in agent.run_stream("Create hello.py"):
    if event.type == "text_delta":
        print(event.content, end="", flush=True)
    elif event.type == "tool_start":
        print(f"\n  ⚡ {event.tool_name}")
    elif event.type == "tool_end":
        print(f"  ← done ({event.duration_ms}ms)")
    elif event.type == "error":
        print(f"\n  ⚠ {event.message}")
```

### Session (Multi-Turn)

The agent remembers conversation context across prompts:

```python
await agent.run("My name is Alice and I like Python.")    # turn 1
await agent.run("What's my name?")                          # turn 2 — remembers Alice
await agent.run("Suggest a Python project for me.")         # turn 3 — knows context

agent.clear()  # reset conversation (keeps tools and config)
```

### Events

```python
# Subscribe to specific event types
agent.on("tool_start", lambda e: print(f"Calling {e.tool_name}"))
agent.on("tool_end", lambda e: print(f"Done in {e.duration_ms}ms"))
agent.on("error", lambda e: print(f"Error: {e.message}"))

# Subscribe to all events
async def log_all(event):
    print(f"[{event.type}] {event.content}")
agent.events.subscribe(log_all)
```

---

## CLI Modes

### One-Shot Mode

Run a single prompt and get the answer:

```bash
tiny-harness "What is the capital of France?"
```

With options:

```bash
tiny-harness "Create a hello.py file" \
    --model claude-sonnet-4-20250514 \
    --provider anthropic \
    --skills files \
    --workspace /home/user/project \
    --max-iterations 10
```

### Session Mode (REPL)

Interactive prompt loop with streaming output:

```bash
tiny-harness
```

```
> Create hello.py
[Iter 1/25 | Tokens: 1.2K]
Let me create that file.
  ⚡ write_file  path=hello.py content=print(...)  (Created, 22B, 3ms)
[Iter 2/25 | Tokens: 1.4K]
Done! Created hello.py.

> Add a shebang line for python3
[Iter 1/25 | Tokens: 2.1K]
...
```

**Session commands:**

| Command | Action |
|---|---|
| `/exit`, `/quit` | End session |
| `/help` | Show available commands |
| `/tools` | List registered tools |
| `/clear` | Reset conversation (keep tools) |
| `/save` | Save conversation to JSONL |
| `/history` | List saved sessions |

### DeepSeek (Default)

```bash
export DEEPSEEK_API_KEY="sk-..."
tiny-harness "Say hi"
```

### Anthropic

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
tiny-harness "Say hi" --provider anthropic --model claude-sonnet-4-20250514
```

### OpenAI

```bash
export OPENAI_API_KEY="sk-..."
tiny-harness "Say hi" --provider openai --model gpt-4o
```

---

## TUI Mode

A full-featured terminal UI with Rich-powered panels, markdown rendering, and color-coded messages.

```bash
pip install tiny-harness[tui]
tiny-harness --tui --skills files,shell,search
```

**Layout:**

```
┌─ tiny-harness ─────────────────────────────────────────────┐
│  claude-sonnet-4  │  Iter 3/25  │  3 calls  │  12s          │  ← Header
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─ You ──────────────────────────────────────────────┐    │
│  │ Create a hello.py file                              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                            │
│  ⚡ write_file  path=hello.py content=print("Hello")       │
│       Created hello.py (1 line, 22B)                       │
│                                                            │
│  ┌─ Agent ────────────────────────────────────────────┐    │
│  │ Done! Created `hello.py` with the expected content. │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                            │
├────────────────────────────────────────────────────────────┤
│ Prompt > _                                                  │  ← Input
└────────────────────────────────────────────────────────────┘
```

**Color coding:**

| Color | Meaning |
|---|---|
| Blue | User messages (You) |
| Gray/White | Agent responses |
| Amber/Yellow | Tool calls |
| Green | Tool results (success) |
| Red | Errors |

**TUI commands** (same as session mode): `/exit`, `/help`, `/tools`, `/clear`, `/save`, `/history`.

---

## Tools & Skills

tiny-harness ships with 9 tools across 3 skills. Tools are not loaded by default — you must explicitly load the skills you need.

### Files Skill (`files`)

7 tools for filesystem operations:

| Tool | What it does |
|---|---|
| `read_file(path, offset?, limit?)` | Read file contents (text) |
| `write_file(path, content)` | Create or overwrite a file |
| `list_directory(path?, pattern?, recursive?)` | List directory entries with sizes |
| `find_files(pattern, path?, max_results?)` | Find files by glob pattern |
| `delete_file(path)` | Permanently delete a file |
| `create_directory(path)` | Create a directory and parents |
| `move_file(source, destination)` | Move or rename a file |

```python
agent.load_skill("files")
```

### Shell Skill (`shell`)

1 tool for command execution:

| Tool | What it does |
|---|---|
| `run_command(command, cwd?, timeout?)` | Execute shell command |

```python
agent.load_skill("shell")
```

### Search Skill (`search`)

1 tool for code search:

| Tool | What it does |
|---|---|
| `search_content(pattern, path?, file_pattern?, max_results?)` | Search file contents with regex |

```python
agent.load_skill("search")
```

### Tool Selection Guide

| You want to... | Use |
|---|---|
| See what's in a directory | `list_directory` |
| Find files by name pattern | `find_files` |
| Find text inside files | `search_content` |
| Read a file | `read_file` |
| Create/overwrite a file | `write_file` |
| Run git, pip, tests, scripts | `run_command` |

---

## Streaming & Events

### Event Types

| Event | When | Fields |
|---|---|---|
| `text_delta` | LLM generates text | `content` |
| `tool_start` | Tool execution begins | `tool_name`, `content` (args) |
| `tool_end` | Tool execution completes | `tool_name`, `content` (result), `duration_ms` |
| `iteration` | New loop iteration | `num`, `max`, `content` (token estimate) |
| `error` | Error occurs | `message` |

### Streaming Example

```python
async for event in agent.run_stream("Search for TODOs in the code"):
    match event.type:
        case "text_delta":
            print(event.content, end="", flush=True)
        case "tool_start":
            print(f"\n  ⚡ {event.tool_name}")
        case "tool_end":
            print(f"  ← {event.content[:80]}")
        case "iteration":
            print(f"\n[Iter {event.num}/{event.max}]")
        case "error":
            print(f"\n  ⚠ {event.message}")
```

---

## Configuration

Full `Config` reference:

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | required | Model identifier |
| `api_key` | `str` | required | Provider API key |
| `workspace` | `str` | required | Root directory for file operations |
| `provider` | `str` | `"deepseek"` | `"deepseek"`, `"anthropic"`, `"openai"` |
| `api_base_url` | `str \| None` | `None` | Custom API endpoint (auto-set for DeepSeek via CLI) |
| `max_iterations` | `int` | `25` | Max loop iterations before forced finish |
| `max_errors` | `int` | `10` | Total tool error budget |
| `max_consecutive_errors` | `int` | `3` | Consecutive error budget |
| `timeout_ms` | `int` | `30_000` | Per-tool execution timeout |
| `max_tool_result_chars` | `int` | `50_000` | Truncate large tool outputs |

### Provider-Specific Config

```python
# DeepSeek (default)
Config(model="deepseek-chat", api_key="...", workspace=".",
       provider="deepseek", api_base_url="https://api.deepseek.com/v1")

# Anthropic
Config(model="claude-sonnet-4-20250514", api_key="...", workspace=".",
       provider="anthropic")

# OpenAI
Config(model="gpt-4o", api_key="...", workspace=".",
       provider="openai")

# Custom OpenAI-compatible (OpenRouter, local models, etc.)
Config(model="...", api_key="...", workspace=".",
       provider="openai", api_base_url="https://your-endpoint.com/v1")
```

---

## Session Persistence

Conversations can be saved as JSONL files for later review.

### CLI

```
> /save
Session saved: a1b2c3d4e5f6 → ~/.tiny-harness/sessions/a1b2c3d4e5f6.jsonl

> /history
Sessions (3):
  a1b2c3d4e5f6 — 12 turns, deepseek-chat, 2026-05-16T14:30:00
  7890abcdef12 — 5 turns, claude-sonnet-4, 2026-05-16T13:15:00
```

### Python API

```python
from tiny_harness._persist import SessionStore

store = SessionStore()

# Start a session
agent.start_session()  # auto-generates session ID

# Save is automatic — each run() call appends a turn
await agent.run("Hello")
await agent.run("How are you?")

# List sessions
for s in store.list_sessions():
    print(f"{s['session_id']}: {s['turns']} turns, {s['model']}")

# Load a session
turns = store.load_session("a1b2c3d4e5f6")
for turn in turns:
    print(f"[{turn['role']}] {turn.get('content', '')[:100]}")

# Export
data = store.export_session("a1b2c3d4e5f6")

# Delete
store.delete_session("a1b2c3d4e5f6")
```

### JSONL Format

Each line is a JSON object:

```json
{"session_id":"a1b2c3d4e5f6","chat_id":1,"timestamp":"2026-05-16T14:30:00Z","role":"user","content":"Hello","model":"deepseek-chat"}
{"session_id":"a1b2c3d4e5f6","chat_id":2,"timestamp":"2026-05-16T14:30:05Z","role":"assistant","content":"Hi! How can I help?","token_usage":{"input":10,"output":5}}
{"session_id":"a1b2c3d4e5f6","chat_id":3,"timestamp":"2026-05-16T14:30:10Z","role":"assistant","content":"Let me check...","tool_calls":[{"name":"read_file","arguments":{"path":"/tmp/x"}}],"tool_results":[{"id":"tc1","content":"file content here"}],"iteration":2}
```

---

## Building Custom Tools

A tool is a function that takes `args: dict` and returns `str`:

```python
from tiny_harness import ToolDef

def weather_tool(args: dict) -> str:
    city = args["city"]
    # In a real tool, you'd call a weather API here
    return f"Sunny, 22°C in {city}"

# Register the tool
agent.tools.register_from_def(
    ToolDef(
        name="weather",
        description="Get current weather for a city.",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"],
        },
        risk_level="read_only",  # "safe" | "read_only" | "mutation" | "destructive" | "dangerous"
    ),
    handler=weather_tool,
)
```

**Important**: The handler receives a single `args: dict` parameter, not `**kwargs`. The `ToolDef` tells the LLM what arguments to pass. Risk level controls FilesystemGuard behavior.

### Async Handlers

```python
async def slow_api_call(args: dict) -> str:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.example.com/data?query={args['query']}")
        return resp.text

agent.tools.register_from_def(ToolDef(...), handler=slow_api_call)
```

---

## Building Skills

A skill packages tools + prompt instructions together:

```python
# my_skill.py
from tiny_harness._tools import ToolDef

MY_PROMPT = """
## My Custom Skill

You have access to these tools:
- greet(name): Say hello to someone.

Use greet when you need to welcome a user.
"""

def register(agent):
    def greet(args: dict) -> str:
        return f"Hello, {args['name']}!"

    agent.tools.register_from_def(
        ToolDef(
            name="greet",
            description="Say hello to someone by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        handler=greet,
    )
    agent._prompt.append(MY_PROMPT)
```

Then load it:

```python
agent.load_skill("my_skill")  # if it's importable
agent.load_skill("/path/to/my_skill.py")  # by file path
```

---

## Troubleshooting

### "API key not found"

Set the environment variable for your provider:
```bash
export DEEPSEEK_API_KEY="sk-..."
```

### "Stream failed: 400 reasoning_content must be passed back"

DeepSeek v4 models (`deepseek-v4-flash`) require reasoning passthrough. Use `deepseek-chat` instead:
```bash
tiny-harness "hello" --model deepseek-chat
```

### "Tool 'X' not found"

The skill providing that tool isn't loaded. Check with `/tools` or:
```python
print(agent.tools.names())
```

### "Tool 'X' failed: unexpected keyword argument"

Your handler takes `**kwargs` instead of `args: dict`. Fix:
```python
# Wrong
def my_tool(path: str) -> str: ...

# Correct
def my_tool(args: dict) -> str:
    path = args["path"]
```

### "Agent stopped due to LLM error"

- **Auth failure**: Check your API key.
- **Network error**: Check your internet connection.
- **Rate limit**: Wait and retry.
- **Context overflow**: The conversation is too long. Use `agent.clear()`.

### Agent seems stuck in a loop

The agent has safety valves: max iterations (25), error budget (10 total / 3 consecutive), and loop detection (3 identical failing calls). If it hits these, it will try to give a final answer with what it knows.

---

## Examples

All examples are in `examples/`. Run with `DEEPSEEK_API_KEY` set.

### Basic Usage

| Example | What it shows |
|---|---|
| [`01_basic_chat.py`](examples/01_basic_chat.py) | Simplest agent usage — one prompt, one answer |
| [`02_file_tools.py`](examples/02_file_tools.py) | Agent reads and writes files |
| [`03_custom_tool.py`](examples/03_custom_tool.py) | Register a custom calculator tool |
| [`04_streaming.py`](examples/04_streaming.py) | Stream events in real-time |
| [`05_session.py`](examples/05_session.py) | Multi-turn conversation with memory |

### Advanced

| Example | What it shows |
|---|---|
| [`06_shell_tools.py`](examples/06_shell_tools.py) | Agent uses git, counts files |
| [`07_search_tools.py`](examples/07_search_tools.py) | Agent searches codebase |
| [`08_multi_skill.py`](examples/08_multi_skill.py) | Agent combines files + shell + search |

### Agent-Built Projects

These games were built by tiny-harness using the `write_file` tool:

```bash
python examples/agent-projects/pingpong.py    # Terminal ping pong (W/S vs arrows)
python examples/agent-projects/snake.py       # Terminal snake (arrow keys)
python examples/agent-projects/cartpole.py    # RL CartPole environment
python examples/agent-projects/tictactoe.py   # Terminal tic-tac-toe
```

### Builder Scripts

Let the agent build projects for you:

```bash
python examples/build_pingpong.py    # Agent builds pingpong game
python examples/build_snake.py       # Agent builds snake game
python examples/build_cartpole.py    # Agent builds cartpole env
python examples/build_all.py         # Agent builds all 4 projects
```
