# Agent Loop: Core Mechanics

## 1. What Is the Agent Loop?

The agent loop is the **central orchestrator** of the entire harness. It's the while-loop that keeps the agent running until it produces a final answer or hits a safety limit.

From first principles, the loop does exactly one thing:

```
while the agent hasn't finished:
    1. Ask the LLM what to do next
    2. If it gives a final answer → we're done
    3. If it wants to use tools → execute them, feed results back, try again
```

Nothing else. The loop itself contains **zero intelligence** — it's a mechanical pump that moves data between the LLM and the tool system. All reasoning happens in the LLM. All execution happens in the tool handlers. The loop just connects them.

---

## 2. The Loop as a State Machine

The agent has exactly four states:

```
                  ┌──────────┐
                  │  IDLE    │
                  └────┬─────┘
                       │ run(prompt)
                       ▼
                  ┌──────────┐
          ┌──────▶│ THINKING │──────┐
          │       └────┬─────┘      │
          │            │            │
          │   final    │   tool     │
          │   answer   │   calls    │
          │            ▼            │
          │       ┌──────────┐      │
          │       │ EXECUTING│      │
          │       └────┬─────┘      │
          │            │            │
          │   results  │            │
          │   injected  │            │
          │            ▼            │
          │       ┌──────────┐      │
          └───────│   LOOP   │──────┘
                  └──────────┘
                       │
                       │ max iterations / error budget exhausted
                       ▼
                  ┌──────────┐
                  │   DONE   │
                  └──────────┘
```

### State Descriptions

| State | What's happening | Transitions |
|---|---|---|
| **IDLE** | Agent created, waiting for a task | `run(prompt)` → THINKING |
| **THINKING** | LLM generating response (streaming text/tool calls) | Final answer → DONE; Tool calls → EXECUTING |
| **EXECUTING** | Running tool handlers, collecting results | Results ready → LOOP |
| **LOOP** | Results injected into messages, preparing next iteration | Iteration < max → THINKING; Iteration ≥ max → DONE |
| **DONE** | Agent has terminated | Return final answer or error |

---

## 3. The Core Loop in Detail

### 3.1 Pseudocode

```python
async def agent_loop(prompt: str, config: Config) -> str:
    # Initialize
    messages = Messages()
    messages.add_system(config.system_prompt)
    messages.add_user(prompt)

    iteration = 0
    error_budget = ErrorBudget(
        max_total=config.max_total_errors,
        max_consecutive=config.max_consecutive_errors
    )

    # Main loop
    while iteration < config.max_iterations:
        iteration += 1

        # === PHASE 1: THINK ===
        try:
            response = await llm.generate(
                model=config.model,
                messages=messages.to_api_format(),
                tools=config.tools.get_definitions()
            )
        except LLMError as e:
            # Non-recoverable LLM error → terminate
            return f"Agent stopped: LLM error on iteration {iteration}: {e}"

        # Stream text output to user
        for chunk in response.text_chunks:
            yield chunk  # or emit to event bus

        # === PHASE 2: CHECK EXIT ===
        if response.is_final_answer():
            return response.full_text

        # === PHASE 3: EXECUTE TOOLS ===
        messages.add_assistant(response)  # preserves tool_calls

        for tool_call in response.tool_calls:
            result = await tool_executor.execute(
                name=tool_call.name,
                args=tool_call.arguments,
                call_id=tool_call.id
            )

            # Track errors for budget
            if not result.success:
                if not error_budget.record_error():
                    messages.add_tool_result(ToolResult.error(
                        tool_call.id,
                        "Error budget exhausted. Please provide a final answer "
                        "based on what you know so far, without using more tools."
                    ))
                    # One more LLM call to get final answer without tools
                    response = await llm.generate(
                        model=config.model,
                        messages=messages.to_api_format(),
                        tools=[]  # No tools allowed
                    )
                    return response.full_text
            else:
                error_budget.record_success()

            messages.add_tool_result(result)

        # === PHASE 4: LOOP ===
        # Implicit: next iteration of while loop calls LLM again
        # with updated messages (including tool results)

    # Exhausted iterations
    return f"Agent stopped: exceeded maximum iterations ({config.max_iterations})"
```

### 3.2 Why This Structure?

The four-phase structure (THINK → CHECK → EXECUTE → LOOP) cleanly separates concerns:

- **THINK**: All LLM interaction. Any LLM error here is a loop-level failure.
- **CHECK**: The only exit decision. Single point of control for termination.
- **EXECUTE**: All tool interaction. Tool errors are handled here, not in THINK.
- **LOOP**: Implicit. The while loop naturally cycles back.

This separation makes the loop debuggable. If the agent gets stuck, you know exactly which phase to inspect.

---

## 4. Stop Conditions

The loop terminates under these conditions, in priority order:

### 4.1 Normal Termination

| Condition | Trigger | Result |
|---|---|---|
| **Final answer** | LLM returns text without tool calls | Success — return the text |
| **Explicit stop** | LLM calls a `stop` tool or equivalent | Success — return stop message |
| **Task complete signal** | LLM's text contains a completion marker | Success — return the text |

### 4.2 Safety Termination

| Condition | Trigger | Result |
|---|---|---|
| **Max iterations** | `iteration >= config.max_iterations` | Truncation — return partial results + warning |
| **Error budget exhausted** | Too many consecutive or total tool errors | Degradation — ask LLM for final answer without tools |
| **Context overflow** | Messages exceed token limit | Degradation — compact context, continue, or terminate |
| **User interrupt** | Ctrl+C, stop button, cancellation token | Interruption — return partial results |

### 4.3 Failure Termination

| Condition | Trigger | Result |
|---|---|---|
| **LLM unavailable** | Provider returns fatal error (auth, quota, etc.) | Failure — return error to user |
| **Harness error** | Bug in the harness code (null pointer, etc.) | Failure — crash with traceback (harness bug = crash) |

---

## 5. State Management Across Iterations

### 5.1 What State Exists?

The agent loop has exactly three pieces of mutable state:

```python
@dataclass
class LoopState:
    messages: MessageManager       # The LLM's working memory
    iteration: int = 0             # Current iteration counter
    tool_call_history: list[ToolCallRecord] = field(default_factory=list)
```

That's it. Everything else is derived or immutable.

### 5.2 State That Does NOT Exist

The loop does NOT maintain:
- **Task plans**: The LLM plans; the loop doesn't need to know the plan
- **Goals or subgoals**: The LLM tracks progress; the loop is agnostic
- **Memory outside messages**: No vector DB, no session storage (MVP)
- **Performance metrics**: Collected externally via event bus, not in the loop
- **Tool results cache**: Every result goes into messages; no separate cache

### 5.3 Why Minimal State?

The loop should be as dumb as possible. Every piece of state in the loop is a potential source of bugs and a deviation from the "LLM does all reasoning" principle. If the loop starts tracking plans, it starts making decisions about what to do — that's the LLM's job.

---

## 6. Iteration Management

### 6.1 Why Limit Iterations?

Without a limit, a confused LLM could loop forever:
- Tool always fails → LLM retries same approach → fails again → forever
- LLM generates tool calls that produce no progress → infinite busywork
- LLM hallucinates tasks → keeps doing unnecessary work

The iteration cap is a **safety valve**, not a performance optimization. It ensures the agent always terminates.

### 6.2 Choosing the Limit

| Complexity | Typical iterations | Max setting |
|---|---|---|
| Simple query (read file, answer) | 1-3 | 10 |
| Medium task (read, analyze, write) | 3-8 | 25 |
| Complex task (multi-file, multi-step) | 8-20 | 50 |
| Autonomous (open-ended) | 20-50+ | 100 |

**MVP default**: 25 iterations. Covers 95% of tasks. Adjustable per agent instance.

### 6.3 Iteration Warnings

Warn before hitting the limit:

```python
if iteration >= config.max_iterations * 0.8:
    messages.add_system(
        f"[System] You have {config.max_iterations - iteration} iterations remaining. "
        f"Prioritize delivering a final answer."
    )
```

This gives the LLM a chance to wrap up before the hard cutoff.

---

## 7. Error Recovery in the Loop

### 7.1 Three Categories of Loop Errors

| Category | Example | Loop Response |
|---|---|---|
| **Recoverable** | Tool timeout, file not found | Tool error → result → LLM self-corrects |
| **Degradable** | Error budget exhausted, context nearly full | Restrict tools/context, ask LLM for final answer |
| **Fatal** | LLM API down, auth failed, harness bug | Terminate immediately |

### 7.2 The Error Budget

```python
class ErrorBudget:
    def __init__(self, max_total: int = 10, max_consecutive: int = 3):
        self.total_errors = 0
        self.consecutive_errors = 0
        self.max_total = max_total
        self.max_consecutive = max_consecutive

    def record_error(self) -> bool:
        """Record an error. Returns False if budget exhausted."""
        self.total_errors += 1
        self.consecutive_errors += 1

        if self.consecutive_errors >= self.max_consecutive:
            return False  # too many in a row — LLM is stuck
        if self.total_errors >= self.max_total:
            return False  # too many overall — task might be impossible
        return True

    def record_success(self):
        """Reset consecutive counter on success."""
        self.consecutive_errors = 0
```

### 7.3 Loop Detection

If the LLM makes identical tool calls repeatedly, it's stuck:

```python
class LoopDetector:
    def __init__(self, max_repeats: int = 3):
        self.recent_calls: deque = deque(maxlen=10)
        self.max_repeats = max_repeats

    def check(self, tool_name: str, args: dict) -> bool:
        """Returns True if this exact call has been made too many times."""
        signature = (tool_name, json.dumps(args, sort_keys=True))
        self.recent_calls.append(signature)

        count = sum(1 for c in self.recent_calls if c == signature)
        if count >= self.max_repeats:
            return False  # Stuck in a loop
        return True
```

---

## 8. Performance Considerations

### 8.1 The Critical Path

The LLM call dominates loop time. A single LLM call takes 1-30 seconds. Tool execution takes 0.01-120 seconds. The loop overhead itself is negligible (<1ms).

**Optimization priority**: Reduce LLM calls, not loop iterations. A loop iteration with no tool calls is cheap (the LLM call is the cost). A loop iteration with many tool calls is still bounded by the LLM call.

### 8.2 Batching Tool Calls

If the LLM requests tools A, B, C in one response, execute them sequentially (or in parallel if independent). The key insight: one LLM call → N tool executions → one result injection is more efficient than N separate LLM calls.

### 8.3 Early Exit

The LLM might produce a final answer in the same response as tool calls:

```
Response: "I found the data. Here's the answer: ..."
           + tool_calls: []  (no tools needed)
```

This is the fastest path: one LLM call, zero tool executions, done. Design the system prompt to encourage the LLM to answer directly when it already knows the answer.

---

## 9. The Complete MVP Loop

```python
class AgentLoop:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.messages = MessageManager(config.system_prompt)
        self.tool_executor = ToolExecutor(config.tools)
        self.llm = LLMProvider(config.model)
        self.event_bus = EventBus()

    async def run(self, user_prompt: str) -> str:
        self.messages.add_user(user_prompt)

        iteration = 0
        error_budget = ErrorBudget(
            max_total=self.config.max_errors,
            max_consecutive=self.config.max_consecutive_errors
        )
        loop_detector = LoopDetector()

        while iteration < self.config.max_iterations:
            iteration += 1
            await self.event_bus.emit("iteration", {"num": iteration})

            # --- THINK ---
            try:
                response = await self.llm.generate(
                    messages=self.messages.to_list(),
                    tools=self.config.tools.get_definitions()
                )
            except FatalLLMError as e:
                return f"Fatal: {e}"
            except RetryableLLMError as e:
                # Let LLM error handling manage retries
                return f"LLM error: {e}"

            await self.event_bus.emit("text", response.text)

            # --- CHECK ---
            if response.is_final():
                return response.text

            # --- EXECUTE ---
            self.messages.add_assistant(response)

            for tc in response.tool_calls:
                # Loop detection
                if not loop_detector.check(tc.name, tc.arguments):
                    result = ToolResult.error(
                        tc.id,
                        f"You've called '{tc.name}' with the same arguments "
                        f"{loop_detector.max_repeats} times. It keeps failing. "
                        f"Try a fundamentally different approach."
                    )
                else:
                    result = await self.tool_executor.execute(tc.name, tc.arguments)

                # Error budget
                if not result.success:
                    if not error_budget.record_error():
                        return await self._degraded_finish()
                else:
                    error_budget.record_success()

                self.messages.add_tool_result(result)

            # --- LOOP (implicit) ---

        # Max iterations
        return await self._timeout_finish()

    async def _degraded_finish(self) -> str:
        """Error budget exhausted. Try to get a final answer without tools."""
        self.messages.add_system(
            "You've encountered too many errors. Please provide your best "
            "final answer based on what you know, without using any tools."
        )
        response = await self.llm.generate(
            messages=self.messages.to_list(),
            tools=[]  # No tools allowed
        )
        return response.text

    async def _timeout_finish(self) -> str:
        """Max iterations reached. Try to get a final answer."""
        self.messages.add_system(
            f"You've reached the maximum number of iterations "
            f"({self.config.max_iterations}). Please provide your final answer now."
        )
        response = await self.llm.generate(
            messages=self.messages.to_list(),
            tools=[]
        )
        return response.text
```

---

## 10. Testing the Loop

### 10.1 What to Test

| Test | What it verifies |
|---|---|
| Single iteration, no tools | LLM answers directly → loop exits with answer |
| Single iteration, one tool | LLM calls tool → tool executes → LLM answers → loop exits |
| Multi-iteration | LLM calls tool, gets result, calls another tool, answers |
| Max iterations hit | Loop terminates with timeout message, not infinite loop |
| Error budget exhausted | Loop degrades gracefully, asks for final answer |
| Loop detection | Repeated identical failing tool call → loop intervenes |
| User interrupt | Cancellation token → loop exits with partial results |
| LLM fatal error | Auth failure → loop terminates with error message |
| Empty tool calls | LLM returns text only → loop exits (no tool execution) |
| Tool not found | LLM calls nonexistent tool → error result → LLM self-corrects |

### 10.2 Test Harness

```python
async def test_simple_answer():
    """LLM answers directly without tools."""
    mock_llm = MockLLM(responses=["Hello! I can help with that."])
    mock_tools = ToolRegistry()

    loop = AgentLoop(config=AgentConfig(
        model="test-model",
        system_prompt="You are helpful.",
        tools=mock_tools,
        max_iterations=5
    ))
    loop.llm = mock_llm

    result = await loop.run("Say hello")
    assert "Hello" in result
    assert mock_llm.call_count == 1  # Only one LLM call
```

---

## 11. MVP Decisions

| Decision | Rationale |
|---|---|
| 4-phase structure (THINK→CHECK→EXECUTE→LOOP) | Clean separation; easy to debug each phase |
| Max iterations: 25 (default) | Covers 95% of tasks; adjustable per instance |
| Error budget: 10 total / 3 consecutive | Prevents runaway error loops; degrades gracefully |
| Loop detection: 3 identical calls | Catches stuck LLM without false positives |
| Degraded finish on exhaustion | One more LLM call without tools → possible partial answer |
| No planning state in the loop | All planning is LLM reasoning; loop is mechanical |
| No tool retry in the loop | LLM decides to retry; harness just reports errors |
| Event bus for observability | Loop emits events; external handlers display/log |
