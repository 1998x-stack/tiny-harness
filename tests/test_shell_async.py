"""Registered shell skill uses a cancellable process-group-aware handler."""
import asyncio
import os
import shlex

import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness.tools.shell import run_command_async


def _make_agent(tmp_path):
    agent = Agent(Prompt("test"), Config(model="t", api_key="unused", workspace=str(tmp_path)))
    agent.load_skill("shell")
    return agent


@pytest.mark.asyncio
async def test_registered_shell_handler_is_async(tmp_path):
    agent = _make_agent(tmp_path)
    handler = agent.tools.get("run_command").handler
    assert asyncio.iscoroutinefunction(handler)
    result = await agent._tool_executor.execute(
        "run_command", {"command": "pwd"}, "tc1"
    )
    # The default HITL gate fails closed without an approval handler.
    assert not result.success


@pytest.mark.asyncio
async def test_shell_does_not_inherit_llm_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-fixture-value")
    output = await run_command_async({"command": "env", "cwd": str(tmp_path)})
    assert "OPENAI_API_KEY" not in output
    assert "private-fixture-value" not in output


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.asyncio
async def test_timeout_kills_child_processes_before_side_effect(tmp_path):
    agent = _make_agent(tmp_path)
    marker = tmp_path / "later-marker.txt"
    command = "sleep 0.5; printf marker > " + shlex.quote(str(marker))
    agent._tool_executor._timeout_ms = 75
    # A test policy grants only this harmless fixture command.
    async def approve(request):
        from tiny_harness._hitl import ApprovalDecision
        return ApprovalDecision(approved=True)
    agent.set_approval_handler(approve)
    result = await agent._tool_executor.execute(
        "run_command", {"command": command, "timeout": 3}, "tc2"
    )
    assert not result.success
    assert "timed out" in result.content.lower()
    await asyncio.sleep(0.65)
    assert not marker.exists()
