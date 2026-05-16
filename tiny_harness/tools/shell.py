# tiny_harness/tools/shell.py
import shlex
import subprocess

MAX_OUTPUT_CHARS = 50_000

_SHELL_METACHARS = frozenset("|;&<>$`(){}!*?")


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
