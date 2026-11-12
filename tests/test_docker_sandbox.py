"""OCI sandbox argv, fail-closed errors, and opt-in Docker integration."""
import os
import shlex
import shutil
import sys

import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._docker_sandbox import build_docker_argv
from tiny_harness._sandbox import SandboxUnavailable


IMAGE = "alpine@sha256:" + "a" * 64
NAME = "tiny-harness-" + "b" * 24


def _mock_docker(monkeypatch):
    monkeypatch.setattr("tiny_harness._docker_sandbox.shutil.which",
                        lambda name, path=None: "/usr/bin/docker")
    monkeypatch.setattr("tiny_harness._docker_sandbox.os.getuid", lambda: 1001)
    monkeypatch.setattr("tiny_harness._docker_sandbox.os.getgid", lambda: 1002)


def test_immutable_image_and_cgroup_policy_argv(tmp_path, monkeypatch):
    _mock_docker(monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sub = workspace / "nested"
    sub.mkdir()
    payload = "echo token; echo --network=host"
    argv = build_docker_argv(
        payload, workspace=str(workspace), cwd=str(sub), image=IMAGE,
        name=NAME, config_dir=str(tmp_path), memory_mb=256,
        cpus=0.5, pids_limit=16,
    )
    assert argv[:4] == ["/usr/bin/docker", "--config", str(tmp_path), "run"]
    for option in ("--rm", "--pull=never", "--network=none", "--ipc=none",
                   "--read-only", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges:true"):
        assert option in argv
    assert "--memory" in argv and argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--memory-swap") + 1] == "256m"
    assert argv[argv.index("--pids-limit") + 1] == "16"
    assert argv[argv.index("--cpus") + 1] == "0.5"
    assert argv[argv.index("--user") + 1] == "1001:1002"
    assert argv[argv.index("--workdir") + 1] == "/workspace/nested"
    assert argv[argv.index("--mount") + 1].startswith(
        "type=bind,source=" + str(workspace) + ",target=/workspace"
    )
    assert argv[-3:] == [IMAGE, "-c", payload]
    assert "--privileged" not in argv
    assert "--network=host" not in argv
    assert "--pull=always" not in argv
    assert not any("/var/run/docker.sock" in arg for arg in argv)


@pytest.mark.parametrize("image", [
    "alpine:3.20", "docker.io/library/alpine:latest",
    "--privileged", "alpine@sha256:ABC", "", "alpine@sha256:123",
])
def test_reject_unpinned_or_invalid_images(tmp_path, monkeypatch, image):
    _mock_docker(monkeypatch)
    with pytest.raises(SandboxUnavailable, match="pinned"):
        build_docker_argv("true", workspace=str(tmp_path), cwd=None,
                          image=image, name=NAME, config_dir=str(tmp_path))


@pytest.mark.parametrize("field,value", [
    ("memory_mb", 32), ("memory_mb", True),
    ("cpus", 0), ("cpus", 20), ("cpus", True),
    ("pids_limit", 0), ("pids_limit", 10000),
])
def test_unsafe_resource_values_fail_closed(tmp_path, monkeypatch, field, value):
    _mock_docker(monkeypatch)
    kw = {"memory_mb": 512, "cpus": 1.0, "pids_limit": 64}
    kw[field] = value
    with pytest.raises(SandboxUnavailable):
        build_docker_argv("true", workspace=str(tmp_path), cwd=None,
                          image=IMAGE, name=NAME, config_dir=str(tmp_path), **kw)


def test_unsafe_workspace_escape_or_mount_delimiter_fails(tmp_path, monkeypatch):
    _mock_docker(monkeypatch)
    w = tmp_path / "workspace"
    w.mkdir()
    for cwd in (str(tmp_path), str(w / "missing")):
        with pytest.raises(SandboxUnavailable):
            build_docker_argv("true", workspace=str(w), cwd=cwd,
                              image=IMAGE, name=NAME, config_dir=str(tmp_path))
    comma = tmp_path / "work,space"
    comma.mkdir()
    with pytest.raises(SandboxUnavailable, match="mount"):
        build_docker_argv("true", workspace=str(comma), cwd=None,
                          image=IMAGE, name=NAME, config_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_docker_unavailable_never_runs_host_shell(tmp_path, monkeypatch):
    monkeypatch.setattr("tiny_harness._docker_sandbox.shutil.which",
                        lambda name, path=None: None)
    agent = Agent(Prompt("fixture"), Config(
        model="t", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
        shell_sandbox="docker", sandbox_image=IMAGE,
    ))
    agent.load_skill("shell")
    result = await agent._tool_executor.execute(
        "run_command", {"command": "echo canary"}, "call-1",
    )
    assert not result.success
    assert "Docker executable unavailable" in result.content


@pytest.mark.asyncio
async def test_missing_digest_never_starts_a_container(tmp_path):
    agent = Agent(Prompt("fixture"), Config(
        model="t", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True, shell_sandbox="docker",
    ))
    agent.load_skill("shell")
    result = await agent._tool_executor.execute(
        "run_command", {"command": "true"}, "call-2",
    )
    assert not result.success
    assert "digest-pinned" in result.content


@pytest.mark.asyncio
async def test_real_docker_cgroup_network_and_workspace_boundary(tmp_path):
    """Actually execute the container when CI supplies a pulled immutable image."""
    image = os.environ.get("TINY_HARNESS_TEST_DOCKER_IMAGE")
    if not image:
        if os.environ.get("TINY_HARNESS_REQUIRE_DOCKER_INTEGRATION") == "1":
            pytest.fail("Required Docker integration image was not configured")
        pytest.skip("Docker integration requires TINY_HARNESS_TEST_DOCKER_IMAGE")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "host-private-marker.txt"
    secret.write_text("hidden")
    agent = Agent(Prompt("fixture"), Config(
        model="t", api_key="unused", workspace=str(workspace),
        no_hitl=True, allow_unsafe_shell=True,
        shell_sandbox="docker", sandbox_image=image,
        sandbox_memory_mb=256, sandbox_cpus=0.5,
        sandbox_pids_limit=16,
    ))
    agent.load_skill("shell")
    command = (
        "printf cgroup-ok > generated.txt; "
        "test ! -e " + shlex.quote(str(secret)) + "; "
        "test \"$(cat /sys/fs/cgroup/memory.max)\" = 268435456; "
        "test \"$(cat /sys/fs/cgroup/pids.max)\" = 16; "
        "test \"$(awk 'NR>1{n++}END{print n+0}' /proc/net/route)\" = 0; "
        "pwd"
    )
    result = await agent._tool_executor.execute(
        "run_command", {"command": command, "timeout": 20}, "call-3",
    )
    assert result.success, result.content
    assert "/workspace" in result.content
    assert (workspace / "generated.txt").read_text() == "cgroup-ok"
    assert secret.read_text() == "hidden"


@pytest.mark.asyncio
async def test_real_docker_timeout_removes_daemon_container(tmp_path, monkeypatch):
    """A timed-out Docker CLI must not orphan its daemon-owned container."""
    image = os.environ.get("TINY_HARNESS_TEST_DOCKER_IMAGE")
    if not image:
        if os.environ.get("TINY_HARNESS_REQUIRE_DOCKER_INTEGRATION") == "1":
            pytest.fail("Required Docker integration image was not configured")
        pytest.skip("Docker integration requires TINY_HARNESS_TEST_DOCKER_IMAGE")
    import secrets
    import subprocess

    name = "tiny-harness-" + "d" * 24
    monkeypatch.setattr(secrets, "token_hex", lambda count: "d" * 24)
    agent = Agent(Prompt("fixture"), Config(
        model="t", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
        shell_sandbox="docker", sandbox_image=image,
    ))
    agent.load_skill("shell")
    result = await agent._tool_executor.execute(
        "run_command", {"command": "sleep 30", "timeout": 1}, "timeout-1",
    )
    assert not result.success
    assert "timed out" in result.content.lower()
    proc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
        capture_output=True, text=True, check=True, timeout=5,
    )
    assert proc.stdout.strip() == "", "Sandbox container was not removed after timeout"


@pytest.mark.asyncio
async def test_real_docker_cancel_removes_daemon_container(tmp_path, monkeypatch):
    """Client-side task cancellation must also force container teardown."""
    image = os.environ.get("TINY_HARNESS_TEST_DOCKER_IMAGE")
    if not image:
        if os.environ.get("TINY_HARNESS_REQUIRE_DOCKER_INTEGRATION") == "1":
            pytest.fail("Required Docker integration image was not configured")
        pytest.skip("Docker integration requires TINY_HARNESS_TEST_DOCKER_IMAGE")
    import asyncio
    import secrets
    import subprocess

    name = "tiny-harness-" + "e" * 24
    monkeypatch.setattr(secrets, "token_hex", lambda count: "e" * 24)
    agent = Agent(Prompt("fixture"), Config(
        model="t", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
        shell_sandbox="docker", sandbox_image=image,
    ))
    agent.load_skill("shell")
    running = asyncio.create_task(agent._tool_executor.execute(
        "run_command", {"command": "sleep 30", "timeout": 30}, "cancel-1",
    ))
    await asyncio.sleep(0.5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    proc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
        capture_output=True, text=True, check=True, timeout=5,
    )
    assert proc.stdout.strip() == "", "Sandbox container was not removed after cancellation"
