"""Shell execution stays inside AgentConfig.workspace regardless of process cwd."""
import os
import pytest

from tiny_harness._guard import FilesystemGuard
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry
from tiny_harness.tools.shell import run_command


@pytest.mark.asyncio
async def test_shell_cwd_defaults_to_configured_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef(
            "run_command", "shell",
            {"type": "object", "properties": {
                "command": {"type": "string"}, "cwd": {"type": "string"}
            }, "required": ["command"]},
            "dangerous",
        ),
        run_command,
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(workspace)), allow_unsafe_shell=True)
    for args in ({"command": "pwd"}, {"command": "pwd", "cwd": "."}):
        result = await executor.execute("run_command", args, "shell-1")
        assert result.success
        assert os.path.realpath(result.content.strip()) == str(workspace)

    outside = await executor.execute(
        "run_command", {"command": "pwd", "cwd": str(elsewhere)}, "shell-2"
    )
    assert not outside.success
    assert "outside" in outside.content
