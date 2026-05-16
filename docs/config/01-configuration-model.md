# Configuration Model

## 1. First Principles: What Is Configuration?

Agent configuration answers one question: **"What does this agent instance know before it starts?"**

From first principles, configuration is everything that:
1. **Identifies** the agent (which model, which system prompt)
2. **Constrains** the agent (max iterations, tool limits, safety rules)
3. **Equips** the agent (which tools are available, API credentials)

Everything else is runtime state (discovered during execution) or external context (provided by the user in the task prompt).

---

## 2. The Configuration Object

### 2.1 Complete Config Schema

```python
@dataclass
class AgentConfig:
    # ── Identity ─────────────────────
    model: str                          # "claude-sonnet-4-20250514"
    system_prompt: str                  # The agent's personality and rules

    # ── Constraints ──────────────────
    max_iterations: int = 25            # Safety cap on loop iterations
    max_tool_errors: int = 10           # Total tool error budget
    max_consecutive_errors: int = 3     # Consecutive error budget
    context_limit: int = 200_000        # Model's max context window (tokens)
    context_warn_threshold: float = 0.8 # Warn when context is 80% full
    max_tool_result_chars: int = 50_000 # Truncate tool results

    # ── Tools ────────────────────────
    tools: ToolRegistry                 # Available tools

    # ── LLM Provider ─────────────────
    provider: str = "anthropic"         # "anthropic" | "openai" | "openrouter"
    api_key: str | None = None          # From env var, not hardcoded
    api_base_url: str | None = None     # For proxies / alternative endpoints
    temperature: float = 0.0            # 0 = deterministic, 1 = creative
    max_output_tokens: int = 16_384     # Max tokens per LLM response

    # ── Streaming ────────────────────
    stream: bool = True                 # Stream LLM output in real time
    stream_tool_events: bool = True     # Stream tool call announcements

    # ── Safety ───────────────────────
    allowed_paths: list[str] | None = None  # Filesystem access boundaries
    require_approval_for: list[str] | None = None  # Tools needing user confirmation
```

### 2.2 What Configuration Is NOT

| Not Config | Why |
|---|---|
| Task description | Provided at runtime by the user |
| Conversation state | Built during execution (messages array) |
| Tool results | Generated at runtime |
| LLM responses | Generated at runtime |
| Performance metrics | Tracked at runtime, not configured |

---

## 3. The System Prompt

### 3.1 Why the System Prompt Is Special

The system prompt is the most impactful piece of configuration. It defines:
- **Who the agent is** (role, personality, tone)
- **How to use tools** (when to call which tool, how to interpret results)
- **What the rules are** (constraints, output format, safety rules)
- **How to handle errors** (retry, escalate, give up)

A harness with the same code but different system prompts produces completely different agent behavior. The prompt is as important as the code.

### 3.2 System Prompt Structure

A well-designed system prompt has clear sections:

```markdown
## Identity
You are a coding assistant. You help users write, debug, and understand code.
Be concise. Provide code first, explanations when asked.

## Tools
You have access to these tools:
- read_file: Read file contents
- write_file: Create or overwrite a file
- search_code: Search codebase with regex
- run_command: Execute shell commands

Use tools when you need to interact with the filesystem or discover information.
Prefer tools over guessing. If you're unsure, check.

## Rules
1. Be minimal — answer only what was asked
2. Verify your work — after writing a file, read it back to confirm
3. If a tool fails, read the error and try a different approach
4. Never run destructive commands without confirmation
5. Use search_code for finding patterns, not grep/awk in run_command

## Output Format
- Code in ```language blocks
- Explanations after code, not before
- One action per response when possible

## Error Handling
If a tool fails:
1. Read the error message carefully
2. Determine if it's fixable (typo, wrong path) or systemic (permission, missing file)
3. Try once more with correction, or try a different approach
4. If stuck, explain the situation to the user
```

### 3.3 Prompt Design Principles

1. **Be specific, not vague**: "Use read_file for reading files, search_code for patterns" > "Use appropriate tools"
2. **Guide tool selection**: Tell the LLM which tool to use for what purpose
3. **Set error expectations**: The LLM should know what to do when things go wrong
4. **Establish tone**: "Be concise" vs "Be thorough and detailed"
5. **Define boundaries**: What the agent should NOT do

### 3.4 Prompt as Code

Treat the system prompt like code:
- Version control it
- Test it (does the LLM follow the rules?)
- Iterate on it (observe behavior, adjust)
- Keep it focused (remove rules that aren't needed)

---

## 4. Configuration Sources

### 4.1 Priority Order

```
1. Environment variables    (highest priority — secrets, deployment-specific)
2. Code defaults            (built-in defaults in the AgentConfig dataclass)
3. Config file              (lowest priority — shared, version-controlled settings)
```

### 4.2 Environment Variables

```
AGENT_MODEL=claude-sonnet-4-20250514
AGENT_MAX_ITERATIONS=50
AGENT_API_KEY=sk-ant-...
AGENT_ALLOWED_PATHS=/home/user/project,/tmp/agent
```

Environment variables are for:
- Secrets (API keys) — never in config files
- Deployment-specific overrides (staging uses different model than production)
- Dynamic settings (feature flags)

### 4.3 Config File (TOML)

```toml
# agent.toml
[model]
name = "claude-sonnet-4-20250514"
provider = "anthropic"
temperature = 0.0
max_output_tokens = 16384

[loop]
max_iterations = 25
max_total_errors = 10
max_consecutive_errors = 3

[context]
limit = 200000
warn_threshold = 0.8
max_tool_result_chars = 50000

[safety]
allowed_paths = ["."]
require_approval_for = ["run_command", "delete_file"]

[streaming]
enabled = true
show_tool_events = true

[system_prompt]
file = "prompts/coding-assistant.md"
```

### 4.4 Loading Order

```python
def load_config(config_path: str | None = None,
                env_prefix: str = "AGENT_") -> AgentConfig:
    # 1. Start with defaults
    config = AgentConfig.defaults()

    # 2. Layer config file (if exists)
    if config_path and os.path.exists(config_path):
        file_config = parse_toml(config_path)
        config = merge_configs(config, file_config)

    # 3. Override with environment variables
    env_config = load_from_env(env_prefix)
    config = merge_configs(config, env_config)

    return config
```

---

## 5. Config Validation

```python
def validate_config(config: AgentConfig) -> list[str]:
    errors = []

    if not config.model:
        errors.append("model is required")
    if not config.system_prompt:
        errors.append("system_prompt is required")
    if config.max_iterations < 1:
        errors.append("max_iterations must be >= 1")
    if config.max_iterations > 1000:
        errors.append("max_iterations too high (>1000)")
    if config.context_limit < 1000:
        errors.append("context_limit too small (<1000)")
    if config.temperature < 0 or config.temperature > 2:
        errors.append("temperature must be 0-2")

    # API key validation
    if not config.api_key:
        key = os.environ.get(f"{config.provider.upper()}_API_KEY")
        if not key:
            errors.append(f"API key not found for provider '{config.provider}'")

    return errors
```

---

## 6. MVP Decisions

| Decision | Rationale |
|---|---|
| **Hardcoded defaults + env vars only** | No config file parsing needed; env vars suffice for MVP |
| **System prompt as a string** | No file loading; paste the prompt directly |
| **No config hot-reload** | Restart the agent to change config |
| **Single model** | No multi-model routing; one model per agent instance |
| **No prompt templates** | The system prompt is the template; no need for Jinja/Mustache |
| **Validation on init** | Crash early on bad config; don't discover at runtime |

### MVP Config Initialization

```python
@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-20250514"
    system_prompt: str = "You are a helpful AI assistant. Use tools when needed."
    max_iterations: int = 25
    max_errors: int = 10
    max_consecutive_errors: int = 3
    timeout_ms: int = 30_000
    stream: bool = True
    api_key: str | None = None

    @classmethod
    def from_env(cls, api_key_env: str = "ANTHROPIC_API_KEY") -> "AgentConfig":
        return cls(
            api_key=os.environ.get(api_key_env),
            model=os.environ.get("AGENT_MODEL", cls.model),
            max_iterations=int(os.environ.get("AGENT_MAX_ITERATIONS", cls.max_iterations)),
        )

# Usage
config = AgentConfig.from_env()
config.system_prompt = "You are a coding assistant..."  # User sets this
config.tools = my_tools  # User registers tools
```
