# CLI Design

## 1. Overview

```
$ tiny-harness
╔══════════════════════════════════════════╗
║              tiny-harness                 ║
║         model: claude-sonnet-4            ║
║         tools: files, shell, search       ║
║         workspace: /home/user/project     ║
║         type /help for commands           ║
╚══════════════════════════════════════════╝

> Create a hello.py file that prints "Hello, world!"

[Iter 1/25 | Tokens: 1.2K/200K]
Let me create that file for you.
  ⚡ write_file  hello.py  (22B, 3ms)

[Iter 2/25 | Tokens: 1.6K/200K]
Let me verify the file was created correctly.
  ⚡ read_file  hello.py  (1 line, 2ms)

[Iter 3/25 | Tokens: 1.9K/200K]
Done! Created `hello.py` with the expected content:
```
print('Hello, world!')
```

>
```

## 2. Session Lifecycle

```
┌─────────────┐
│  STARTUP    │  Load config, Prompt, register tools, connect LLM
└──────┬──────┘
       ▼
┌─────────────┐
│  SESSION    │  ← User types prompts, Agent responds
│   LOOP      │
│             │  while session active:
│  ┌────────┐ │    1. Read user input
│  │ prompt │ │    2. Run Agent with Conversation context
│  └───┬────┘ │    3. Stream output with metadata
│      │      │    4. Wait for next prompt
│      ▼      │
│  ┌────────┐ │
│  │stream  │ │
│  │output  │ │
│  └───┬────┘ │
│      │      │
│      └──────┤  (loop back to prompt)
└─────────────┘
       │  user types /exit or Ctrl+C
       ▼
┌─────────────┐
│  SHUTDOWN   │  Discard Conversation, close connections, exit
└─────────────┘
```

The Agent is created once at startup. The Conversation persists across all prompts within the session. Each `run(prompt)` appends the new user message to the existing Conversation.

## 3. Streaming Output Format

### 3.1 Event Types

The CLI renders these events in real time:

| Event | Format | Example |
|---|---|---|
| `iteration` | `[Iter N/M \| Tokens: used/limit]` | `[Iter 3/25 \| Tokens: 4.2K/200K]` |
| `text_delta` | Inline text (no prefix) | `Let me read that file...` |
| `tool_start` | `  ⚡ tool_name  args_summary` | `  ⚡ write_file  hello.py (22B)` |
| `tool_end` | Appended to tool_start line | `, 3ms` |
| `tool_error` | `  ✗ tool_name  error_summary` | `  ✗ read_file  not found` |
| `tool_long` | `  ⏳ tool_name  progress...` | `  ⏳ run_tests  12/27 passed` |
| `error` | `  ⚠ error message` | `  ⚠ Context 85% full` |
| `done` | (end of response, prompt returns) | |

### 3.2 Rendering Order

```
> user prompt
[Iter 1/25 | Tokens: 1.2K/200K]       ← before LLM call
Let me search for that.                  ← text streaming
  ⚡ search_code  pattern="TODO"         ← tool call announced before execution
  ⚡ search_code  15 matches, 1.2s       ← result appended after execution
Now let me format the results...         ← more text streaming
[Iter 2/25 | Tokens: 1.8K/200K]        ← next iteration
Here are all 15 TODOs: ...              ← final answer (streaming)
                                        ← prompt returns
>
```

### 3.3 Metadata Line

```
[Iter N/M | Tokens: used/limit | Δ: +last_call_tokens]
```

- `N/M`: Current iteration / max iterations
- `Tokens`: Estimated total tokens in Conversation
- `Δ`: Tokens consumed by last LLM call (optional, shown when significant)

Warnings:
```
[Iter 6/25 | Tokens: 168K/200K ⚠ 84%]
```

## 4. Command Modes

### 4.1 Session Mode (default)

```bash
tiny-harness
tiny-harness --model claude-sonnet-4-20250514
tiny-harness --prompt prompts/coder.md --tools files,shell
```

Opens interactive session. User types prompts until `/exit`.

### 4.2 One-Shot Mode

```bash
tiny-harness run "Create hello.py"
tiny-harness run "Fix all type errors" --workspace /home/user/project
tiny-harness -m "Create hello.py"  # shortcut
```

Single prompt, streams output, exits. For scripts, CI, quick tasks.

### 4.3 Config Dump Mode

```bash
tiny-harness config
tiny-harness config --format json
```

Prints resolved configuration and exits. For debugging.

### 4.4 Tool List Mode

```bash
tiny-harness tools
```

Lists all registered tools with descriptions. For discovery.

## 5. CLI Arguments

```
tiny-harness [run] [prompt] [options]

Session control:
  --session, -s           Force session mode (default when no prompt given)
  (no flag, with prompt)   One-shot mode

Model:
  --model, -m MODEL        Model identifier (default: claude-sonnet-4-20250514)
  --provider PROVIDER      LLM provider: anthropic, openai (auto-detected)

Agent:
  --prompt FILE            Prompt file (default: built-in coding assistant)
  --workspace, -w DIR      Workspace directory (default: current directory)
  --max-iterations N       Max loop iterations (default: 25)
  --timeout MS             Tool timeout in ms (default: 30000)

Tools:
  --tools LIST             Comma-separated tool sets: files,shell,search
  --skill NAME             Load a skill by name (repeatable)

Output:
  --quiet, -q              Minimal output (no metadata, no tool announcements)
  --verbose, -v            Maximum metadata
  --no-stream              Disable streaming (wait for full response)

Config:
  --config FILE            TOML config file (future)
  --api-key KEY            Override API key
  --api-key-env VAR        Environment variable for API key
```

## 6. Built-in Session Commands

Inside a session, the user can type these commands:

| Command | Action |
|---|---|
| `/exit`, `/quit`, Ctrl+C | End the session |
| `/help` | Show available commands |
| `/tools` | List registered tools |
| `/clear` | Reset the Conversation (keep tools, Prompt, Config) |
| `/compact` | Manually trigger context compaction |
| `/stats` | Show session statistics (iterations, tokens, tool calls) |
| `/config` | Show current configuration |
| `/model MODEL` | Switch model mid-session |
| `/skill NAME` | Load a skill mid-session |
| `/save FILE` | Save the Conversation to a file |
| `!command` | Escape to shell (run command outside Agent) |

## 7. Implementation

### 7.1 REPL Loop

```python
# tiny_harness/cli.py
import asyncio
import sys

async def session_loop(agent: Agent):
    print_banner(agent)

    while True:
        try:
            user_input = await async_input("> ")
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = await handle_command(agent, user_input)
            if handled == "exit":
                break
            continue

        if user_input.startswith("!"):
            run_shell(user_input[1:])
            continue

        # Run the agent with this prompt
        await run_with_streaming(agent, user_input)


async def run_with_streaming(agent: Agent, prompt: str):
    """Run agent and stream output with metadata."""
    iteration = agent.conversation.iteration_count

    async for event in agent.run_stream(prompt):
        match event.type:
            case "iteration":
                tokens = f"{event.tokens_used // 1000}K/{agent.config.context_limit // 1000}K"
                pct = event.tokens_used / agent.config.context_limit
                warn = " ⚠" if pct > 0.8 else ""
                print(f"\n[Iter {event.num}/{agent.config.max_iterations} | Tokens: {tokens}{warn}]")

            case "text_delta":
                print(event.content, end="", flush=True)

            case "tool_start":
                args_summary = summarize_args(event.arguments)
                print(f"\n  ⚡ {event.tool_name}  {args_summary}", end="", flush=True)

            case "tool_end":
                timing = f", {event.duration_ms}ms" if event.duration_ms else ""
                result = summarize_result(event.result)
                print(f"  ({result}{timing})")

            case "tool_error":
                print(f"\n  ✗ {event.tool_name}  {event.error}")

            case "error":
                print(f"\n  ⚠ {event.message}")

    print()  # Final newline


def summarize_args(args: dict) -> str:
    """Summarize tool arguments for display (first few key-value pairs)."""
    if not args:
        return ""
    items = list(args.items())[:2]
    parts = []
    for k, v in items:
        v_str = str(v)
        if len(v_str) > 40:
            v_str = v_str[:37] + "..."
        parts.append(f"{k}={v_str}")
    if len(args) > 2:
        parts.append("...")
    return "  ".join(parts)


def summarize_result(result: str) -> str:
    """Summarize tool result for display (first sentence or size)."""
    result = result.strip()
    if "\n" in result:
        first_line = result.split("\n")[0]
        return first_line[:60]
    return result[:60]
```

### 7.2 Entry Point

```python
# tiny_harness/cli.py
def main():
    args = parse_args()

    if args.subcommand == "tools":
        list_tools(args)
        return

    if args.subcommand == "config":
        dump_config(args)
        return

    # Build agent
    prompt = load_prompt(args.prompt)
    config = AgentConfig(
        model=args.model,
        max_iterations=args.max_iterations,
        timeout_ms=args.timeout,
        context_limit=200_000,
    )
    agent = Agent(prompt=prompt, config=config)

    # Register tools
    if "files" in args.tools:
        register_file_tools(agent)
    if "shell" in args.tools:
        register_shell_tools(agent)
    if "search" in args.tools:
        register_search_tools(agent)

    # Load skills
    for skill_name in args.skills:
        agent.load_skill(skill_name)

    # Run
    if args.prompt:  # One-shot mode
        asyncio.run(run_with_streaming(agent, args.prompt))
    else:  # Session mode
        asyncio.run(session_loop(agent))
```

## 8. Design Decisions

| Decision | Rationale |
|---|---|
| Metadata-rich streaming (style C) | Power users benefit; can be toggled off with `--quiet` |
| Session is the default mode | Matches user expectation for an interactive tool |
| One-shot with CLI arg | Scriptable, CI-friendly |
| Built-in slash commands | Familiar (Slack/Discord convention); no special parser needed |
| `async_input` wrapper | Python's `input()` is blocking; wrap in `asyncio.to_thread` |
| Tool announcements before execution | User can see what's happening and interrupt if needed |
| `/clear` resets Conversation only | Tools, Config, Prompt persist — faster than restarting |
