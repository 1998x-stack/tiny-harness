# tiny_harness/tools/shell.py
import shlex
import subprocess

MAX_OUTPUT_CHARS = 50_000

_SHELL_METACHARS = frozenset("|;&<>$`(){}!*?~#")


def _has_shell_syntax(command: str) -> bool:
    """Check if command string contains shell metacharacters (pipes, redirects, etc)."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return True
    for part in parts:
        if any(c in _SHELL_METACHARS for c in part):
            return True
    return False


def _build_args(command: str) -> tuple[list[str] | str, bool]:
    """Parse command into safe arg list when possible.

    If the command has no shell syntax (pipes, redirects, variable expansion),
    it's executed via shell=False with shlex-split args for safety.
    Complex shell syntax falls back to shell=True.
    """
    if not command.strip():
        return command, True
    try:
        parts = shlex.split(command)
    except ValueError:
        return command, True
    if not parts:
        return command, True
    if _has_shell_syntax(command):
        return command, True
    return parts, False


def run_command(args: dict) -> str:
    command = args["command"]
    cwd = args.get("cwd")
    timeout = args.get("timeout", 30)

    # ToolExecutor resolves and validates cwd against AgentConfig.workspace.
    # This low-level handler does not know the configured workspace boundary.

    cmd, use_shell = _build_args(command)
    try:
        result = subprocess.run(
            cmd,
            shell=use_shell,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output = f"[exit code: {result.returncode}]\n{output}"
        if not output.strip():
            output = "(no output)"
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n\n[... truncated at {MAX_OUTPUT_CHARS} characters]"
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"

# The agent registers the async entrypoint below. Unlike the legacy sync helper
# it can stop its whole process group when the executor cancels the coroutine.
async def run_command_async(args: dict) -> str:
    import asyncio
    import os
    import signal

    command = args["command"]
    cwd = args.get("cwd")
    timeout = args.get("timeout", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return "Error: timeout must be positive."

    # Do not let subprocesses inherit provider secrets.
    safe_keys = {"PATH", "HOME", "LANG", "TERM", "TMPDIR", "VIRTUAL_ENV", "PYTHONPATH"}
    environment = {
        key: value for key, value in os.environ.items()
        if key in safe_keys or key.startswith("LC_")
    }

    cmd, use_shell = _build_args(command)
    options = {
        "cwd": cwd,
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": environment,
    }
    if os.name == "posix":
        options["start_new_session"] = True
    if use_shell:
        process = await asyncio.create_subprocess_shell(cmd, **options)
    else:
        process = await asyncio.create_subprocess_exec(*cmd, **options)

    async def read_limited(stream):
        parts = []
        retained = 0
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            if retained < MAX_OUTPUT_CHARS:
                selected = chunk[:MAX_OUTPUT_CHARS - retained]
                parts.append(selected)
                retained += len(selected)
        return b"".join(parts)

    stdout_task = asyncio.create_task(read_limited(process.stdout))
    stderr_task = asyncio.create_task(read_limited(process.stderr))

    def kill_tree():
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()

    try:
        stdout, stderr, _ = await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task, process.wait()),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        kill_tree()
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return f"Error: Command timed out after {timeout}s"

    output = stdout.decode("utf-8", errors="replace")
    if stderr:
        output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
    if process.returncode != 0:
        output = f"[exit code: {process.returncode}]\n" + output
    if not output.strip():
        output = "(no output)"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"\n\n[... truncated at {MAX_OUTPUT_CHARS} characters]"
    return output
