# Tool System: First Principles

## 1. What Is a Tool? (LLM's Perspective)

An LLM without tools is a **brain in a jar** — it can reason, plan, and respond, but it cannot *act*. It's purely a text → text function.

A **tool** gives the LLM a limb. It says: "Here is something you can actually *do* in the world." The LLM doesn't execute the tool — it *requests* execution. The harness does the actual work.

This distinction is fundamental:

```
LLM: "I want to read the file at /tmp/data.json"
        │
        ▼  (tool call request: { name: "read_file", args: { path: "/tmp/data.json" } })
        │
HARNESS: opens("/tmp/data.json") → reads content → returns result
        │
        ▼  (tool result: "Success. Content: { ... }")
        │
LLM: "Great, now I can see the data. Let me analyze it..."
```

The LLM never touches the filesystem. It never makes HTTP requests. It never runs code. It only *decides what should happen*, and the harness makes it happen.

**Corollary**: The tool system is the **interface between cognition (LLM) and action (harness)**. Its quality determines what the agent can accomplish. A bad tool system cripples even the smartest model.

---

## 2. The Three Parts of Every Tool

Every tool in any system can be decomposed into exactly three orthogonal concerns:

### 2.1 Definition (What the LLM sees)

The tool definition is the **contract** exposed to the LLM. It answers:
- What does this tool do? (name + description)
- What information does it need? (parameters schema)
- Is it safe/reversible? (optional metadata)

The definition shapes the LLM's decision-making. If the description is wrong, the LLM will misuse the tool. If the schema is wrong, the LLM will generate invalid arguments.

### 2.2 Implementation (What the harness runs)

The implementation is the **actual code** that executes when the LLM invokes the tool. It is completely opaque to the LLM — the LLM only sees the definition and the result.

This separation is powerful: you can swap implementations without changing how the LLM interacts with the tool. You can add caching, logging, rate limiting, or even replace a real implementation with a mock — the LLM never knows.

### 2.3 Result (What flows back to the LLM)

The result is the **feedback** the LLM receives after execution. It can be:
- **Success**: "File read successfully. Content: { ... }"
- **Error**: "File not found: /tmp/data.json"
- **Partial**: "Read 1000 of 5000 lines (truncated)"

The result format determines whether the LLM can self-correct. A good error message helps the LLM fix its mistake. A bad one ("Error.") is useless.

---

## 3. The Tool System's Core Responsibility

The tool system is a **bridge** with exactly one job:

```
LLM's intent → [validate] → [execute] → [format] → LLM's context
```

It must:
1. **Accept** the LLM's tool call request (name + arguments)
2. **Validate** that the tool exists and arguments are well-formed
3. **Execute** the handler function with validated arguments
4. **Format** the result as a message the LLM can understand
5. **Return** the formatted result to the agent loop for context injection

That's it. Five steps. Everything else — streaming, async, permissions, sandboxing — is elaboration on these five.

---

## 4. First-Principles Constraints

What constraints does the environment impose on the tool system?

### 4.1 The LLM makes mistakes

The LLM will sometimes call tools that don't exist, provide wrong argument types, or supply semantically invalid values. The tool system must handle all of these gracefully — never crash, always return a structured result.

### 4.2 The LLM self-corrects through feedback

When the tool system returns an error, the LLM reads it and adjusts. This means: **error messages are prompts to the LLM**. Write them accordingly. "Tool 'read_fil' not found. Did you mean 'read_file'?" is vastly better than "Unknown tool."

### 4.3 Tools are the agent's only way to act

If a tool is slow, the agent is slow. If a tool is unreliable, the agent is unreliable. If a tool has side effects, the agent has side effects. Tool quality ≈ agent quality.

### 4.4 The LLM has finite context

Every tool result consumes context tokens. Large results crowd out conversation history. The tool system must balance informativeness with conciseness. 500KB of raw JSON as a tool result is a context bomb.

### 4.5 The LLM is stateless between calls

The LLM doesn't "remember" tool results natively — they must be in the messages array. If you cache results locally but don't feed them to the LLM, the LLM doesn't know about them. The messages array IS the agent's memory.

---

## 5. The Tool System's API Surface

From these principles, we can derive the minimum API:

```typescript
interface ToolSystem {
  // Registration: define what tools exist
  register(tool: Tool): void

  // Execution: the LLM says "run X with args Y", we do it
  execute(name: string, args: Record<string, unknown>): Promise<ToolResult>

  // Query: what tools are available? (for LLM to decide)
  getDefinitions(): ToolDefinition[]
}

interface Tool {
  definition: ToolDefinition
  handler: (args: Record<string, unknown>) => Promise<unknown>
}

interface ToolDefinition {
  name: string           // unique identifier, LLM uses this to invoke
  description: string    // tells LLM when and how to use this tool
  parameters: JSONSchema // contract for arguments
}

interface ToolResult {
  success: boolean
  content: string        // the message that goes back to the LLM
  error?: ToolError      // structured error if failed
}
```

This is the **entire interface**. Everything else — streaming, async dispatch, approval gates, progress reporting — is built on top of this foundation.

---

## 6. The Misunderstood Parts

These are things that seem important but aren't (for an MVP), or things that seem trivial but are critical:

### 6.1 Tool descriptions ARE the UI

The LLM has no mouse, no dropdown, no autocomplete. The tool description is the ONLY thing telling the LLM: "use this tool when..." A bad description means the LLM simply won't use the tool, or will use it wrong. Write descriptions for an LLM reader, not a human reader.

Good: `"Read the contents of a file from the local filesystem. Returns the file contents as a string."`
Bad: `"Reads a file"`

### 6.2 Tool names are permanent API

Once the LLM learns to call `read_file`, renaming it to `fs_read` breaks everything. Tool names are baked into the LLM's behavior through training and system prompt. Treat them as permanent. Name carefully from day one.

Convention: `snake_case` verbs: `read_file`, `write_file`, `search_code`, `run_command`. Consistent naming makes the LLM's life easier.

### 6.3 Schema validation is NOT just type checking

JSON Schema validates structure (is `path` a string?). But semantic validation (does the file exist? is the URL reachable?) happens at execution time. Both are important, but they happen at different stages. Don't conflate them.

### 6.4 Error messages ARE prompts

This is worth repeating. When a tool fails, the error message goes directly into the LLM's context. Write error messages that help the LLM fix the problem. Include: what went wrong, why, and what to try instead.

```
Bad:  "Error: ENOENT"
Good: "File '/tmp/missing.json' not found. Check the file path and try again.
       The file must exist and be readable by the current process."
```

---

## 7. Summary

| Principle | Implication |
|---|---|
| Tools are the LLM's limbs | Tool quality = agent quality |
| Definition ≠ Implementation | Swap implementations freely; the LLM only sees definition + result |
| Five-step bridge | validate → execute → format → return → inject |
| Errors are prompts | Write error messages the LLM can learn from |
| Names are permanent | `snake_case` verbs; never rename after deployment |
| Context is finite | Large tool results kill context; be concise |
| LLM makes mistakes | Never crash; always return structured feedback |
