# Gotchas

Common pitfalls, surprising behaviors, and edge cases in tiny-harness.

## Tool System

### Tool handlers receive `args: dict`, not `**kwargs`

The ToolExecutor passes arguments as a single dictionary:

```python
# ✅ Correct
def my_tool(args: dict) -> str:
    path = args["path"]
    return f"ok: {path}"

# ❌ Wrong — will get "unexpected keyword argument" error
def my_tool(path: str) -> str:
    return f"ok: {path}"
```

The executor calls `handler(args)`, not `handler(**args)`. All built-in file tools follow the dict pattern.

### Tool definitions must be sent to the LLM

The AgentLoop passes tool definitions from `ToolExecutor.get_definitions()`. If you create a ToolExecutor without a Registry (e.g., a mock), ensure `get_definitions()` returns a valid list.

### Schema validation is type-only

The built-in validator checks JSON Schema types (`string`, `integer`, `boolean`, `array`, `object`), `required` fields, and `enum` values. It does NOT validate semantics — `path=""` passes type checks but fails at execution time. The handler is responsible for semantic validation.

### Tool name typos get helpful suggestions

If the LLM calls `read_fil` instead of `read_file`, the executor returns:
```
Tool 'read_fil' not found. Did you mean: read_file?
```

This uses `difflib.get_close_matches` with a 0.6 cutoff. Names very different from any registered tool just get "not found."

### Risk levels affect FilesystemGuard

| Risk Level | Guard Behavior |
|---|---|
| `safe` | No path checking |
| `read_only` | Checks path is readable within workspace |
| `mutation` | Checks path is writable within workspace |
| `destructive` | Strictest — checks path for delete operations |

The guard extracts the path from `args["path"]`, `args["source"]`, or `args["destination"]`. If your tool uses a different key, the guard won't apply.

### Tool timeouts are per-call, not cumulative

Each tool call has its own timeout (default 30s). A task requiring 10 tool calls can run for 10 × 30 = 300 seconds total. The iteration cap (default 25) is the primary time-gate.

---

## LLM Providers

### DeepSeek v4 models require reasoning passthrough

`deepseek-v4-flash` and other v4 models use "thinking mode" and require the `reasoning_content` field from API responses to be passed back in subsequent messages. This causes a 400 error on the second iteration:

```
Stream failed: 400 'The `reasoning_content` in the thinking mode must be passed back to the API.'
```

**Workaround**: Use `deepseek-chat` (v3) which supports tool calling without reasoning requirements. Or implement reasoning_content passthrough in the MessageManager.

### DeepSeek streaming tool calls arrive as deltas

Unlike Anthropic where tool calls arrive complete in a single event, OpenAI-compatible APIs (DeepSeek, OpenAI) stream tool call arguments as JSON fragments. The `OpenAIProvider.generate_stream()` buffers these deltas and emits the complete `ToolCallRequest` at the end.

### Anthropic uses separate `system` parameter

The Anthropic API passes the system prompt as a separate `system` parameter, not as a message role. The `AnthropicProvider._extract_system()` method handles this. If you're adding a new provider, check whether it expects system prompts as messages or as a separate field.

### Retry only covers transient errors

The retry logic (3 attempts, exponential backoff) covers:
- Rate limits (429)
- Server errors (5xx)
- Overloaded (529)
- Network errors (timeout, connection reset)

It does NOT retry:
- Auth failures (401, 403)
- Bad requests (400)
- Context overflow

---

## Agent Loop

### Conversation accumulates across `run()` calls

The Agent is session-scoped. Each `agent.run(prompt)` appends to the same Conversation:

```python
await agent.run("My name is Alice")       # Conversation: system, user1, assistant1
await agent.run("What's my name?")        # Conversation: ..., user2, assistant2
                                          # LLM sees all messages — remembers Alice
```

Use `agent.clear()` to reset the Conversation (keeps tools, config, prompt).

### Error budget resets per `run()` call

Error budget (10 total / 3 consecutive) resets with each `agent.run()` call. Errors from one prompt don't carry over to the next. `agent.clear()` also resets the budget.

### Loop detector is per-`run()`, not per-session

The loop detector tracks identical tool calls (same tool + same args) within a single `run()` call. It resets for each new prompt.

### Max iterations triggers degraded finish

When the iteration limit is reached, the loop injects a system notice asking the LLM for a final answer without tools. The final response may be incomplete — the LLM summarizes what it knows.

### Empty LLM responses are treated as errors

If the LLM returns zero text and zero tool calls, the loop emits an error event and continues to the next iteration. The LLM may self-correct on the next call.

---

## Configuration

### Prompt is separate from Config

```python
# ✅ Correct
agent = Agent(
    prompt=Prompt("You are helpful."),
    config=Config(model="...", api_key="...", workspace="."),
)

# ❌ Wrong — no such field
config = Config(system_prompt="...")
```

The Prompt is a first-class artifact (ADR 002). Config is runtime parameters.

### Default provider is `deepseek`, not `anthropic`

```python
config = Config(model="deepseek-chat", api_key="...", workspace=".")
# provider defaults to "deepseek"
# api_base_url defaults to "https://api.deepseek.com/v1"
```

The CLI also defaults to DeepSeek with `DEEPSEEK_API_KEY` env var.

### `api_base_url` is required for non-standard endpoints

For DeepSeek and custom OpenAI-compatible providers, set `api_base_url`:
```python
Config(provider="deepseek", api_base_url="https://api.deepseek.com/v1")
```

For OpenAI, it defaults to `https://api.openai.com/v1`.

---

## Filesystem

### Workspace boundaries are absolute

The FilesystemGuard resolves all paths to their canonical form (`os.path.realpath`). This means:
- Symlinks are resolved before boundary checking
- `..` traversal is collapsed before checking
- Relative paths are resolved against the workspace root

A symlink inside the workspace that points outside will be blocked.

### File writes auto-create parent directories

`write_file("a/b/c.txt", content)` creates `a/` and `a/b/` automatically. The LLM doesn't need to call `create_directory` first.

### Large file outputs are truncated

Tool results are truncated at `max_tool_result_chars` (default 50,000 characters). The LLM sees a truncation notice and can use `offset`/`limit` to read specific sections.

### Binary files return descriptions, not content

`read_file` detects binary files and returns a size/type description instead of raw bytes. The LLM can't meaningfully process binary data.

---

## Skills

### Loading the same skill twice is a no-op

```python
agent.load_skill("files")
agent.load_skill("files")  # no effect — already loaded
```

Skills track their loaded state by name. Duplicate loading doesn't re-register tools or duplicate prompt sections.

### Skill not found raises RuntimeError

```python
agent.load_skill("nonexistent")  # RuntimeError: Skill 'nonexistent' not found
```

Skills are resolved by: `tiny_harness.skills.{name}` → direct import → file path.

### Skill prompt sections are appended, never replaced

Each `agent.load_skill()` appends to the Prompt. There's no way to remove a skill's prompt section without recreating the Agent.

---

## Streaming & Events

### Sync handlers in `agent.on()` work but don't await

```python
# ✅ Works — lambda is called but not awaited (sync)
agent.on("tool_start", lambda e: print(e.tool_name))

# ✅ Works with async handlers
async def my_handler(event):
    await save_to_db(event)
agent.on("tool_start", my_handler)
```

The `on()` method detects whether the handler is async and awaits accordingly.

### `run_stream()` raises RuntimeError if already running

```python
async for event in agent.run_stream("prompt"):
    # Cannot call agent.run() or agent.run_stream() here
    pass
```

Only one execution at a time. The concurrent check prevents state corruption.

### EventBus subscribers receive ALL events

When subscribing via `agent.events.subscribe()`, the handler receives every event type. Use `agent.on("type", handler)` for filtered subscriptions.

---

## Debugging

### Enable verbose event tracking

```python
agent.on("iteration", lambda e: print(f"[Iter {e.num}/{e.max}]"))
agent.on("tool_start", lambda e: print(f"  ⚡ {e.tool_name}"))
agent.on("tool_end", lambda e: print(f"  ← {e.content[:80]}"))
agent.on("error", lambda e: print(f"  ⚠ {e.message}"))
```

### Inspect the Conversation

```python
for msg in agent._messages.to_list():
    role = msg["role"]
    content = str(msg.get("content", ""))[:100]
    print(f"[{role}] {content}")
```

### Check registered tools

```python
for name in agent.tools.names():
    tool = agent.tools.get(name)
    print(f"{name}: {tool.definition.description}")
```

### Token usage estimate

```python
tokens = agent._messages.estimate_tokens()
print(f"~{tokens} tokens used (approximate)")
```
