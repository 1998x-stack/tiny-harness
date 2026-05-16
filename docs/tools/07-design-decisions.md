# Design Decisions: Tradeoffs, Patterns, and Anti-Patterns

## 1. Key Architectural Tradeoffs

### 1.1 Many Small Tools vs Few Powerful Tools

| Approach | Pros | Cons |
|---|---|---|
| **Many small tools** (`read_file`, `write_file`, `list_dir`, `file_exists`) | LLM composes precisely; each tool is simple; easy to sandbox | More tools to define; LLM must chain multiple calls; more iterations |
| **Few powerful tools** (`file_operation(action, path, content)`) | Fewer definitions; fewer LLM calls; single call does more | LLM must specify action enum correctly; harder to sandbox (one tool does everything); error messages less specific |

**Decision for MVP**: Many small tools. The LLM excels at composition ("read this, now write that, now verify"). Simple tools are easier to debug, sandbox, and explain. Composition cost (extra iterations) is low compared to the cost of the LLM misusing a powerful tool.

**Exception**: Shell command execution is inherently a "powerful tool" (`run_command`). It's the escape hatch. Everything that can be a dedicated tool should be; `run_command` is for everything else.

### 1.2 Tool State: Stateless vs Stateful

| Approach | Pros | Cons |
|---|---|---|
| **Stateless** | Each call independent; no hidden state; LLM has full context in messages | Must pass all context each time; no persistent connections |
| **Stateful** | Persistent connections; session-level state; fewer arguments | Hidden state confuses LLM; tool behavior changes over time; harder to debug |

**Decision**: Stateless by default. The messages array IS the state. If a tool needs persistent state (e.g., a database connection), make it explicit in the tool definition: "This tool opens a connection that persists for the session."

### 1.3 Sequential vs Parallel Execution

| Approach | Pros | Cons |
|---|---|---|
| **Sequential** | Simple; deterministic ordering; easy error handling | Slower for independent operations |
| **Parallel** | Faster; better resource utilization | Complex error handling (partial failures); non-deterministic ordering; harder to debug |

**Decision**: Sequential for MVP. The simplicity benefit outweighs the performance cost at small scale. The LLM can already express parallelism by calling tools in separate responses when dependencies exist. Add explicit parallel execution when profiling shows it's the bottleneck.

### 1.4 Strict vs Lenient Argument Validation

| Approach | Pros | Cons |
|---|---|---|
| **Strict** (reject unknown args, require all required) | Catches LLM mistakes early; predictable behavior | LLM may add "helpful" extra fields that break things |
| **Lenient** (ignore unknown args, apply defaults) | More forgiving; LLM can add context fields freely | Silent bugs when LLM passes wrong args that happen to be accepted |

**Decision**: Lenient for MVP. The LLM sometimes adds metadata fields (reasoning, context). Rejecting these is frustrating. But log warnings for unknown/extra fields so developers can spot patterns and tighten validation later.

### 1.5 Verbose vs Concise Tool Results

| Approach | Pros | Cons |
|---|---|---|
| **Verbose** (full output, all metadata) | LLM has complete information | Consumes context tokens; large results crowd out history |
| **Concise** (summary, truncated) | Preserves context; faster LLM processing | LLM may miss important details; may need to re-query |

**Decision**: Concise with truncation at ~50K characters. The LLM can always ask for more detail ("read the file again with a larger limit"). It's better to under-deliver and let the LLM ask for more than to silently overflow context.

---

## 2. Design Patterns

### 2.1 Tool Result Enrichment

Always include tool name and execution metadata in results:

```
Bad:  "File contents: ..."
Good: "[read_file] /tmp/data.json (150 lines, 4.2KB, took 12ms):
       File contents: ..."
```

This helps the LLM track which result came from which tool call, especially when multiple tools were called.

### 2.2 Suggestive Error Messages

Error messages are prompts. Make them actionable:

```
Bad:  "Error: EACCES"
Good: "Cannot write to '/etc/nginx.conf': permission denied.
       This file requires root access. Options:
       1. Write to a different location (e.g., ~/nginx.conf)
       2. Ask the user for elevated permissions
       3. Use a user-writable config directory"
```

### 2.3 Tool Composition Hints

In tool descriptions, hint at related tools:

```
description: "Read a file from disk. For listing directory contents,
              use list_directory first. For searching file contents,
              use search_code."
```

This helps the LLM discover the right tool for the job without trial and error.

### 2.4 Idempotency Where Possible

Design tools to be safe when called multiple times with the same arguments:

```
write_file: overwrites → idempotent (same file, same content = same result)
create_directory: exists_ok flag → idempotent
delete_file: ignore_missing flag → idempotent
```

Add an `idempotent: true` flag to the tool definition so the harness knows retries are safe.

### 2.5 Dry Run Mode

For destructive tools, add a `dry_run: boolean` parameter:

```
description: "Delete a file permanently. Set dry_run=true to see what
              would be deleted without actually deleting."
```

The LLM can use dry runs to verify intent before committing.

---

## 3. Common Anti-Patterns

### 3.1 The "Do Everything" Tool

```python
# BAD: One tool that does everything
def tool_execute(action: str, target: str, options: dict) -> str:
    if action == "read": ...
    elif action == "write": ...
    elif action == "delete": ...
    # ...

# GOOD: Separate tools
def read_file(path: str) -> str: ...
def write_file(path: str, content: str) -> str: ...
def delete_file(path: str) -> str: ...
```

**Why it's bad**: The LLM must correctly specify the `action` enum. If the LLM writes `action: "read"` but means to delete, there's no validation to catch it. Separate tools make the LLM's intent explicit.

### 3.2 Implicit State in Tool Results

```python
# BAD: Tool result references state the LLM can't see
def search_code(pattern: str) -> str:
    internal_results = do_search(pattern)
    self.last_search_results = internal_results  # Hidden state
    return f"Found {len(internal_results)} results. Use get_result(n) to retrieve."

# GOOD: Return results directly
def search_code(pattern: str) -> str:
    results = do_search(pattern)
    return json.dumps(results, indent=2)  # LLM sees everything
```

**Why it's bad**: The LLM doesn't know about `last_search_results`. It can't see or reason about hidden state. Everything the LLM needs must be in the messages array.

### 3.3 Over-Abstraction of Tool Handlers

```python
# BAD: Premature abstraction
class BaseTool(ABC):
    @abstractmethod
    def execute(self, args): ...

class FileReaderTool(BaseTool):
    def execute(self, args): ...

# GOOD: Simple functions
def read_file(path: str) -> str:
    return open(path).read()
```

**Why it's bad**: The tool handler is just a function. A base class, registry, decorators, and dependency injection are overkill for an MVP. A dictionary of `{name: (definition, function)}` is sufficient.

### 3.4 Validation in the Handler Instead of Schema

```python
# BAD: Manual validation in handler
def read_file(path: str, limit: int = None) -> str:
    if not isinstance(path, str):
        return "Error: path must be a string"
    if limit is not None and not isinstance(limit, int):
        return "Error: limit must be an integer"
    # ...

# GOOD: Schema validation before handler runs
tool = Tool(
    name="read_file",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"}
        },
        "required": ["path"]
    },
    handler=read_file
)
```

**Why it's bad**: Manual validation in every handler is repetitive, error-prone, and inconsistent. Schema validation is centralized, declarative, and the LLM can read schema errors to self-correct before the handler even runs.

### 3.5 Ignoring the Error-As-Result Pattern

```python
# BAD: Letting exceptions crash the agent
def read_file(path: str) -> str:
    return open(path).read()  # FileNotFoundError crashes the agent

# GOOD: Catch and format
async def execute_tool(tc: ToolCall) -> ToolResult:
    try:
        result = await handler(**tc.args)
        return ToolResult.success(tc.id, result)
    except Exception as e:
        return ToolResult.error(tc.id, f"Error: {e}")
```

**Why it's bad**: A single unhandled exception crashes the entire agent. Every error must become a tool result. The harness is a safety net.

### 3.6 Tools That Return Raw Stack Traces

```
Bad result:
  Traceback (most recent call last):
    File "handler.py", line 42, in read_file
      return open(path).read()
  FileNotFoundError: [Errno 2] No such file or directory: '/tmp/x.json'

Good result:
  File '/tmp/x.json' not found. Check the path and try again.
```

**Why it's bad**: Stack traces are for developers, not LLMs. The LLM can't parse tracebacks as effectively as a clear English description. Format errors for the LLM reader.

---

## 4. Concrete MVP Specification

### Tool System Core

```python
class ToolRegistry:
    """The tool registry — the only essential data structure."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        """Return all tool definitions as LLM-compatible JSON."""
        return [t.definition.to_llm_format() for t in self._tools.values()]

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())


@dataclass
class Tool:
    definition: ToolDef
    handler: Callable  # async (args: dict) -> Any


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict        # JSON Schema object
    risk_level: str = "read_only"  # "safe" | "read_only" | "mutation" | "destructive" | "dangerous"

    def to_llm_format(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
```

### Tool Executor

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry,
                 timeout_ms: int = 30_000,
                 max_output_chars: int = 50_000):
        self.registry = registry
        self.timeout_ms = timeout_ms
        self.max_output_chars = max_output_chars

    async def execute(self, tool_name: str, args: dict) -> ToolResult:
        tool = self.registry.get(tool_name)

        if tool is None:
            suggestions = self._suggest_names(tool_name)
            msg = f"Tool '{tool_name}' not found."
            if suggestions:
                msg += f" Did you mean: {', '.join(suggestions)}?"
            return ToolResult.error(msg)

        # Validate schema
        try:
            validated = self._validate(tool.definition.parameters, args)
        except ValidationError as e:
            return ToolResult.error(f"Invalid arguments: {e}")

        # Execute
        try:
            raw = await asyncio.wait_for(
                tool.handler(**validated),
                timeout=self.timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            return ToolResult.error(
                f"Tool '{tool_name}' timed out after {self.timeout_ms/1000}s"
            )
        except Exception as e:
            return ToolResult.error(f"Tool '{tool_name}' failed: {e}")

        # Format
        return ToolResult.success(self._format(raw))

    def _validate(self, schema: dict, args: dict) -> dict:
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(args))
        if errors:
            msg = "\n".join(f"  - {'/'.join(str(p) for p in e.path)}: {e.message}"
                          for e in errors)
            raise ValidationError(msg)
        # Apply defaults
        return self._apply_defaults(schema, args)

    def _format(self, result: Any) -> str:
        if result is None:
            return "Success."
        if isinstance(result, str):
            return truncate(result, self.max_output_chars)
        if isinstance(result, (dict, list)):
            return truncate(json.dumps(result, indent=2), self.max_output_chars)
        return truncate(str(result), self.max_output_chars)

    def _suggest_names(self, name: str) -> list[str]:
        """Suggest similar tool names for typos."""
        from difflib import get_close_matches
        return get_close_matches(name, self.registry.names(), n=3, cutoff=0.6)
```

### Complete MVP Agent Loop with Tool System

```python
class Agent:
    def __init__(self, model: str, system_prompt: str, tools: ToolRegistry):
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools
        self.executor = ToolExecutor(tools)
        self.max_iterations = 25

    async def run(self, user_message: str, event_bus=None) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]

        for iteration in range(self.max_iterations):
            # Call LLM with current messages + tool definitions
            response = await llm_generate(
                model=self.model,
                messages=messages,
                tools=self.tools.get_definitions()
            )

            # Stream text
            for chunk in response.text_chunks:
                if event_bus:
                    await event_bus.emit("text", chunk)

            # No tool calls = final answer
            if not response.tool_calls:
                return response.full_text

            # Announce + execute tools
            for tc in response.tool_calls:
                if event_bus:
                    await event_bus.emit("tool_start", tc.name, tc.arguments)

                result = await self.executor.execute(tc.name, tc.arguments)

                if event_bus:
                    await event_bus.emit("tool_end", tc.name, result.summary())

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content
                })

        return "Agent stopped: maximum iterations reached."
```

---

## 5. What NOT to Add (Yet)

These are features that seem necessary but are premature for an MVP tool system:

| Feature | Why Wait |
|---|---|
| Tool decorators / class-based tools | A dictionary is simpler and just as powerful |
| Tool dependency injection | Tools are functions; inject via closures if needed |
| Tool hot-reloading | Restart the agent to add tools |
| Tool versioning | Rename is sufficient (`read_file_v2`) |
| Tool discovery (scanning modules) | Explicit registration is clearer |
| Tool composition (chaining, pipelines) | The LLM composes tools; harness shouldn't |
| Tool analytics dashboard | Log to a file; analyze later |
| Multi-language tool SDK | One language per agent instance |
| Tool marketplace / sharing | Premature without a user base |

---

## 6. Summary: The Tool System's Philosophy

1. **Tools are the LLM's limbs** — design them to extend what the LLM can do, not to constrain it
2. **The definition is the contract** — JSON Schema tells the LLM what's possible; the handler does the work
3. **Errors are prompts** — every failure is an opportunity for the LLM to learn and self-correct
4. **Keep tools small and composable** — many simple tools > few complex tools
5. **Safety is metadata** — risk level, permissions, sandboxing are attributes of the definition
6. **Stream everything** — the user should see the agent thinking in real time
7. **The simplest thing works** — a dictionary of `{name: (definition, function)}` is a complete tool system
