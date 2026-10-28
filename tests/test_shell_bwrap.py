"""Bubblewrap boundary tests: fail-closed launch and host filesystem separation."""
import os
import shutil
import sys

import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._sandbox import SandboxUnavailable, build_bubblewrap_argv


@pytest.fixture
def workspace(tmp_path):
    d = tmp_path / "workspace"
    d.mkdir()
    return d


def test_sandbox_command_is_structured_and_never_interpolated(workspace, monkeypatch):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/bwrap")
    marker = "echo hello; printf 'unsafe?'; echo --ro-bind"
    argv = build_bubblewrap_argv(marker, workspace=str(workspace), cwd=None)
    assert argv[0] == "/usr/bin/bwrap"
    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert "--die-with-parent" in argv
    assert "--new-session" in argv
    assert "--bind" in argv and str(workspace) in argv
    assert "--ro-bind" in argv
    assert "--proc" in argv and "--dev" in argv
    assert "--tmpfs" in argv
    assert "--share-net" not in argv
    assert "--ro-bind-try" not in argv
    assert argv[-3:] == ["/bin/sh", "-c", marker]
    assert argv[argv.index("--chdir") + 1] == "/workspace"
    # The container root is isolated; host / and /etc are not bulk mounted.
    assert not any(
        argv[i:i+3] in (["--ro-bind", "/", "/"], ["--ro-bind", "/etc", "/etc"])
        for i in range(len(argv) - 2)
    )


def test_sandbox_maps_nested_working_directory(workspace, monkeypatch):
    (workspace / "nested").mkdir()
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/bwrap")
    argv = build_bubblewrap_argv(
        "pwd", workspace=str(workspace), cwd=str(workspace / "nested")
    )
    assert argv[argv.index("--chdir") + 1] == "/workspace/nested"


def test_sandbox_blocks_workspace_escape_and_missing_cwd(workspace, tmp_path, monkeypatch):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/bwrap")
    for cwd in (str(tmp_path), str(workspace / "missing")):
        with pytest.raises(SandboxUnavailable):
            build_bubblewrap_argv("true", workspace=str(workspace), cwd=cwd)


@pytest.mark.asyncio
async def test_missing_bwrap_fails_closed_for_registered_tool(workspace, monkeypatch):
    monkeypatch.setattr("tiny_harness._sandbox.shutil.which",
                        lambda name, path=None: None)
    agent = Agent(Prompt("fixture"), Config(
        model="fixture", api_key="unused", workspace=str(workspace),
        no_hitl=True, allow_unsafe_shell=True, shell_sandbox="bubblewrap",
    ))
    agent.load_skill("shell")
    result = await agent._tool_executor.execute(
        "run_command", {"command": "echo expected"}, "c1"
    )
    assert not result.success
    assert "bubblewrap executable is unavailable" in result.content


def test_invalid_sandbox_config_is_rejected(workspace):
    with pytest.raises(ValueError, match="shell_sandbox"):
        Agent(Prompt("fixture"), Config(
            model="fixture", api_key="unused", workspace=str(workspace),
            shell_sandbox="unknown"
        ))


def _bwrap_works(workspace):
    if sys.platform != "linux" or shutil.which("bwrap", path="/usr/bin:/bin") is None:
        return False
    import subprocess
    try:
        argv = build_bubblewrap_argv("true", workspace=str(workspace), cwd=None)
        return subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired, SandboxUnavailable):
        return False


@pytest.mark.asyncio
async def test_real_namespace_hides_host_files_and_writes_only_workspace(workspace, tmp_path):
    # CI may disable unprivileged user namespaces. Report a skip instead of
    # claiming an isolation smoke test passed when the host cannot run bwrap.
    if not _bwrap_works(workspace):
        pytest.skip("bubblewrap or unprivileged namespaces unavailable on runner")

    outside = tmp_path / "host-secret-marker.txt"
    outside.write_text("not-visible")
    agent = Agent(Prompt("fixture"), Config(
        model="fixture", api_key="unused", workspace=str(workspace),
        no_hitl=True, allow_unsafe_shell=True, shell_sandbox="bubblewrap",
    ))
    agent.load_skill("shell")
    command = (
        'pwd; printf "sandbox-write" > generated.txt; '
        'test ! -e /etc/passwd && test ! -e ' + str(outside)
    )
    result = await agent._tool_executor.execute(
        "run_command", {"command": command}, "c2"
    )
    assert result.success, result.content
    assert "/workspace" in result.content
    assert (workspace / "generated.txt").read_text() == "sandbox-write"
    assert outside.read_text() == "not-visible"
