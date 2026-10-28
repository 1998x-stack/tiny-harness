"""Optional Linux bubblewrap backend for the *registered* async Shell tool.

This constrains visible mounts and removes the host network namespace. It
does not turn Python path guards into OS security, constrain arbitrary other
plugins, or replace cgroup limits / kernel hardening.
"""
from __future__ import annotations

import os
import shutil
import sys


class SandboxUnavailable(RuntimeError):
    """Sandbox requested, but cannot be created safely."""


# Runtime directories containing shared libraries and executables. Never
# recursively bind /, /home, /etc, /root, /run or arbitrary host paths.
_RUNTIME_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
_RUNTIME_FILES = ("/etc/ld.so.cache", "/etc/nsswitch.conf")


def build_bubblewrap_argv(command: str, *, workspace: str, cwd: str | None) -> list[str]:
    """Build an argv array; no untrusted command bytes become bwrap options.

    User commands run through the shell *inside* the namespace. An unavailable
    bwrap executable or unsupported host causes an error, never an unsafe
    fallback to an ordinary subprocess.
    """
    if sys.platform != "linux":
        raise SandboxUnavailable("bubblewrap sandbox is available only on Linux")

    # Resolve bwrap from trusted system binary directories, not cwd/PATH.
    binary = shutil.which("bwrap", path="/usr/bin:/bin")
    if binary is None:
        raise SandboxUnavailable(
            "bubblewrap executable is unavailable; install bwrap or choose "
            "shell_sandbox='off' explicitly"
        )
    if not os.path.isdir(workspace):
        raise SandboxUnavailable("Sandbox workspace must be an existing directory")

    root = os.path.realpath(workspace)
    working_dir = os.path.realpath(cwd or root)
    if os.path.commonpath((root, working_dir)) != root:
        raise SandboxUnavailable("Sandbox cwd is outside workspace")
    if not os.path.isdir(working_dir):
        raise SandboxUnavailable("Sandbox cwd must be an existing directory")

    relative = os.path.relpath(working_dir, root)
    sandbox_cwd = "/workspace" if relative == "." else "/workspace/" + relative.replace(os.sep, "/")

    argv = [
        binary,
        "--unshare-all",             # Includes the network and PID namespaces.
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--tmpfs", "/",             # An empty filesystem root.
    ]

    for path in _RUNTIME_DIRS:
        if os.path.isdir(path):
            argv.extend(("--ro-bind", path, path))
    for path in _RUNTIME_FILES:
        if os.path.isfile(path):
            argv.extend(("--ro-bind", path, path))

    argv.extend((
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/workspace",
        "--bind", root, "/workspace",  # Only writable host mount.
        "--chdir", sandbox_cwd,
        "--",
        "/bin/sh", "-c", command,
    ))
    return argv
