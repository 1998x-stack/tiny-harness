# Human-in-the-Loop (HITL)

## 1. Overview

HITL inserts human judgment at critical decision points in the agent's execution loop. When the agent wants to call a tool that could have side effects — write files, delete data, run shell commands — it pauses and asks the human for approval.

```
Agent → AgentLoop → ToolExecutor.execute()
                        ↓
                  ApprovalGate.check()  ← HITL interception
                        ↓
                  ApprovalHandler (user callback)
                        ↓
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
    APPROVED          DENIED         MODIFIED
   (proceed)     (return error)   (execute with
                                   edited args)
```

The gate sits inside `ToolExecutor.execute()`, between the filesystem guard check and the handler call — it catches every tool execution regardless of how the loop calls it.

---

## 2. Architecture

### 2.1 Module Layout

```
tiny_harness/
├── _hitl.py          ← HITL core (ApprovalGate, SessionApprovals, types)
├── _tools.py         ← ToolExecutor accepts approval_gate parameter
├── _loop.py          ← skips denied results in error budget
├── _core.py          ← Agent wires ApprovalGate into ToolExecutor
├── cli.py            ← default y/n/s/m approval handler
└── tui.py            ← Rich-styled approval dialog
```

### 2.2 Data Types

```python
@dataclass
class ApprovalDecision:
    approved: bool
    reason: str = ""
    session_approved: bool = False
    modified_args: dict | None = None

@dataclass
class ToolApprovalRequest:
    tool_name: str
    args: dict
    risk_level: str
    reason: str = ""

ApprovalHandler = Callable[[ToolApprovalRequest], Awaitable[ApprovalDecision]]
```

### 2.3 ApprovalGate

```python
class ApprovalGate:
    def __init__(
        self,
        handler: ApprovalHandler | None = None,
        session: SessionApprovals | None = None,
        timeout_ms: int = 120_000,
        require_approval_for: set[str] | None = None,
    ) -> None: ...

    def needs_approval(self, tool_name: str, risk_level: str) -> bool: ...
    async def check(self, tool_name: str, args: dict, risk_level: str) -> ApprovalDecision: ...
```

`check()` follows this decision tree:

```
needs_approval(tool, risk)?
  ├─ No  → auto-approved (low risk)
  └─ Yes → session.is_approved(risk)?
              ├─ Yes → session-approved
              └─ No  → handler exists?
                         ├─ No  → rejected (no handler)
                         └─ Yes → await handler(request)
                                    ├─ Timeout → rejected
                                    ├─ Returned None → rejected
                                    └─ Decision returned
                                       ├─ approved + session_approved → cache level
                                       └─ return decision
```

---

## 3. Risk-Level → HITL Mapping

Every tool has a `risk_level` on its `ToolDef`. The gate uses this to decide whether approval is needed:

| risk_level | HITL required? | Session bypass? | Example tools |
|---|---|---|---|
| `"safe"` | No | — | `calculate`, `format_date` |
| `"read_only"` | No | — | `read_file`, `list_directory`, `search_content` |
| `"mutation"` | Yes | Yes | `write_file`, `create_directory`, `move_file` |
| `"destructive"` | Yes | No | `delete_file` |
| `"dangerous"` | Yes | No | `run_command` |

### 3.1 Explicit Override

The `require_approval_for` set forces approval for specific tool names regardless of their risk level:

```python
config = Config(
    require_approval_for=["read_file"],  # even reads need approval
)
```

Tools in this set always route to the approval handler, even if their risk level would normally auto-pass.

---

## 4. Session Approvals

`SessionApprovals` caches user decisions to reduce repeated prompts. When the user picks "yes for session" (`s`), the approved risk level and ALL lower levels are cached.

```python
session = SessionApprovals()
session.approve_for_session("mutation")

session.is_approved("read_only")    # True  (lower level)
session.is_approved("mutation")     # True  (the approved level)
session.is_approved("destructive")  # False (higher level, no bypass)
session.is_approved("dangerous")    # False
```

Risk level ordering: `safe < read_only < mutation < destructive < dangerous`

The session cache lives on the `ApprovalGate` and is accessible at `agent.approval_gate.session`. Use `clear()` to reset it mid-session.

---

## 5. Error Budget Integration

HITL denials do NOT count against the agent's error budget. The loop distinguishes via `ToolResult.denied`:

```python
# _loop.py
if result.success:
    error_budget.record_success()
elif result.denied:
    pass  # denial — don't count as error
else:
    if not error_budget.record_error():
        return await self._degraded_finish(collected_text)
```

This means the user can say "no" repeatedly without triggering `_degraded_finish()`. The LLM still sees the denial message and can try a different approach.

---

## 6. Events & Observability

When a tool is denied, the executor emits a `"tool_denied"` event through the `EventBus`:

```python
StreamEvent(
    type="tool_denied",
    tool_name="delete_file",
    message="User denied"
)
```

Streaming consumers can handle this:

```python
async for event in agent.run_stream(prompt):
    if event.type == "tool_denied":
        print(f"User blocked: {event.tool_name} — {event.message}")
    elif event.type == "tool_start":
        print(f"Calling: {event.tool_name}")
```

---

## 7. Modify & Approve

The user can edit tool arguments before approving. The handler returns `modified_args` in the decision:

```python
# Handler
return ApprovalDecision(
    approved=True,
    modified_args={"path": "/safe/path.txt"}  # override original args
)
```

The executor applies modified args and re-runs the filesystem guard check on the new path before executing. Schema is NOT re-validated (trust the user's edit).

CLI flow:
```
  🔐 Approve 'write_file'? (risk: mutation)
     path: /etc/hostname
  [y=yes / n=no / s=yes for session / m=modify]: m
  Modify key=value (or empty to finish): path=/safe/path.txt
     Updated path = /safe/path.txt
  Modify key=value (or empty to finish):
  → Executes with modified path
```

---

## 8. Configuration

```python
config = Config(
    require_approval_for=["delete_file"],  # specific tools always need approval
    approval_timeout_ms=60_000,            # how long to wait for user response
    no_hitl=False,                         # True = disable HITL entirely
)
```

### 8.1 Disabling HITL

```bash
# CLI: bypass all approval prompts
tiny-harness --no-hitl "delete all temp files"

# Python API: don't create ApprovalGate
agent = Agent(prompt=prompt, config=Config(..., no_hitl=True))
```

When `no_hitl=True`, the `ApprovalGate` is `None`, and `ToolExecutor` executes all tools without checks. Same behavior as pre-HITL.

---

## 9. Custom Approval Handlers

### 9.1 Python API

```python
from tiny_harness import Agent, Prompt, Config, ApprovalDecision

agent = Agent(prompt=Prompt("..."), config=Config(...))

async def my_handler(request) -> ApprovalDecision:
    print(f"Agent wants to use: {request.tool_name}")
    # Custom logic: check against allowlist, call external service, etc.
    if request.tool_name in ALLOWED_TOOLS:
        return ApprovalDecision(approved=True)
    return ApprovalDecision(approved=False, reason="not in allowlist")

agent.set_approval_handler(my_handler)
```

### 9.2 Handler Contract

The handler receives a `ToolApprovalRequest` and must return an `ApprovalDecision`:

```python
@dataclass
class ToolApprovalRequest:
    tool_name: str      # e.g., "write_file"
    args: dict          # e.g., {"path": "/tmp/x.txt", "content": "hello"}
    risk_level: str     # e.g., "mutation"
    reason: str         # human-readable reason for the approval prompt

@dataclass  
class ApprovalDecision:
    approved: bool                    # allow execution?
    reason: str = ""                  # why denied (shown to LLM)
    session_approved: bool = False    # cache this decision for the session?
    modified_args: dict | None = None # override arguments
```

The handler has `approval_timeout_ms` to respond. If it takes longer, the gate auto-rejects with a timeout error.

---

## 10. CLI/TUI Default Handlers

Both CLI and TUI ship with built-in approval handlers:

```
  🔐 Approve 'write_file'? (risk: mutation)
     path: /tmp/hello.py
     content: print("hello")
  [y=yes / n=no / s=yes for session / m=modify]:
```

| Key | Action |
|---|---|
| `y` | Approve this call |
| `n` or Enter | Deny this call |
| `s` | Approve this call AND all future calls at this risk level or lower |
| `m` | Enter modify mode — edit args with `key=value` pairs, empty to finish |

The CLI handler uses `asyncio.to_thread(input, ...)` for non-blocking I/O. The TUI handler uses `console.input()` for Rich-styled prompts.

---

## 11. Testing

```bash
# 36 tests covering all HITL components
pytest tests/test_hitl.py -v
```

Test coverage includes:
- `SessionApprovals`: cascading, clear, edge cases
- `ApprovalGate.needs_approval`: all risk levels, explicit override
- `ApprovalGate.check`: auto-approve, session cache, handler denial, timeout, None handler
- `ToolExecutor` integration: backward compat (no gate), denial, approval, read_only bypass
- Event emission: `tool_denied` fires on denial, not on read_only
- `modified_args`: applied correctly, re-guarded for safety
- `ToolResult.denial()`: factory correctness, denied flag

---

## 12. Design Decisions

| Decision | Rationale |
|---|---|
| Gate in `ToolExecutor`, not `AgentLoop` | Single choke point — catches all tool calls regardless of caller |
| Denials don't count as errors | User should be able to say "no" repeatedly without killing the agent |
| Re-guard on modified args | Modified paths must still pass workspace boundary check |
| Session cache at risk level, not per-tool | Coarse-grained is simpler; specific tools use `require_approval_for` |
| `120s` default timeout | Long enough for human to read and decide; prevents infinite hang |
| `EventBus` optional on `ToolExecutor` | Backward compatible; only needed if consumer wants `tool_denied` events |
| Schema NOT re-validated on modified args | Trust the human's edit; guard is sufficient for path safety |

---

## 13. Future: From Spec (Not Yet Implemented)

The original HITL spec (Chinese: "PHuman-in-the-Loop") describes additional modes not yet in this implementation:

| Feature | Status | Notes |
|---|---|---|
| Sync approval (pause-and-wait) | ✅ Implemented | Via approval handler callback |
| Session approvals | ✅ Implemented | `SessionApprovals` with risk-level cache |
| Modify & Approve | ✅ Implemented | `m` option in CLI/TUI handlers |
| Async approval (ticket-based) | ❌ Not yet | For long-running tasks; needs persistence |
| Notification mode (countdown) | ❌ Not yet | "Doing X in 5s, cancel if not OK" |
| Context-based dynamic triggering | ❌ Not yet | Approval based on context, not just risk level |
| Confidence-based triggering | ❌ Not yet | Model confidence < threshold → ask human |
| HITL audit trail | ❌ Not yet | Logging all approval decisions for review |
