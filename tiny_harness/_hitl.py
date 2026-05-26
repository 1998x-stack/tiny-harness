# tiny_harness/_hitl.py
"""Human-in-the-Loop (HITL) approval gate for agent tool execution.

HITL inserts human judgment at critical decision points:
- High-risk operations (mutation, destructive, dangerous) require human approval
- "Approve for session" reduces repeated prompts
- Timeout defaults to reject for safety

Architecture:
    Agent → AgentLoop → ToolExecutor.execute()
                              ↓
                        ApprovalGate.check()  ← HITL interception
                              ↓
                        ApprovalHandler (user callback)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Callable, Awaitable


@dataclass
class ApprovalDecision:
    """Result of a HITL approval check, returned by the handler."""
    approved: bool
    reason: str = ""
    session_approved: bool = False
    modified_args: dict | None = None


@dataclass
class ToolApprovalRequest:
    """Presented to the approval handler when a tool needs human review."""
    tool_name: str
    args: dict
    risk_level: str
    reason: str = ""


ApprovalHandler = Callable[[ToolApprovalRequest], Awaitable[ApprovalDecision]]

class SessionApprovals:
    """Remembers which risk levels the user has approved for this session.

    If user approves "mutation" for the session, all mutation, read_only,
    and safe tools are auto-approved going forward. Destructive and dangerous
    always require explicit approval regardless of session state.
    """

    _RISK_ORDER = ["safe", "read_only", "mutation", "destructive", "dangerous"]

    def __init__(self) -> None:
        self._approved_levels: set[str] = set()

    def approve_for_session(self, risk_level: str) -> None:
        """Approve this risk level and all lower levels for the session."""
        for level in self._RISK_ORDER:
            self._approved_levels.add(level)
            if level == risk_level:
                break

    def is_approved(self, risk_level: str) -> bool:
        """Check if this risk level was approved for the session."""
        return risk_level in self._approved_levels

    def clear(self) -> None:
        """Reset all session approvals."""
        self._approved_levels.clear()


class ApprovalGate:
    """HITL gate: checks whether a tool needs approval and routes to handler.

    Usage:
        gate = ApprovalGate(handler=my_handler)
        decision = await gate.check("write_file", {"path": "x.txt"}, "mutation")
        if not decision.approved:
            return ToolResult.error(call_id, decision.reason)
    """

    def __init__(
        self,
        handler: ApprovalHandler | None = None,
        session: SessionApprovals | None = None,
        timeout_ms: int = 120_000,
        require_approval_for: set[str] | None = None,
    ) -> None:
        self._handler = handler
        self._session = session or SessionApprovals()
        self._timeout_ms = timeout_ms
        self._require_approval_for = require_approval_for or set()

    @property
    def handler(self) -> ApprovalHandler | None:
        return self._handler

    @handler.setter
    def handler(self, h: ApprovalHandler | None) -> None:
        self._handler = h

    @property
    def session(self) -> SessionApprovals:
        return self._session

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def needs_approval(self, tool_name: str, risk_level: str) -> bool:
        """Check whether this tool requires HITL approval.

        Approval is required when:
        1. The tool is in the explicit require_approval_for set, OR
        2. The risk level is mutation, destructive, or dangerous.
        """
        if tool_name in self._require_approval_for:
            return True
        if risk_level in ("mutation", "destructive", "dangerous"):
            return True
        return False

    async def check(self, tool_name: str, args: dict, risk_level: str) -> ApprovalDecision:
        """Evaluate whether to allow a tool call, consulting the handler if needed.

        Returns:
            ApprovalDecision with approved=True if tool is safe, session-approved,
            or the handler grants permission. approved=False otherwise.
        """
        if not self.needs_approval(tool_name, risk_level):
            return ApprovalDecision(approved=True, reason="auto-approved (low risk)")

        if self._session.is_approved(risk_level):
            return ApprovalDecision(approved=True, reason="session-approved")

        if self._handler is None:
            return ApprovalDecision(
                approved=False,
                reason=f"No approval handler configured. Cannot execute '{tool_name}' (risk: {risk_level})."
            )

        request = ToolApprovalRequest(
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            reason=f"Tool '{tool_name}' requires human approval (risk level: {risk_level})."
        )

        try:
            decision = await asyncio.wait_for(
                self._handler(request), timeout=self._timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            return ApprovalDecision(
                approved=False,
                reason=f"Approval timed out after {self._timeout_ms / 1000}s"
            )

        if decision is None:
            return ApprovalDecision(approved=False, reason="Approval handler returned None")

        if decision.approved and decision.session_approved:
            self._session.approve_for_session(risk_level)

        return decision

    def cancel(self) -> None:
        pass
