# AI Agent Harness: First Principles Design

## 1. What Is an AI Agent? (First Principles)

Start from the fundamentals:

- **An LLM is a pure function**: `messages[] → response`. You send text in, you get text out. That's it.
- **Tool calling is the LLM saying "I need to do X"** instead of just answering. The LLM outputs structured instructions (function name + arguments) alongside or instead of text.
- **An agent is a feedback loop**: LLM decides → system executes → result feeds back → LLM decides again → ... → terminal answer.

This means the "intelligence" lives entirely in the LLM. The harness is mechanical infrastructure — it does no reasoning, only bookkeeping. The harness's job is to faithfully execute the LLM's decisions and feed results back into context, allowing the LLM to course-correct.

**The agent harness is a while-loop with good bookkeeping.**

---

## 2. The Core Loop

Every agent harness reduces to this:

```
while not done:
    response = llm.generate(messages, tools)

    if response.is_final():
        return response.content          # terminal answer — exit loop

    for tool_call in response.tool_calls:
        result = execute(tool_call)
        messages.append(tool_result(tool_call.id, result))
        # loop continues — LLM sees results and decides next action
```

That's it. ~10 lines of pseudocode. Everything else is elaboration.

The loop has exactly two exit conditions:
1. **LLM returns text without tool calls** → final answer delivered
2. **Max iterations reached** → safety valve (safety cutoff)

---

## 3. Minimum Viable Components

From the core loop, we can derive the minimum components by asking: "what does this line need to work?"

### 3.1 LLM Provider (`llm.generate()`)

**What it needs**: A way to call an LLM with messages and tool definitions, returning text and/or tool calls.

**MVP:**
- Single model support (e.g., Anthropic Claude, or OpenAI-compatible API)
- Handle API key, base URL, model name
- Parse response into: text chunks (for streaming) + tool call blocks
- Basic retry on transient errors (rate limits, 5xx)

**NOT needed for MVP**: multi-model routing, fallback providers, model comparison.

```
Interface:
  generate(messages: Message[], tools: ToolDef[]) → Response
    Response.text: string | null
    Response.tool_calls: ToolCall[]
    Response.usage: { input_tokens, output_tokens }
```

### 3.2 Tool System (`execute(tool_call)`)

**What it needs**: A way to define tools the LLM can call, validate arguments, execute them, and return results.

**MVP:**
- A registry: `{ name → { definition, handler } }`
- Definition includes: name, description, JSON schema for parameters
- Handler is a plain function: `(args: object) => string | object`
- Result formatting: turn execution output into a properly-typed tool result message

**NOT needed for MVP**: tool approval/confirmation UI, async execution, sandboxing, permission system, parallel tool execution.

```
Interface:
  ToolDef = {
    name: string
    description: string
    parameters: JSONSchema
  }
  ToolHandler = (args: Record<string, unknown>) => Promise<string>

  register(tool: ToolDef, handler: ToolHandler): void
  execute(name: string, args: Record<string, unknown>): Promise<string>
```

### 3.3 Message/Context Manager (`messages`)

**What it needs**: Maintain the ordered message array that serves as the LLM's working memory.

**MVP:**
- Append-only message array: system → user → [assistant → tool_results] × N
- Message types: system, user, assistant, tool_result
- Properly formatted tool result messages (matching the tool_call IDs)
- Token counting (approximate is fine — character count ÷ 4)

**Critical insight**: The message array IS the agent's memory. Every tool result enriches context. Every assistant message captures reasoning. Nothing is lost between iterations — the LLM sees the full history.

**NOT needed for MVP**: context compaction, summarization, sliding windows, conversation pruning.

```
Messages = [
  { role: "system", content: "You are a helpful assistant..." },
  { role: "user", content: "Do X" },
  { role: "assistant", content: null, tool_calls: [...] },
  { role: "tool", tool_call_id: "...", content: "result" },
  { role: "assistant", content: "I did X. Here's the result..." },
  ...
]
```

### 3.4 Agent Loop Controller

**What it needs**: The while-loop that orchestrates the flow, with safety limits.

**MVP:**
- Max iterations cap (safety cutoff — prevents infinite loops)
- Stop detection: LLM returns text without tool calls
- Basic error handling: tool execution errors become tool result messages (error messages feed back to LLM, which can self-correct)
- Iteration counter for logging

**NOT needed for MVP**: sub-agent spawning, parallel task dispatch, multi-turn planning.

```
loop(max_iterations=25):
  iteration++
  if iteration > max_iterations: return timeout_error

  response = llm.generate(messages, tools)

  if response.text and not response.tool_calls:
    return response.text  # done

  for tc in response.tool_calls:
    try:
      result = tools.execute(tc.name, tc.args)
    catch error:
      result = format_error(error)
    messages.append(tool_result(tc.id, result))
```

### 3.5 Configuration

**What it needs**: Everything the agent needs to know before starting.

**MVP (hardcoded is fine):**
- System prompt (agent identity, rules, behavior)
- Model identifier (`claude-sonnet-4-20250514`, `gpt-4o`, etc.)
- Available tools list
- Max iterations
- API credentials (from environment variables)

**NOT needed for MVP**: config files (YAML/TOML/JSON), dynamic config reloading, environment-specific configs.

---

## 4. Component Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                  Agent Harness                    │
│                                                   │
│  ┌─────────────┐          ┌──────────────────┐   │
│  │ Agent Loop  │◄─────────│   Config         │   │
│  │ Controller  │          │ (system prompt,  │   │
│  │             │          │  model, tools,   │   │
│  │ while(...)  │          │  max_iterations) │   │
│  └──┬──────┬───┘          └──────────────────┘   │
│     │      │                                      │
│     ▼      ▼                                      │
│  ┌──────┐ ┌──────────┐  ┌────────────────────┐  │
│  │ LLM  │ │  Tool    │  │ Message / Context  │  │
│  │ Prov.│ │  System  │  │ Manager            │  │
│  │      │ │          │  │                    │  │
│  │call()│ │register()│  │ messages[]         │  │
│  │stream│ │execute() │  │ countTokens()      │  │
│  └──────┘ └──────────┘  └────────────────────┘  │
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │         Observability (logging)            │  │
│  └────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

Each component is a distinct responsibility. The Agent Loop is the only "active" component — it orchestrates the others. LLM Provider, Tool System, and Message Manager are passive — they respond to requests.

---

## 5. What an MVP Looks Like (Pseudocode)

```python
# ~80 lines — a complete working agent harness

class Agent:
    def __init__(self, model: str, system_prompt: str, max_iterations: int = 25):
        self.model = model
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.tools: dict[str, tuple[ToolDef, callable]] = {}

    def register_tool(self, name: str, description: str,
                      parameters: dict, handler: callable):
        self.tools[name] = (
            ToolDef(name=name, description=description, parameters=parameters),
            handler
        )

    def run(self, user_message: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]

        for iteration in range(self.max_iterations):
            # 1. Call LLM
            response = self._call_llm(messages)

            # 2. No tool calls? Final answer
            if response.text and not response.tool_calls:
                return response.text

            # 3. Append assistant message (with tool calls)
            messages.append(response.as_message())

            # 4. Execute tools, append results
            for tc in response.tool_calls:
                result = self._execute_tool(tc.name, tc.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })

        return "Error: max iterations reached"

    def _call_llm(self, messages: list) -> LLMResponse:
        # Single-model, single-provider. Replace with your LLM API call.
        ...

    def _execute_tool(self, name: str, args: dict) -> str:
        _, handler = self.tools[name]
        try:
            return str(handler(**args))
        except Exception as e:
            return f"Error executing {name}: {e}"
```

That's the entire agent. Register tools, call `run()`, done.

---

## 6. Key Design Insights

### 6.1 The harness does NO reasoning

The LLM does all the thinking. The harness should never try to be "smart" about what the LLM meant. Parse faithfully, execute faithfully, report faithfully. Any "intelligence" in the harness is a bug.

Corollary: the harness's error messages are prompts to the LLM. If a tool fails, the error message IS the tool result — the LLM reads it and self-corrects. The harness doesn't need retry logic; the LLM can decide to retry.

### 6.2 Tool results ARE memory

Every tool result appended to messages becomes part of the LLM's working context. The LLM can refer back to earlier results, compare outputs, notice contradictions. The message array is the agent's memory — treat it with care.

### 6.3 The system prompt IS the agent's personality

The system prompt defines everything about agent behavior: tool usage rules, output format, safety constraints, role identity. A harness with the same code but different system prompts produces completely different agent behavior. The prompt is as important as the code.

### 6.4 Streaming is essential even for MVP

Without streaming, the user stares at a blank screen for 30+ seconds with no feedback. Streaming transforms UX from "is it broken?" to "I can see it thinking." The simplest streaming: print text chunks as they arrive, and announce tool calls before executing.

### 6.5 Context grows monotonically — this is the fundamental scaling problem

Every iteration adds: assistant message + N tool result messages. A task requiring 10 tool calls produces ~20+ messages. Context windows are finite (200K tokens is common now, but complex tasks can still overflow). The MVP can ignore this, but it's the first thing you'll hit in production.

### 6.6 The only real failure mode is tool errors

If the LLM is good, the loop always converges. The harness's only real job in error handling is: tool execution fails → format error nicely → feed back as tool result → let LLM self-correct. Don't try to fix things in the harness.

---

## 7. Evolution Path: MVP → Production

| Concern | MVP | Production |
|---|---|---|
| **Streaming** | Print text as it arrives | Structured streaming with tool call state, JSON events |
| **Context mgmt** | Append-only, no limits | Token-aware truncation, summarization, compaction |
| **Tool execution** | Direct function calls | Subprocess sandboxing, timeouts, approval gates |
| **Error handling** | Try/catch, feed error to LLM | Categorized errors, retry policies, circuit breakers |
| **Observability** | Console logging | Structured logs, tracing, token usage dashboards |
| **Model support** | Single provider | Multi-provider with fallback chains |
| **Agent types** | Single loop | Sub-agent spawning, parallel dispatch |
| **Configuration** | Hardcoded | TOML/YAML config files, env-specific overrides |
| **Persistence** | None | Session storage, resume from checkpoint |

---

## 8. What NOT to Build (at MVP or ever)

Things that seem necessary but are premature complexity:

- **Task planning / decomposition in the harness**: The LLM can plan. Let it. The harness shouldn't try to break tasks down — that's the LLM's job.
- **Memory systems (vector DBs, RAG)**: These solve a specific problem (knowledge beyond context window). MVP should stay within a single context window. Add memory when you actually hit the limit.
- **Multi-agent orchestration**: One agent that can call tools is already powerful. Multi-agent adds complexity (coordination, message routing, shared state). Start with one.
- **Tool approval UI**: For MVP, either auto-approve everything (trusted environment) or auto-deny destructive operations. Approval flows are UX work, not harness work.
- **Config file format wars**: Hardcode until you need multiple configurations. Then pick one format (TOML is fine). Don't build an abstraction layer for "future format switching."
- **"Tool framework" abstractions**: Don't build base classes, decorators, or registries for tool definitions. A dictionary of `{name: (definition, handler)}` is sufficient and easier to debug.

---

## 9. Concrete MVP Specification

If building `tiny-harness` from scratch today:

### Must Have (Core Loop)
1. **LLM call**: Function that sends messages + tools to a single model, returns text + tool calls
2. **Tool registry**: Dict of `{name: (ToolDef, handler_fn)}`, with JSON schema parameters
3. **Agent loop**: While loop with max iterations, stop detection, tool execution, error feeding
4. **Message builder**: Append system, user, assistant, tool_result messages in correct order
5. **Streaming output**: Print text chunks as they arrive; log tool calls

### Should Have (Quick Wins)
6. **Token counter**: Approximate token count (char_count ÷ 4) with warnings near limit
7. **Tool timeout**: Each tool call has a timeout; exceeded → error result fed back
8. **Structured logging**: Each iteration logs: iteration #, tokens used, tool called, result snippet

### Won't Have (MVP)
9. Multi-model support
10. Context compaction
11. Sub-agent spawning
12. Persistent sessions
13. Config files
14. Tool approval UI
15. Parallel tool execution

### Target Scope
- **~200-300 lines** of Python or TypeScript
- **Single file** is fine
- **Hardcoded config** is fine
- **Single model** (Anthropic or OpenAI) is fine

---

## 10. The Test: "What's the Simplest Thing That Works?"

The simplest agent that does something useful:

```python
agent = Agent(model="claude-sonnet-4-20250514",
              system="You are a helpful assistant. Use tools when needed.")

agent.register_tool("read_file", "Read a file from disk",
    {"path": {"type": "string", "description": "File path"}},
    lambda path: open(path).read()
)

agent.register_tool("write_file", "Write content to a file",
    {"path": {"type": "string"}, "content": {"type": "string"}},
    lambda path, content: open(path, "w").write(content) or "done"
)

result = agent.run("Create a hello.py that prints 'Hello, world!'")
```

This agent can: read files, write files, iterate (read → decide → write → verify). That's already useful. Build from here.

---

## 11. Summary

| Question | Answer |
|---|---|
| What is an agent harness? | A while-loop that calls LLM, executes tools, feeds results back |
| How many core components? | 5: LLM provider, tool system, agent loop, message manager, config |
| How complex is an MVP? | ~200 lines, single file, no dependencies beyond an LLM SDK |
| What's the hardest part? | Not the code — it's the system prompt design and tool surface design |
| What breaks first in production? | Context overflow. Monotonically growing messages always eventually hit the limit |
| What should you NOT build? | Multi-agent, memory systems, planning frameworks, complex tool abstractions |
