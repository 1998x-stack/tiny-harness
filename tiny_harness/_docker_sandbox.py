"""Opt-in OCI Docker execution with aggregate cgroup ceilings.

The Docker daemon is a privileged trust boundary. This is designed for a
trusted local daemon only; it is NOT a remote multi-tenant sandbox service.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

from tiny_harness._sandbox import SandboxUnavailable


_IMAGE_DIGEST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[0-9a-f]{64}\Z")
_CONTAINER_NAME = re.compile(r"tiny-harness-[0-9a-f]{24}\Z")


def build_docker_argv(
    command: str, *, workspace: str, cwd: str | None, image: str,
    name: str, config_dir: str, memory_mb: int = 1024,
    cpus: float = 1.0, pids_limit: int = 64,
) -> list[str]:
    """Construct an isolated, resource-limited Docker CLI invocation.

    Images must be pre-pulled and referenced by immutable digest. No shell
    interpolation, automatic pull, remote Docker host, privileged mode,
    socket mount, or broad filesystem bind.
    """
    if sys.platform != "linux":
        raise SandboxUnavailable("Docker sandbox currently requires Linux")
    docker = shutil.which("docker", path="/usr/bin:/bin:/usr/local/bin")
    if docker is None:
        raise SandboxUnavailable("Docker executable unavailable; refusing unsandboxed fallback")
    if not _IMAGE_DIGEST.fullmatch(image):
        raise SandboxUnavailable("Docker sandbox image must be pinned using @sha256:<64 hex>")
    if not _CONTAINER_NAME.fullmatch(name):
        raise SandboxUnavailable("Invalid sandbox container name")
    if not config_dir or not os.path.isdir(config_dir):
        raise SandboxUnavailable("Private Docker CLI config directory is required")
    if not isinstance(memory_mb, int) or isinstance(memory_mb, bool) or not (64 <= memory_mb <= 16384):
        raise SandboxUnavailable("sandbox_memory_mb must be between 64 and 16384")
    if isinstance(cpus, bool) or not isinstance(cpus, (int, float)) or not (0.1 <= cpus <= 8.0):
        raise SandboxUnavailable("sandbox_cpus must be between 0.1 and 8.0")
    if not isinstance(pids_limit, int) or isinstance(pids_limit, bool) or not (8 <= pids_limit <= 512):
        raise SandboxUnavailable("sandbox_pids_limit must be between 8 and 512")
    if not hasattr(os, "getuid") or os.getuid() == 0:
        raise SandboxUnavailable("Docker sandbox requires a non-root host identity")
    if not os.path.isdir(workspace):
        raise SandboxUnavailable("Sandbox workspace must be an existing directory")

    root = os.path.realpath(workspace)
    working_dir = os.path.realpath(cwd or root)
    if os.path.commonpath((root, working_dir)) != root:
        raise SandboxUnavailable("Sandbox cwd is outside workspace")
    if not os.path.isdir(working_dir):
        raise SandboxUnavailable("Sandbox cwd must be an existing directory")
    # Docker --mount parses commas. Reject ambiguous input rather than allowing
    # data from a workspace name to be parsed as extra mount options.
    if "," in root or "\n" in root or "\r" in root:
        raise SandboxUnavailable("Sandbox workspace contains unsupported mount delimiters")
    relative = os.path.relpath(working_dir, root)
    container_cwd = "/workspace" if relative == "." else "/workspace/" + relative.replace(os.sep, "/")

    return [
        docker, "--config", config_dir, "run", "--rm",
        "--pull=never",
        "--name", name,
        "--network=none",
        "--ipc=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit", str(pids_limit),
        "--memory", f"{memory_mb}m",
        "--memory-swap", f"{memory_mb}m",
        "--cpus", str(cpus),
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount", f"type=bind,source={root},target=/workspace,bind-propagation=rprivate",
        "--workdir", container_cwd,
        "--env", "HOME=/tmp", "--env", "PATH=/usr/bin:/bin",
        "--entrypoint", "/bin/sh",
        image, "-c", command,
    ]
