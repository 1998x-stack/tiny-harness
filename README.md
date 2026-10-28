# tiny-harness

**Minimal AI agent harness — wrap any LLM with tools and a streaming CLI.**

> 中文一句话：极小的 AI Agent 执行环境（harness），给 LLM 配上工具、对话循环、流式事件与 CLI 会话。强调可读性、显式状态和可测试的执行契约，是 1998x-stack harness 家族的最小基线。

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Python tests](https://github.com/1998x-stack/tiny-harness/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/1998x-stack/tiny-harness/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`tiny-harness` is a small Python agent runtime with tools, a conversation loop, streaming events, and CLI sessions. It uses explicit contracts for tool validation, filesystem paths, and success/failure status.

```bash
pip install tiny-harness
```

```python
from tiny_harness import Agent, Prompt, Config
import os

agent = Agent(
    prompt=Prompt("You are a helpful coding assistant."),
    config=Config(
        model="deepseek-chat",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        workspace=".",
    )
)

# files skill loaded by default in CLI; explicit in Python API
agent.load_skill("files")
result = await agent.run("Create hello.py")  # agent writes the file
```

```bash
# CLI loads files skill automatically
tiny-harness "Create hello.py"
```

## Features

- **Agent loop** — while-loop state machine with safety valves (max iterations, error budget, loop detection)
- **Tool system** — pluggable tools with JSON Schema validation, automatic error→result conversion, LLM self-correction
- **Streaming** — real-time SSE streaming from Anthropic and OpenAI-compatible APIs
- **Multi-provider** — Anthropic (native) and OpenAI/DeepSeek (compatible) providers
- **Skills** — packaged bundles of tools + prompt instructions, loaded with `agent.load_skill("files")`
- **CLI** — session REPL with streaming output, one-shot mode for scripts. Files skill loaded by default.
- **Rich TUI** — optional `--tui` mode with panels, markdown rendering, color-coded messages (`pip install tiny-harness[tui]`)
- **Persistence** — JSONL session history with `/save` and `/history` commands
- **Filesystem guard** — workspace boundary enforcement, path traversal protection
- **Inspectable contracts** — explicit tool risk classification, workspace path declarations, and JSON Schema Draft 2020-12 validation

## Quick Start

> 中文要点：三行 pip 安装即可用；CLI 一行运行单次任务，或进入交互式会话；`files` 技能默认加载。

### Install

```bash
pip install tiny-harness
```

### One-Shot Mode

```bash
# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Run a single prompt
tiny-harness --provider anthropic "Create a hello.py file that prints 'Hello, world!'"
```

### Session Mode

```bash
tiny-harness --provider anthropic --model claude-sonnet-4-20250514 --skills files
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
tiny-harness --tui --provider anthropic --model claude-sonnet-4-20250514 --skills files
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

> 中文要点：`Agent.run(prompt)` 内嵌 MessageManager（对话数组）+ AgentLoop（while 状态机），LLMProvider 负责流式、ToolExecutor 负责「校验→守卫→执行→格式化」。核心循环：prompt → LLM → 工具调用 → 执行 → 结果 → LLM → …→ 最终答案。

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
    handler=lambda args: "Sunny, 22°C in " + args["city"],
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
| `provider` | `"deepseek"` | `"anthropic"`, `"openai"`, `"deepseek"` |
| `api_base_url` | provider default | Custom API endpoint |
| `max_iterations` | `25` | Max loop iterations |
| `max_errors` | `10` | Total tool error budget |
| `max_consecutive_errors` | `3` | Consecutive error budget |
| `timeout_ms` | `30_000` | Tool execution timeout |
| `max_tool_result_chars` | `50_000` | Truncate large results |
| `context_window` | `200_000` | Input + reserved output window (heuristic estimator) |
| `max_tokens` | `16_384` | Reserve for model output; must be less than context_window |

## Providers

### Anthropic (explicit)
```python
config = Config(model="claude-sonnet-4-20250514", api_key="...", workspace=".", provider="anthropic")
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

## The Harness Lineage（本系定位）

`tiny-harness` 是 1998x-stack 循序渐进 harness 家族的**最小基线**——先做到可读、零魔法、零冗余，再演进出更完整的能力：

| 成员 | 定位 | 与 tiny-harness 的关系 |
|------|------|------------------------|
| **tiny-harness** | 最小执行环境：loop + tools + streaming CLI | --- 本仓库（基线） |
| `mid-harness` | hooks / MCP / 渐进式 skills | 在 hook 之上扩展，不破坏单文件可读性 |
| `effective-harness` | 零配置 CLI wrapper 实现 Anthropic `twelve-factor agent` | 面向生产约定，tiny 的思路给到上一层 |
| `mega-harness` | 更完整的全家桶（规划/脚手架） | 集 loop + 调度 + 扩展包 |
| `agent-loop` | 跨会话的多 Agent 编排（Initializer / Executor） | 从「单会话执行」升级到「跨会话编排」 |
| `ralph-loop` | 插件式确定性自治循环（文件系统即记忆） | 从「工具封装」到「闭环自治」 |
| `loop-runner` | Generator–Evaluator 编码验证循环引擎 | 把「写码→验证」固化为循环 |

> 特点：从 tiny 的小而美到 mid/effective 的工程化，再到 agent-loop/ralph-loop 的自治化——每一层都继承上一层的可读性与诚实度。

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
- [TOOL_FACTORY.md](docs/TOOL_FACTORY.md) — JSON Schema and filesystem path contract for custom tools
- [TOOL_OUTCOME.md](docs/TOOL_OUTCOME.md) — typed tool execution success/failure semantics
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

## Context budget and unattended execution

The configured `context_window` reserves `max_tokens` for model output. When input history grows too large, the harness compacts oversized tool outputs and can discard complete older turns, preserving the latest user turn and tool-call/result pairing. This budget currently uses a heuristic estimate, not model-specific tokenizers.

The built-in Shell skill requires human approval by default. In `--no-hitl` mode, Shell additionally requires `--allow-unsafe-shell`. The default `shell_sandbox=off` is **not** OS-isolated. Linux can use [Bubblewrap](docs/SHELL_SANDBOX.md) with per-process limits, or opt into a [Docker OCI sandbox](docs/OCI_SANDBOX.md) with container-wide cgroup limits (validated in real GitHub CI).

## Optional Linux Shell Sandbox

```bash
tiny-harness --provider deepseek --skills files,shell --shell-sandbox bubblewrap --sandbox-cpu-seconds 30 --sandbox-memory-mb 1024 --sandbox-file-mb 32
```

Requires system-installed `bubblewrap` and `prlimit`, and working unprivileged namespaces. Sandboxed mode blocks external network by default; it never falls back to a host shell if setup fails. These per-process limits are **not** cgroup-wide quotas.

## OCI Docker Sandbox (Linux)

```bash
docker pull alpine:3.20
docker image inspect --format '{{index .RepoDigests 0}}' alpine:3.20
tiny-harness --provider deepseek --skills files,shell \
  --shell-sandbox docker \
  --sandbox-image 'alpine@sha256:<your_64_hex_digest>' \
  --sandbox-cpus 1.0 --sandbox-memory-mb 1024 --sandbox-pids-limit 64
```

Use the **actual** digest returned by `docker image inspect`; the displayed digest is only a placeholder. The Docker sandbox disables external networking, requires a pre-pulled image and uses a container read-only root with a writable workspace. A real OCI CI job verifies cgroup and filesystem/network isolation. Docker daemon privileges and third-party Python tools are still outside this boundary. See [OCI Sandbox details](docs/OCI_SANDBOX.md).

## Security

Tool arguments are checked with JSON Schema Draft 2020-12 and declared filesystem paths are normalized before tool execution. **These checks are not an OS sandbox**. Read [security boundaries](docs/security.md) and the [phased optimization status](docs/OPTIMIZATION_STATUS.md) before deploying to untrusted environments.

## License

MIT
