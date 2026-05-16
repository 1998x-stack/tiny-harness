# tiny_harness/tools/shell.py
import subprocess


def run_command(args: dict) -> str:
    command = args["command"]
    cwd = args.get("cwd")
    timeout = args.get("timeout", 30)

    try:
        result = subprocess.run(
            command,
            shell=True,
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
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
