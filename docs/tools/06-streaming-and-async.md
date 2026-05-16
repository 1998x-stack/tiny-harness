# Streaming, Async, and Long-Running Tools

## 1. The Problem: The Blank Screen

Without streaming, the agent experience is:

```
User: "Find all TODO comments in the codebase"
[30 seconds of silence...]
Agent: "Found 15 TODOs in 8 files: ..."
```

The user has no idea if the agent is working, stuck, or crashed. This is terrible UX.

With streaming, the same interaction:

```
User: "Find all TODO comments in the codebase"
Agent: Let me search the codebase for TODO comments.
       → Running: search_code(pattern="TODO", file_pattern="*.py")
       → Found 15 matches in 8 files...
Agent: Here's what I found: ...
```

The user sees the agent thinking, deciding, and executing in real time. Trust and engagement increase dramatically.

---

## 2. What to Stream

The agent loop produces several types of events that should be streamed:

### 2.1 LLM Text Output

As the LLM generates text, stream chunks immediately:

```
"Let me search for that..."
"Looking at the results now..."
"I found several TODOs..."
```

This is handled by the LLM provider's streaming API. The harness passes chunks through without buffering.

### 2.2 Tool Call Announcements

Before executing a tool, announce it:

```
→ Calling tool: search_code
  pattern: "TODO"
  file_pattern: "*.py"
```

This tells the user what's happening and enables them to interrupt if the LLM is about to do something wrong.

### 2.3 Tool Progress (Long-Running)

For tools that take significant time:

```
→ Running: run_tests (this may take 30-60 seconds)
  [========>           ] 45% — 12/27 tests passed
```

### 2.4 Tool Results (Summarized)

After execution, show a summary:

```
← search_code returned 15 matches in 8 files (took 1.2s)
```

### 2.5 Iteration Metadata

```
[Iteration 3/25 | Tokens: 4,200/200,000]
```

---

## 3. Streaming Architecture

### 3.1 Event Model

Define a standard set of stream events:

```typescript
type StreamEvent =
  | { type: "text_delta", content: string }           // LLM text chunk
  | { type: "tool_call_start", tool: string, args: object }  // About to execute
  | { type: "tool_progress", tool: string, message: string }  // Progress update
  | { type: "tool_call_end", tool: string, result_summary: string, duration_ms: number }
  | { type: "iteration", num: number, tokens_used: number }
  | { type: "error", message: string }
  | { type: "done", final_answer: string }
```

### 3.2 Event Bus

```python
class AgentEventBus:
    def __init__(self):
        self._handlers: list[callable] = []

    def on_event(self, handler: callable):
        """Register an event handler. Handler receives StreamEvent."""
        self._handlers.append(handler)

    async def emit(self, event: StreamEvent):
        for handler in self._handlers:
            await handler(event)

# Built-in handlers
def console_handler(event: StreamEvent):
    """Print events to console in a human-friendly format."""
    match event:
        case {"type": "text_delta", "content": text}:
            print(text, end="", flush=True)
        case {"type": "tool_call_start", "tool": tool, "args": args}:
            print(f"\n→ Calling: {tool}({json.dumps(args, indent=2)})")
        case {"type": "tool_call_end", "tool": tool, "result_summary": summary, "duration_ms": ms}:
            print(f"← {tool} returned ({ms}ms): {summary}")
        case {"type": "error", "message": msg}:
            print(f"\n⚠ {msg}")
```

---

## 4. Long-Running Tools

### 4.1 The Problem

Some tools take seconds or minutes:
- `run_tests`: 30-120 seconds
- `build_project`: 20-60 seconds
- `search_codebase`: 5-30 seconds for large repos
- `fetch_url`: Variable, network-dependent
- `transform_large_file`: Dependent on file size

During execution, the agent appears frozen. The user has no feedback.

### 4.2 Progress Reporting

Tools can report progress via callbacks:

```python
@dataclass
class ToolContext:
    """Context passed to tool handlers for progress reporting."""
    tool_call_id: str
    report_progress: Callable[[str], None]  # Send progress message

async def run_tests(args: dict, ctx: ToolContext) -> str:
    ctx.report_progress("Discovering tests...")
    tests = discover_tests()

    passed = 0
    for i, test in enumerate(tests):
        result = run_test(test)
        if result.passed:
            passed += 1
        ctx.report_progress(f"[{passed}/{i+1}] {test.name}: {'PASS' if result.passed else 'FAIL'}")

    return f"Tests complete: {passed}/{len(tests)} passed"
```

### 4.3 Tool Timeouts

Every tool must have a timeout. Never let a tool hang indefinitely:

```python
class TimeoutConfig:
    default: int = 30_000        # 30 seconds
    per_tool: dict[str, int] = {  # Override per tool
        "run_tests": 120_000,     # 2 minutes
        "build_project": 300_000, # 5 minutes
        "search_codebase": 30_000,
    }

async def execute_with_timeout(tool: Tool, args: dict) -> str:
    timeout = TimeoutConfig.per_tool.get(tool.name, TimeoutConfig.default)
    try:
        return await asyncio.wait_for(
            tool.handler(**args),
            timeout=timeout / 1000
        )
    except asyncio.TimeoutError:
        return f"Tool '{tool.name}' timed out after {timeout/1000}s"
```

---

## 5. Parallel Tool Execution

### 5.1 When to Parallelize

The LLM sometimes calls multiple tools in one response:

```
LLM: "Let me read three files in parallel."
  → tool_calls: [
      { name: "read_file", args: { path: "a.py" } },
      { name: "read_file", args: { path: "b.py" } },
      { name: "read_file", args: { path: "c.py" } },
    ]
```

These calls are independent — reading `a.py` doesn't depend on reading `b.py`. They can run in parallel.

### 5.2 Parallel Execution

```python
async def execute_tool_calls(tool_calls: list[ToolCall]) -> list[ToolResult]:
    """Execute independent tool calls in parallel."""
    tasks = [
        execute_single_tool(tc)
        for tc in tool_calls
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    formatted = []
    for tc, result in zip(tool_calls, results):
        if isinstance(result, Exception):
            formatted.append(ToolResult.error(tc.id, str(result)))
        else:
            formatted.append(result)

    return formatted
```

### 5.3 Sequential vs Parallel Decision

| Pattern | When | Example |
|---|---|---|
| **Parallel** | Independent tools, no shared state | Read 3 files, search 2 patterns |
| **Sequential** | Tool B depends on Tool A's result | Read a file, then write based on content |
| **Interleaved** | Some parallel, some sequential | Read config, then write 3 files in parallel |

The LLM can signal dependencies by splitting tool calls across multiple responses:

```
Response 1: read_file("config.json")          # Single tool call
Response 2: write_file("a.py", ...),           # Three parallel calls
            write_file("b.py", ...),           # (all depend on config content)
            write_file("c.py", ...)
```

### 5.4 MVP Decision

For MVP: execute tool calls sequentially within a single LLM response. Parallel execution adds complexity (ordering, error handling when one of N fails, result interleaving) without being essential. Add it when you observe the performance bottleneck.

---

## 6. Cancellation and Interruption

### 6.1 User Interrupts the Agent

The user should be able to stop the agent at any time:
- Ctrl+C or equivalent signal
- Stop button in UI

On interrupt:
1. Cancel in-flight LLM calls
2. Cancel in-flight tool executions
3. Return partial results or "Interrupted" message

### 6.2 Implementation

```python
class CancellationToken:
    def __init__(self):
        self._cancelled = False
        self._event = asyncio.Event()

    def cancel(self):
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def wait_if_not_cancelled(self):
        """Check cancellation before proceeding."""
        if self._cancelled:
            raise CancelledError()

class AgentLoop:
    async def run(self, prompt: str, cancel_token: CancellationToken) -> str:
        for i in range(self.max_iterations):
            cancel_token.wait_if_not_cancelled()

            response = await self.llm.generate(messages, tools)
            cancel_token.wait_if_not_cancelled()

            if response.is_final():
                return response.text

            for tc in response.tool_calls:
                cancel_token.wait_if_not_cancelled()
                result = await self.tools.execute(tc, cancel_token)
                messages.append(result)

        return "Max iterations reached"
```

---

## 7. Streaming in the Agent Loop

The complete streaming agent loop:

```python
async def run_streaming(self, prompt: str, event_bus: EventBus) -> str:
    messages = [
        {"role": "system", "content": self.system_prompt},
        {"role": "user", "content": prompt}
    ]

    for iteration in range(self.max_iterations):
        await event_bus.emit({"type": "iteration", "num": iteration + 1})

        # Stream LLM text as it generates
        tool_calls = []
        async for chunk in self.llm.stream(messages, self.tool_defs):
            if chunk.type == "text":
                await event_bus.emit({"type": "text_delta", "content": chunk.text})
            elif chunk.type == "tool_call":
                tool_calls.append(chunk.tool_call)

        # If final answer (text, no tools): done
        if not tool_calls:
            return  # streaming already delivered the answer

        messages.append(format_assistant_message(tool_calls))

        # Execute tools with progress
        for tc in tool_calls:
            await event_bus.emit({
                "type": "tool_call_start",
                "tool": tc.name,
                "args": tc.arguments
            })

            start = time.time()
            result = await self.tools.execute(tc)
            duration = int((time.time() - start) * 1000)

            await event_bus.emit({
                "type": "tool_call_end",
                "tool": tc.name,
                "result_summary": result.content[:100],
                "duration_ms": duration
            })

            messages.append(result)

    await event_bus.emit({"type": "error", "message": "Max iterations reached"})
```

---

## 8. MVP Decisions

| Decision | Rationale |
|---|---|
| Stream LLM text chunks immediately | Essential UX — user sees thinking in real time |
| Announce tool calls before execution | Transparency; user can interrupt before side effects |
| Summarize tool results (not full output) | Keep console clean; full output goes to context |
| Timeout on every tool (30s default) | Prevent hangs; per-tool overrides for known slow tools |
| Sequential tool execution | Simpler; add parallel when performance demands it |
| Console event handler built-in | MVP just prints to console; later can be JSON/webhook |
| Ctrl+C cancellation | Standard Unix signal handling |
| No progress callbacks in MVP | Tool handlers are plain functions; add ToolContext later |
