"""Security defaults: unclassified tools need approval and shell opt-in is explicit."""
import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry
from tiny_harness._guard import FilesystemGuard
from tiny_harness._hitl import ApprovalDecision, ApprovalGate


def test_tool_risk_default_is_not_read_only():
    tool = ToolDef("third_party_action", "Unclassified plugin", {"type": "object"})
    assert tool.risk_level == "mutation"


@pytest.mark.parametrize("bad", ["", "read", "mutaton", "SAFE", "unknown"])
def test_unknown_risk_levels_fail_at_registration(bad):
    with pytest.raises(ValueError, match="risk_level"):
        ToolDef("plugin", "Untrusted", {"type": "object"}, risk_level=bad)


@pytest.mark.asyncio
async def test_unclassified_plugin_cannot_run_without_approval(tmp_path):
    seen = []
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("plugin_action", "act", {"type": "object"}),
        lambda _: seen.append(1),
    )
    executor = ToolExecutor(
        registry, FilesystemGuard(str(tmp_path)), approval_gate=ApprovalGate(),
    )
    result = await executor.execute("plugin_action", {}, "one")
    assert result.denied
    assert seen == []


@pytest.mark.asyncio
async def test_safe_risk_does_not_disable_workspace_guard(tmp_path):
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("read_file", "read", {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]}, risk_level="safe"),
        lambda args: "not reached",
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(tmp_path)))
    result = await executor.execute("read_file", {"path": str(tmp_path.parent)}, "one")
    assert not result.success
    assert "outside" in result.content


@pytest.mark.asyncio
async def test_unattended_shell_cannot_run_without_explicit_optin(tmp_path):
    seen = []
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("run_command", "run", {"type": "object", "properties": {
            "command": {"type": "string"},
        }, "required": ["command"]}, risk_level="dangerous"),
        lambda args: seen.append(args),
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(tmp_path)))
    denied = await executor.execute("run_command", {"command": "echo fixture"}, "one")
    assert denied.denied and not seen
    assert "allow_unsafe_shell" in denied.content

    allowed = ToolExecutor(
        registry, FilesystemGuard(str(tmp_path)), allow_unsafe_shell=True,
    )
    result = await allowed.execute("run_command", {"command": "echo fixture"}, "two")
    assert result.success and len(seen) == 1


def test_no_hitl_shell_skill_needs_optin(tmp_path):
    agent = Agent(Prompt("fixture"), Config(
        model="fixture", api_key="unused", workspace=str(tmp_path), no_hitl=True,
    ))
    with pytest.raises(ValueError, match="allow_unsafe_shell"):
        agent.load_skill("shell")
    assert not agent.tools.names()

    unsafe = Agent(Prompt("fixture"), Config(
        model="fixture", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
    ))
    unsafe.load_skill("shell")
    assert "run_command" in unsafe.tools.names()


@pytest.mark.asyncio
async def test_explicit_approval_still_allows_shell_without_unsafe_optin(tmp_path):
    async def handler(request):
        assert request.risk_level == "dangerous"
        return ApprovalDecision(approved=True)
    registry = ToolRegistry()
    registry.register_from_def(ToolDef(
        "run_command", "demo", {"type": "object"}, "dangerous",
    ), lambda args: "ok")
    executor = ToolExecutor(registry, FilesystemGuard(str(tmp_path)),
                            approval_gate=ApprovalGate(handler=handler))
    result = await executor.execute("run_command", {}, "one")
    assert result.success
