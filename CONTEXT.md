# CONTEXT.md — tiny-harness

## Canonical Terms

### Agent
The complete runtime system that wraps an LLM, gives it tools, and executes the agent loop until a final answer is produced. The Agent owns: the Loop (while-loop orchestrator), the ToolRegistry (available tools), the LLMProvider (model interface), the MessageManager (context/memory), and the Config (identity + constraints).

Usage: `agent = Agent(config); result = await agent.run("Do X")`

The Agent is the only user-facing entry point. Internally, the Loop is the mechanical orchestrator; the Agent is the whole thing.

**Not to be confused with**: the LLM itself (which is the "model" or "provider"), or the Agent Loop (which is the internal while-loop component).

### Agent Core
The components that ship with the Agent and are essential for it to function: the Loop, MessageManager, Config, LLMProvider, and an empty ToolRegistry. The Agent Core has zero tools by default — even file access must be registered.

### Tool
A capability registered into the Agent's ToolRegistry. Tools are external plugins — they do not ship with the Agent Core. A convenience helper (`register_file_tools(agent)`) provides standard filesystem tools, but the user always controls which tools are available.

**Distinction**: The ToolRegistry is part of the Agent Core (it's the container). Individual Tools are not — they are registered into the registry by the user.

### Prompt
The agent's personality and operational rules — the system-level instructions that define how the Agent behaves, when to use tools, and what constraints to follow. The Prompt is a first-class design artifact, separate from Config (which is parameters like model, iterations) and from MessageManager (which manages runtime conversation state).

Usage: A Prompt may be a string, a file reference, or a template. It is version-controlled, tested, and swapped independently of the Agent's runtime parameters.

**Not to be confused with**: the User Prompt (the task given to the Agent at runtime) or Config (numeric/boolean parameters like `max_iterations`).

### Workspace
The root directory that bounds the Agent's filesystem authority. All relative paths resolve against the Workspace. The FilesystemGuard enforces that no file operation escapes the Workspace. The Workspace is the Agent's "home" — it can read, write, and organize within it, but cannot access anything outside.

Usage: Set once at Agent creation. The Agent treats the Workspace as `/` — it doesn't know (and shouldn't care) about the absolute path on the host filesystem.

**Not to be confused with**: the OS-level working directory (which the Agent ignores) or allowed_paths (which is a Config parameter — `["/workspace", "/tmp"]` — that may include directories beyond the primary Workspace).

### Conversation
The full ordered history of messages exchanged during an Agent run: the system-level Prompt, the user's task, the LLM's responses (text + tool call requests), and the tool results. The Conversation IS the Agent's memory — everything the LLM knows about the current interaction lives in this sequence. The MessageManager owns the Conversation; all other components read from it or append to it.

Usage: The Conversation starts with Prompt + user task and grows monotonically as the Loop executes. When the Agent completes, the Conversation is discarded (single-use Agent). Context management (truncation, compaction) operates on the Conversation.

### Session
A continuous interaction between the user and Agent that spans multiple user prompts. Within a Session, the Conversation persists — each new user prompt appends to the same Conversation, giving the Agent memory of what happened earlier in the Session. The Agent is Session-scoped: created when the Session starts, serves multiple user prompts, and discarded when the Session ends.

Usage: A Session starts with `agent.start_session()` or `tiny-harness` CLI. The user issues multiple prompts within the Session. The Agent maintains full conversation context (tool calls, results, reasoning) across prompts. The Session ends when the user exits or the Agent terminates.

**Not to be confused with**: cross-session persistence (the Agent remembering things between separate Sessions — out of scope for MVP).

### Skill
A packaged bundle of tools, Prompt augmentations, and usage conventions that can be loaded into the Agent as a unit. A Skill represents a domain capability — "git operations," "code review," "file management" — that the Agent can acquire by loading the Skill. Skills are the primary extensibility mechanism: users install skills, the Agent loads them.

Usage: `agent.load_skill("git")` registers the skill's tools and appends its prompt instructions. Skills may be local Python modules, installed packages, or (future) remote MCP servers.

**Not to be confused with**: individual Tools (a Skill contains multiple Tools), or MCP servers (which are a remote tool source — future scope, not MVP).
