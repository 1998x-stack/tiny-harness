# Safety and Sandboxing

## 1. The Fundamental Tension

Every tool gives the agent power to act. The more powerful the tools, the more the agent can accomplish. But every tool is also a potential attack surface — either from the LLM making mistakes, or from malicious inputs the LLM processes.

The safety design problem:

```
Agent capability  ∝  Number & power of tools
Agent risk        ∝  Number & power of tools

Safety = maximizing capability while minimizing risk
```

There is no perfectly safe agent with useful tools. There are only tradeoffs.

---

## 2. First Principles: What Makes a Tool Dangerous?

### 2.1 Destructive Side Effects

Operations that irreversibly change state:
- Deleting files, dropping database tables
- Overwriting production data
- Sending money, making purchases
- Modifying system configuration

**Risk**: The LLM misunderstands intent and deletes/destroys the wrong thing.

### 2.2 Information Exposure

Operations that read and potentially leak sensitive data:
- Reading secret files (.env, private keys, credentials)
- Sending data to external URLs
- Logging sensitive information in tool results

**Risk**: The LLM reads secrets and accidentally includes them in responses or tool calls.

### 2.3 Resource Exhaustion

Operations that consume unbounded resources:
- Infinite loops (while true; do ...)
- Fork bombs, recursive directory creation
- Allocating all available memory
- Filling the disk with writes

**Risk**: A single bad tool call takes down the entire system.

### 2.4 Privilege Escalation

The agent can access things the user didn't intend:
- `sudo` in shell commands
- Accessing other users' files
- Modifying system services

**Risk**: The LLM discovers and exploits its own permissions.

---

## 3. Tool Risk Classification

Every tool belongs to one of five risk levels. The harness uses this classification to decide: auto-approve, ask user, or deny.

### Level 0: Safe (No Risk)

Tools with no side effects and no access to sensitive data.

| Characteristics | Examples | Policy |
|---|---|---|
| Pure computation | `calculate`, `format_date` | Always auto-approve |
| No I/O | `string_length`, `json_parse` | |
| No external state | `generate_uuid` | |

### Level 1: Read-Only (Low Risk)

Tools that read data but don't modify anything.

| Characteristics | Examples | Policy |
|---|---|---|
| Read filesystem | `read_file`, `list_directory` | Auto-approve in trusted workspace |
| Query APIs | `search_code`, `git_log` | |
| No side effects | `get_current_time`, `check_file_exists` | |

### Level 2: Write / Mutation (Medium Risk)

Tools that create or modify state, with reversible or contained effects.

| Characteristics | Examples | Policy |
|---|---|---|
| Create/modify files | `write_file`, `create_directory` | Confirm on first use per session |
| Git operations | `git_commit`, `git_branch` | |
| Limited scope | `append_file`, `rename_file` | |

### Level 3: Destructive (High Risk)

Tools that irreversibly destroy data or state.

| Characteristics | Examples | Policy |
|---|---|---|
| Delete data | `delete_file`, `drop_table` | Always confirm |
| Overwrite | `force_write` (no backup) | |
| Irreversible | `rm -rf`, `git push --force` | |

### Level 4: Dangerous (Critical Risk)

Tools that can compromise the system or have unbounded effects.

| Characteristics | Examples | Policy |
|---|---|---|
| Arbitrary execution | `shell_command`, `eval_code` | Confirm every call |
| Network outbound | `http_request`, `send_email` | May require allowlist |
| System modification | `install_package`, `sudo` | May be disabled entirely |
| Financial | `make_payment`, `place_order` | Require explicit user action |

---

## 4. Permission Models

### 4.1 MVP: No Permissions (Trusted Environment)

For the first iteration, assume the agent runs in a trusted environment:

```
All tools auto-approved. User fully trusts the agent's judgment.
```

This is appropriate when:
- The user is the developer, running the agent locally
- The workspace is isolated (not production)
- Destructive tools simply don't exist (MVP just has read + write tools)
- The user can see what the agent is doing in real time (streaming)

### 4.2 User Confirmation (Production Minimum)

Add a confirmation gate for Level 2+ tools:

```python
async def execute_with_approval(tool_call: ToolCall, tool: Tool) -> ToolResult:
    if tool.risk_level >= Level.MUTATION:
        approved = await ask_user(
            f"Agent wants to use '{tool.name}' with args: {tool_call.arguments}\n"
            f"Approve? [y/N] "
        )
        if not approved:
            return ToolResult.error(
                tool_call.id,
                f"User denied '{tool.name}'. Try a different approach that doesn't require this tool."
            )
    return await execute_tool(tool_call)
```

### 4.3 Allowlist / Denylist

For more control, maintain lists:

```python
class ToolPolicy:
    allowlist: set[str]   # Only these tools (+ safe ones) are allowed
    denylist: set[str]    # These tools are never allowed
    path_allowlist: list[str]  # Only these paths can be read/written
    domain_allowlist: list[str]  # Only these domains for network tools

    def is_allowed(self, tool: Tool, args: dict) -> bool:
        if tool.name in self.denylist:
            return False
        if tool.name in self.allowlist:
            return self._check_arg_constraints(args)
        return tool.risk_level <= Level.READ_ONLY
```

### 4.4 Capability-Based (Future)

Each tool declares required capabilities. User grants capabilities to the agent:

```python
CAP_READ_FILES = "read_files"
CAP_WRITE_FILES = "write_files"
CAP_NETWORK = "network"
CAP_SHELL = "shell"

tool = Tool(
    name="write_file",
    required_capabilities=[CAP_WRITE_FILES]
)

agent = Agent(granted_capabilities=[CAP_READ_FILES, CAP_WRITE_FILES])
```

---

## 5. Sandboxing Strategies

### 5.1 Filesystem Sandbox

Restrict which directories the agent can touch:

```python
class FilesystemGuard:
    def __init__(self, allowed_paths: list[str]):
        self.allowed_paths = [Path(p).resolve() for p in allowed_paths]

    def check(self, path: str) -> bool:
        resolved = Path(path).resolve()
        return any(
            resolved == allowed or allowed in resolved.parents
            for allowed in self.allowed_paths
        )

# Usage: wrap file tools
guard = FilesystemGuard(allowed_paths=["/home/user/project", "/tmp/agent"])

def safe_read_file(path: str) -> str:
    if not guard.check(path):
        raise PermissionError(f"Access denied: '{path}' is outside allowed paths")
    return open(path).read()
```

### 5.2 Resource Limits

Prevent resource exhaustion:

```python
RESOURCE_LIMITS = {
    "max_file_size_read": 10 * 1024 * 1024,   # 10 MB
    "max_file_size_write": 10 * 1024 * 1024,  # 10 MB
    "max_command_runtime": 30,                 # 30 seconds
    "max_command_output": 1 * 1024 * 1024,     # 1 MB
    "max_memory_per_tool": 256 * 1024 * 1024,  # 256 MB
}
```

### 5.3 Container Isolation (Beyond MVP)

Run the entire agent in a Docker container:

```
docker run --rm \
  --memory=2g \
  --cpus=2 \
  --network=none \
  -v /safe/workspace:/workspace:rw \
  tiny-harness run "Do X"
```

This provides OS-level isolation: no access to host filesystem, network, or other processes.

### 5.4 Subprocess Sandbox (Per-Tool)

Run high-risk tools in limited subprocesses:

```python
async def sandboxed_execute(tool_call: ToolCall) -> str:
    proc = await asyncio.create_subprocess_exec(
        "sandbox-runner",
        "--tool", tool_call.name,
        "--timeout", "30",
        "--max-memory", "256m",
        "--input", json.dumps(tool_call.arguments),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=35  # slightly more than tool timeout
    )
    if proc.returncode != 0:
        return f"Error: {stderr.decode()}"
    return stdout.decode()
```

---

## 6. Safety in the Tool Definition

Safety metadata should be part of the tool definition:

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict

    # Safety metadata
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    requires_approval: bool = False
    is_reversible: bool = True       # Can effects be undone?
    max_expected_runtime_ms: int = 5000
    may_access_network: bool = False
    may_modify_filesystem: bool = False
    requires_capabilities: list[str] = field(default_factory=list)
```

The harness uses this metadata to decide:
- Whether to auto-approve or ask user
- What timeout to apply
- Whether to sandbox the execution
- Whether to log/audit the call

---

## 7. Audit Trail

Every tool call should be logged for post-hoc review:

```python
@dataclass
class ToolCallRecord:
    timestamp: datetime
    tool_name: str
    arguments: dict
    result_summary: str       # first 200 chars of result
    success: bool
    risk_level: RiskLevel
    duration_ms: int
    was_approved: bool | None  # None if auto-approved
```

This enables:
- Debugging: "What did the agent actually do?"
- Security review: "Did it access anything suspicious?"
- Cost analysis: "Which tools are most expensive?"
- Improvement: "Which tools fail most often?"

---

## 8. MVP Decisions

For `tiny-harness` MVP:

| Decision | Rationale |
|---|---|
| No permission system initially | MVP runs in trusted local environment; the user IS the safety layer |
| Risk level metadata on every tool | Cheap to add, enables safety features later without refactoring |
| Resource limits from day one | Timeouts + output size limits prevent common failure modes |
| Filesystem guard (configurable, disabled by default) | Simple to implement, high value when enabled |
| Audit log (file-based) | Enables debugging and post-hoc review |
| Tool description includes safety warnings | LLM reads warnings and adjusts behavior (e.g., "WARNING: destructive") |
| No sudo, no eval, no network by default | Dangerous capabilities opt-in only |
| User sees tool calls in streaming output | Transparency is the first line of defense |

### MVP Safety Implementation

```python
class SafeToolExecutor:
    def __init__(self, registry, config):
        self.registry = registry
        self.timeout_ms = config.get("default_timeout_ms", 30000)
        self.max_output_chars = config.get("max_output_chars", 50000)
        self.fs_guard = FilesystemGuard(config.get("allowed_paths", []))
        self.audit_log = []

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        tool = self.registry.get(tool_call.name)
        start = time.time()

        try:
            # Filesystem check for file tools
            if tool.definition.may_modify_filesystem:
                path = tool_call.arguments.get("path") or tool_call.arguments.get("file_path")
                if path and not self.fs_guard.check(path):
                    return ToolResult.error(tool_call.id, f"Access denied: '{path}'")

            # Execute with timeout
            raw = await asyncio.wait_for(
                tool.handler(**tool_call.arguments),
                timeout=self.timeout_ms / 1000
            )

            # Format with truncation
            formatted = truncate(format_output(raw), self.max_output_chars)
            result = ToolResult.success(tool_call.id, formatted)

        except asyncio.TimeoutError:
            result = ToolResult.error(tool_call.id, f"Timeout after {self.timeout_ms}ms")
        except Exception as e:
            result = ToolResult.error(tool_call.id, f"Error: {e}")

        # Audit
        self.audit_log.append(ToolCallRecord(
            timestamp=datetime.now(),
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            result_summary=result.content[:200],
            success=result.success,
            risk_level=tool.definition.risk_level,
            duration_ms=int((time.time() - start) * 1000),
        ))

        return result
```
