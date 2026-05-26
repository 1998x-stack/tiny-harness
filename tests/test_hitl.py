# tests/test_hitl.py
import asyncio
import pytest
from tiny_harness._hitl import (
    ApprovalDecision,
    ToolApprovalRequest,
    SessionApprovals,
    ApprovalGate,
)
from tiny_harness._tools import ToolDef, ToolRegistry, ToolExecutor, ToolResult
from tiny_harness._guard import FilesystemGuard
from tiny_harness._events import EventBus


def test_session_approvals_default_not_approved():
    sa = SessionApprovals()
    assert sa.is_approved("read_only") is False
    assert sa.is_approved("mutation") is False
    assert sa.is_approved("destructive") is False


def test_session_approvals_cascade_upward():
    sa = SessionApprovals()
    sa.approve_for_session("mutation")
    assert sa.is_approved("safe") is True
    assert sa.is_approved("read_only") is True
    assert sa.is_approved("mutation") is True
    assert sa.is_approved("destructive") is False
    assert sa.is_approved("dangerous") is False


def test_session_approvals_destructive_not_cascaded():
    sa = SessionApprovals()
    sa.approve_for_session("destructive")
    assert sa.is_approved("mutation") is True
    assert sa.is_approved("destructive") is True
    assert sa.is_approved("dangerous") is False


def test_session_approvals_dangerous_covers_all():
    sa = SessionApprovals()
    sa.approve_for_session("dangerous")
    for level in ["safe", "read_only", "mutation", "destructive", "dangerous"]:
        assert sa.is_approved(level) is True


def test_session_approvals_clear():
    sa = SessionApprovals()
    sa.approve_for_session("mutation")
    assert sa.is_approved("mutation") is True
    sa.clear()
    assert sa.is_approved("mutation") is False


def test_needs_approval_read_only():
    gate = ApprovalGate()
    assert gate.needs_approval("read_file", "read_only") is False


def test_needs_approval_safe():
    gate = ApprovalGate()
    assert gate.needs_approval("calc", "safe") is False


def test_needs_approval_mutation():
    gate = ApprovalGate()
    assert gate.needs_approval("write_file", "mutation") is True


def test_needs_approval_destructive():
    gate = ApprovalGate()
    assert gate.needs_approval("delete_file", "destructive") is True


def test_needs_approval_dangerous():
    gate = ApprovalGate()
    assert gate.needs_approval("run_command", "dangerous") is True


def test_needs_approval_explicit_list():
    gate = ApprovalGate(require_approval_for={"read_file"})
    assert gate.needs_approval("read_file", "read_only") is True


@pytest.mark.asyncio
async def test_check_auto_approves_safe():
    gate = ApprovalGate()
    decision = await gate.check("calc", {}, "safe")
    assert decision.approved is True
    assert "auto-approved" in decision.reason


@pytest.mark.asyncio
async def test_check_auto_approves_read_only():
    gate = ApprovalGate()
    decision = await gate.check("read_file", {}, "read_only")
    assert decision.approved is True


@pytest.mark.asyncio
async def test_check_session_approved():
    session = SessionApprovals()
    session.approve_for_session("mutation")
    gate = ApprovalGate(session=session)
    decision = await gate.check("write_file", {}, "mutation")
    assert decision.approved is True
    assert "session-approved" in decision.reason


@pytest.mark.asyncio
async def test_check_no_handler_rejects():
    gate = ApprovalGate(handler=None)
    decision = await gate.check("write_file", {}, "mutation")
    assert decision.approved is False
    assert "No approval handler" in decision.reason


@pytest.mark.asyncio
async def test_check_handler_approves():
    async def handler(req):
        return ApprovalDecision(approved=True)
    gate = ApprovalGate(handler=handler)
    decision = await gate.check("write_file", {"path": "x.txt"}, "mutation")
    assert decision.approved is True


@pytest.mark.asyncio
async def test_check_handler_rejects():
    async def handler(req):
        return ApprovalDecision(approved=False, reason="nope")
    gate = ApprovalGate(handler=handler)
    decision = await gate.check("delete_file", {"path": "x.txt"}, "destructive")
    assert decision.approved is False
    assert "nope" in decision.reason


@pytest.mark.asyncio
async def test_check_handler_session_approve():
    async def handler(req):
        return ApprovalDecision(approved=True, session_approved=True)
    session = SessionApprovals()
    gate = ApprovalGate(handler=handler, session=session)
    decision = await gate.check("write_file", {}, "mutation")
    assert decision.approved is True
    assert decision.session_approved is True
    assert session.is_approved("mutation") is True


@pytest.mark.asyncio
async def test_check_handler_receives_request_data():
    async def handler(req):
        assert req.tool_name == "write_file"
        assert req.args == {"path": "test.txt"}
        assert req.risk_level == "mutation"
        return ApprovalDecision(approved=True)
    gate = ApprovalGate(handler=handler)
    await gate.check("write_file", {"path": "test.txt"}, "mutation")


@pytest.mark.asyncio
async def test_check_handler_returns_none():
    async def handler(req):
        return None
    gate = ApprovalGate(handler=handler)
    decision = await gate.check("write_file", {}, "mutation")
    assert decision.approved is False
    assert "returned None" in decision.reason


@pytest.mark.asyncio
async def test_check_timeout():
    async def slow_handler(req):
        await asyncio.sleep(10)
        return ApprovalDecision(approved=True)
    gate = ApprovalGate(handler=slow_handler, timeout_ms=50)
    decision = await gate.check("write_file", {}, "mutation")
    assert decision.approved is False
    assert "timed out" in decision.reason


def test_approval_gate_handler_getter_setter():
    gate = ApprovalGate()
    assert gate.handler is None
    async def h(req):
        return ApprovalDecision(approved=True)
    gate.handler = h
    assert gate.handler is h
    gate.handler = None
    assert gate.handler is None


def test_approval_gate_session_property():
    session = SessionApprovals()
    gate = ApprovalGate(session=session)
    assert gate.session is session


def test_approval_gate_timeout_property():
    gate = ApprovalGate(timeout_ms=999)
    assert gate.timeout_ms == 999


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register_from_def(
        ToolDef(name="write_file", description="Write a file",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                risk_level="mutation"),
        lambda args: f"wrote {args['path']}",
    )
    r.register_from_def(
        ToolDef(name="read_file", description="Read a file",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                risk_level="read_only"),
        lambda args: f"read {args['path']}",
    )
    return r


@pytest.mark.asyncio
async def test_executor_without_approval_gate_executes(registry):
    """Backward compat: executor works without approval_gate."""
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"))
    result = await executor.execute("read_file", {"path": "/tmp/test.txt"}, "tc1")
    assert result.success is True


@pytest.mark.asyncio
async def test_executor_approval_denies_mutation(registry):
    async def deny_handler(req):
        return ApprovalDecision(approved=False, reason="test denial")
    gate = ApprovalGate(handler=deny_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate)
    result = await executor.execute("write_file", {"path": "/tmp/test.txt"}, "tc2")
    assert result.success is False
    assert result.denied is True
    assert "denied" in result.content
    assert "test denial" in result.content


@pytest.mark.asyncio
async def test_executor_approval_allows_mutation(registry):
    async def allow_handler(req):
        return ApprovalDecision(approved=True)
    gate = ApprovalGate(handler=allow_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate)
    result = await executor.execute("write_file", {"path": "/tmp/test.txt"}, "tc3")
    assert result.success is True
    assert "wrote" in result.content


@pytest.mark.asyncio
async def test_executor_approval_skips_read_only(registry):
    """Read-only tools bypass approval even with gate present."""
    call_count = 0

    async def counting_handler(req):
        nonlocal call_count
        call_count += 1
        return ApprovalDecision(approved=True)

    gate = ApprovalGate(handler=counting_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate)
    result = await executor.execute("read_file", {"path": "/tmp/test.txt"}, "tc4")
    assert result.success is True
    assert call_count == 0  # handler never called for read_only


def test_approval_decision_defaults():
    d = ApprovalDecision(approved=True)
    assert d.approved is True
    assert d.reason == ""
    assert d.session_approved is False
    assert d.modified_args is None


def test_approval_decision_with_reason():
    d = ApprovalDecision(approved=False, reason="not allowed")
    assert d.approved is False
    assert d.reason == "not allowed"


def test_tool_approval_request():
    req = ToolApprovalRequest(
        tool_name="delete_file",
        args={"path": "/tmp/x.txt"},
        risk_level="destructive",
        reason="test",
    )
    assert req.tool_name == "delete_file"
    assert req.args == {"path": "/tmp/x.txt"}
    assert req.risk_level == "destructive"
    assert req.reason == "test"


def test_tool_result_denied_factory():
    result = ToolResult.denial("tc1", "not allowed")
    assert result.success is False
    assert result.denied is True
    assert result.tool_call_id == "tc1"
    assert "not allowed" in result.content


@pytest.mark.asyncio
async def test_executor_emits_tool_denied_event(registry):
    events = []

    async def collector(event):
        events.append((event.type, event.tool_name, event.message))

    bus = EventBus()
    bus.subscribe(collector)

    async def deny_handler(req):
        return ApprovalDecision(approved=False, reason="test denial")

    gate = ApprovalGate(handler=deny_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate, event_bus=bus)
    await executor.execute("write_file", {"path": "/tmp/test.txt"}, "tc5")

    denied_events = [e for e in events if e[0] == "tool_denied"]
    assert len(denied_events) == 1
    assert denied_events[0][1] == "write_file"
    assert "test denial" in denied_events[0][2]


@pytest.mark.asyncio
async def test_executor_no_event_for_read_only(registry):
    events = []

    async def collector(event):
        events.append(event.type)

    bus = EventBus()
    bus.subscribe(collector)

    gate = ApprovalGate()
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate, event_bus=bus)
    await executor.execute("read_file", {"path": "/tmp/test.txt"}, "tc6")

    assert "tool_denied" not in events


@pytest.mark.asyncio
async def test_executor_modified_args(registry):
    async def modify_handler(req):
        modified = dict(req.args)
        modified["path"] = "/tmp/modified.txt"
        return ApprovalDecision(approved=True, modified_args=modified)

    gate = ApprovalGate(handler=modify_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate)
    result = await executor.execute("write_file", {"path": "/tmp/original.txt"}, "tc7")
    assert result.success is True
    assert "modified.txt" in result.content
    assert "original.txt" not in result.content


@pytest.mark.asyncio
async def test_executor_modified_args_reguarded(registry):
    async def modify_handler(req):
        return ApprovalDecision(approved=True, modified_args={"path": "/etc/passwd"})

    gate = ApprovalGate(handler=modify_handler)
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), approval_gate=gate)
    result = await executor.execute("write_file", {"path": "/tmp/original.txt"}, "tc8")
    assert result.success is False
    assert "outside" in result.content.lower() or "denied" in result.content.lower()
