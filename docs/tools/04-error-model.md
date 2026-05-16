# Error Model

## 1. The Fundamental Insight: Errors Are Results

In a traditional program, when a function fails, you throw an exception up the call stack. The caller catches it and handles it — or the program crashes.

In a tool system, **the caller is an LLM**. It can't catch exceptions. But it CAN read error messages and self-correct.

This means the error model is inverted:

```
Traditional:  error → throw → crash or catch → handle
Tool System:  error → catch → format as message → feed to LLM → LLM self-corrects
```

**Every error becomes a tool result message.** The harness never crashes because a tool failed. The harness catches everything, formats it, and hands it back to the LLM as input.

---

## 2. Error Taxonomy

Tool system errors fall into five categories, ordered by when they occur in the lifecycle:

### 2.1 Pre-Execution Errors (Validation)

These happen before the handler runs. They mean the LLM made a mistake in its tool call.

| Error | Cause | LLM Can Fix? |
|---|---|---|
| **Tool Not Found** | LLM called a tool that doesn't exist (typo, hallucination) | Usually — suggest correct name |
| **Schema Validation** | Arguments don't match schema (wrong type, missing required) | Always — provide expected schema |
| **Permission Denied** | Tool requires approval or has policy restrictions | Sometimes — try different approach |
| **Rate Limited** | Too many calls (harness-level throttling) | Yes — wait and retry |

### 2.2 Execution Errors (Runtime)

These happen during handler execution. They mean the world didn't cooperate.

| Error | Cause | LLM Can Fix? |
|---|---|---|
| **Resource Not Found** | File missing, URL 404, database row deleted | Usually — try different path/ID |
| **Permission Error (OS)** | Process lacks filesystem/network permissions | Sometimes — try different location |
| **Invalid State** | Operation impossible in current state (e.g., delete non-empty dir) | Yes — change approach |
| **External Failure** | API down, network timeout, DNS failure | Sometimes — retry, use fallback |

### 2.3 Harness Errors (Infrastructure)

These are harness-level failures, not tool failures.

| Error | Cause | LLM Can Fix? |
|---|---|---|
| **Timeout** | Tool exceeded time limit | Sometimes — reduce scope |
| **Output Overflow** | Result too large for context | Yes — use more specific query |
| **Loop Detected** | LLM calling same tool repeatedly | No — harness should terminate |
| **System Error** | Harness bug (null pointer, etc.) | No — bug in harness code |

---

## 3. Error Message Design

### 3.1 The Golden Rule

**Write error messages that help the LLM fix its mistake.**

The LLM reads the error as input. A good error message:
1. States what went wrong (factual)
2. Explains why (actionable context)
3. Suggests what to do instead (guidance)
4. Shows what was expected (schema, format, constraints)

### 3.2 Examples: Bad vs Good

**Tool Not Found**
```
Bad:  "Tool not found"
Good: "Tool 'read_fil' not found. Did you mean 'read_file'?
       Available tools: read_file, write_file, search_code, run_command.
       Check the tool name spelling and try again."
```

**Schema Validation**
```
Bad:  "Invalid arguments"
Good: "Invalid arguments for 'read_file':
       - 'path' is required but was not provided
       - 'offset' should be an integer, got string 'abc'

       Expected: { path: string, offset?: integer, limit?: integer }
       Required fields: [path]"
```

**File Not Found**
```
Bad:  "ENOENT: no such file or directory"
Good: "File '/tmp/missing.json' not found.
       The file does not exist at this path. Possible causes:
       - Typo in the filename
       - Wrong directory
       - File was deleted or moved

       Try listing the directory first: list_directory('/tmp/')
       Or check if you meant: /tmp/data.json (similar name found)"
```

**Permission Denied**
```
Bad:  "Permission denied"
Good: "Cannot write to '/etc/config.json': permission denied.
       This path requires elevated privileges.
       Consider writing to a different location, such as '/tmp/' or '~/'.
       If you need to modify system files, ask the user for elevated access."
```

**Timeout**
```
Bad:  "Timeout"
Good: "Tool 'run_command' timed out after 30 seconds.
       The command may be hanging or processing too much data.
       Try: reduce the scope of the operation, add a filter, or
       break the task into smaller steps."
```

### 3.3 Structure Pattern

Every error message should follow this structure:

```
[WHAT] Tool 'X' failed: <specific reason>
[WHY] <context that explains why this happened in terms the LLM understands>
[FIX] <actionable suggestion for what to try instead>
```

---

## 4. Error-to-Result Conversion

### 4.1 The Conversion Function

```python
def error_to_result(tool_call_id: str, error: ToolError) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id,
        content=format_error(error)
    )

def format_error(error: ToolError) -> str:
    """Format an error as a message the LLM can learn from."""
    parts = [f"Tool '{error.tool_name}' failed: {error.message}"]

    if error.suggestion:
        parts.append(f"Suggestion: {error.suggestion}")

    if error.details:
        parts.append(f"Details: {error.details}")

    if error.expected_schema:
        parts.append(f"Expected: {json.dumps(error.expected_schema, indent=2)}")

    return "\n".join(parts)
```

### 4.2 The Structured Error Type

```python
@dataclass
class ToolError:
    tool_name: str
    category: str          # "not_found" | "validation" | "execution" | "timeout"
    message: str           # Human-readable error description
    suggestion: str | None # What the LLM should try instead
    details: str | None    # Additional technical details
    expected_schema: dict | None  # Schema that was expected (for validation errors)
    is_recoverable: bool   # Can the LLM fix this by changing its approach?
```

---

## 5. Recovery Patterns

### 5.1 LLM Self-Correction

The primary recovery mechanism: the LLM reads the error and adjusts.

```
Iteration 1: LLM calls read_file("/tmp/missing.json")
           → Error: "File not found. Did you mean /tmp/data.json?"
Iteration 2: LLM reads error, calls read_file("/tmp/data.json")
           → Success: file contents returned
```

This works because the LLM is a reasoning system. It can interpret error messages, learn from mistakes, and try alternatives — just like a human developer reading error output.

### 5.2 When Self-Correction Fails

The LLM may get stuck in a loop: try A → fail → try A again → fail → try A again...

**Detection**: Track identical tool calls (same tool + same arguments) across iterations. If a call repeats N times (e.g., 3), the LLM is stuck.

**Response options**:
1. **Warn the LLM**: "You have called 'read_file' with path='/tmp/missing.json' 3 times. Each time it failed with 'File not found'. Please try a different approach."
2. **Force escalation**: Terminate the agent and return partial results + the error loop.
3. **Auto-vary**: For certain errors (like timeouts), the harness could auto-retry with smaller scope before giving the LLM the error.

### 5.3 Non-Recoverable Errors

Some errors should terminate the agent immediately:

- **Authentication failures**: API key invalid, token expired. Nothing the LLM can do.
- **Harness bugs**: Null reference, type error in harness code. This is a bug, not a tool failure.
- **Resource exhaustion**: Out of memory, disk full. The environment is broken.
- **Safety violations**: Tool attempted something explicitly forbidden by policy.

For these, terminate the loop with a clear message to the user.

---

## 6. The Error Budget

An agent should have an **error budget** — a maximum number of tool failures before termination. This prevents runaway error loops:

```python
class ErrorBudget:
    def __init__(self, max_total=10, max_consecutive=3):
        self.total = 0
        self.consecutive = 0
        self.max_total = max_total
        self.max_consecutive = max_consecutive

    def record_error(self) -> bool:
        self.total += 1
        self.consecutive += 1
        return self.total < self.max_total and self.consecutive < self.max_consecutive

    def record_success(self):
        self.consecutive = 0  # reset consecutive counter on success

    def is_exhausted(self) -> bool:
        return self.total >= self.max_total or self.consecutive >= self.max_consecutive
```

---

## 7. Error Handling in the Agent Loop

```python
error_budget = ErrorBudget(max_total=10, max_consecutive=3)

while not done and iterations < max_iterations:
    response = llm.generate(messages, tools)

    if response.is_final():
        return response.text

    messages.append(response.as_message())

    for tool_call in response.tool_calls:
        result = execute_tool_call(tool_call, registry)

        if not result.success:
            if not error_budget.record_error():
                messages.append(ToolResultMessage(
                    tool_call_id=tool_call.id,
                    content="Error budget exhausted. Too many tool failures. "
                            "Please provide a final answer based on what you know."
                ))
                # Give LLM one more chance to respond without tools
                response = llm.generate(messages, tools=[])
                return response.text

        else:
            error_budget.record_success()

        messages.append(result)
```

---

## 8. MVP Decisions

| Decision | Rationale |
|---|---|
| All errors become tool results | LLM self-corrects; never crash the agent |
| Categorized errors (5 types) | Each needs different formatting and recovery |
| Structured error messages (what/why/fix) | LLM needs actionable information, not stack traces |
| Error budget (consecutive + total) | Simple, effective loop prevention |
| Loop detection via identical call tracking | Catches the most common failure mode |
| Non-recoverable → terminate | Auth failures, harness bugs, safety violations must stop the agent |
| No automatic retry in the harness | Let the LLM decide to retry; harness just reports errors |
