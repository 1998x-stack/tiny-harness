# Tool Handler Result Contract

The agent runtime must distinguish **tool execution success** from text that
merely looks like an error.

## Return types

Handlers may return ordinary strings for backward compatibility. In that case
`ToolExecutor` treats the call as successful if the Python function returns
normally. **Never** infer failure by scanning output for `Error:`.

Prefer the explicit `ToolOutcome` contract for all new tools:

```python
from tiny_harness._tool_outcome import ToolOutcome

def lookup(args: dict) -> ToolOutcome:
    key = args["key"]
    if key not in STORE:
        return ToolOutcome.error(f"Key {key!r} not found")
    return ToolOutcome.ok(STORE[key])
```

`ToolExecutor` maps `ToolOutcome.error` to `ToolResult.success=False`.
This status feeds the AgentLoop error budget, while `content` remains available
to the model for troubleshooting. Denied HITL calls remain a distinct status.

## First-party built-ins

- File handlers can be called as legacy functions that return strings.
  Skills register them with `structured=True` to expose explicit errors.
- Shell's async handler uses process return code, not stdout/stderr keywords.
  A command that prints `Error: fixture` and exits 0 **succeeds**; a command
  that prints nothing and exits non-zero **fails**.
- Search's typed handler reports ripgrep failures or invalid regex as errors.
  A normal search with no matches is not an error.

## Stream retry invariant

Both provider streaming paths permit automatic retry of 429/529/5xx and selected
connection exceptions **only if no chunk has been yielded**. An output chunk
could already have been shown to the user or used to assemble a tool call;
replay after that point is never automatic. `Retry-After` is capped by the
configured maximum delay.

These tests use `httpx.MockTransport`, not paid live API calls. Test real
providers separately in an opt-in integration environment.

## Follow-up work

- Migrate third-party plugin handlers to structured outcomes.
- Track success/denied/error and duration in emitted tool events.
- Strengthen context accounting with real provider usage and tokenizers.
- Apply OS-level isolation for untrusted Shell execution (workspace path guard
  and approval are **not** sandboxing).
