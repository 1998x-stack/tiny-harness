"""High-risk approval is per-call and logical sessions do not share grants."""
import pytest
from tiny_harness import Agent, Config, Prompt
from tiny_harness._hitl import ApprovalDecision, ApprovalGate


@pytest.mark.asyncio
async def test_high_risk_session_grant_does_not_skip_second_approval():
    seen = []

    async def approve(request):
        seen.append(request.tool_name)
        return ApprovalDecision(approved=True, session_approved=True)

    gate = ApprovalGate(handler=approve)
    first = await gate.check("run_command", {"command": "pwd"}, "dangerous")
    second = await gate.check("run_command", {"command": "pwd"}, "dangerous")
    assert first.approved and second.approved
    assert seen == ["run_command", "run_command"]
    assert not gate.session.is_approved("dangerous")


@pytest.mark.asyncio
async def test_destructive_grant_does_not_skip_second_approval():
    seen = []

    async def approve(request):
        seen.append(request.tool_name)
        return ApprovalDecision(approved=True, session_approved=True)

    gate = ApprovalGate(handler=approve)
    await gate.check("delete_file", {"path": "unused.txt"}, "destructive")
    await gate.check("delete_file", {"path": "unused.txt"}, "destructive")
    assert seen == ["delete_file", "delete_file"]


def test_agent_clear_forgets_session_approvals():
    agent = Agent(Prompt("test"), Config(model="t", api_key="unused", workspace="."))
    agent.approval_gate.session.approve_for_session("mutation")
    assert agent.approval_gate.session.is_approved("mutation")
    agent.clear()
    assert not agent.approval_gate.session.is_approved("mutation")
