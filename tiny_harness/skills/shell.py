# tiny_harness/skills/shell.py
from tiny_harness.tools.shell import run_command
from tiny_harness._tools import ToolDef

SHELL_PROMPT = """
## Shell Commands

You can execute shell commands to interact with the system. Use for operations that don't have dedicated tools.

### run_command(command, cwd?, timeout?)

Execute a shell command and return stdout, stderr, and exit code.

**When to use:**
- Git operations: `git status`, `git diff`, `git log`, `git add`, `git commit`
- Package management: `pip install`, `npm install`, `cargo build`
- Running scripts: `python script.py`, `bash deploy.sh`
- System inspection: `ls`, `cat`, `wc`, `find`, `grep`
- Build/test: `pytest`, `ruff check`, `mypy`

**When NOT to use (use dedicated tools instead):**
- Reading files → use read_file (faster, handles large files)
- Writing files → use write_file (safer, auto-creates dirs)
- Searching code → use search_content (structured output, regex)
- Listing directories → use list_directory (formatted output)

### Understanding output

Commands return three pieces of information:
- **stdout**: Main output (what the command prints).
- **stderr**: Error/warning output, shown in a `[stderr]` section.
- **Exit code**: 0 = success, non-zero = error. Shown as `[exit code: N]`.

If a command returns a non-zero exit code, it FAILED. Read the stderr to understand why, then try a different approach or fix the command.

### Safety Rules

1. **NEVER run destructive commands** without explicit user request:
   - Forbidden: `rm -rf`, `sudo`, `format`, `dd`, `mkfs`, `chmod 777`, etc.
   - Always ask yourself: "Can this command delete or corrupt data?"

2. **Prefer specific over broad**: `rm src/old_file.py` not `rm -rf *`.

3. **Set timeouts** for long-running commands: `timeout=10` for quick checks.

4. **Use absolute or workspace-relative paths** — avoid `cd` before commands.

5. **Verify after mutation**: after git commit, run `git log -1` to confirm.

6. **Output is truncated at 50K characters** — use more specific commands for large output.

### Common Patterns

- Check project state: `git status`, `git diff --stat`
- Run tests: `python -m pytest tests/ -x --tb=short`
- Count/locate: `find . -name '*.py' | wc -l`
- Check Python version: `python --version`
- List git history: `git log --oneline -10`

### Error Handling

- "Command timed out" → reduce scope or increase timeout.
- "exit code: 1" → the command failed. Read stderr for details.
- "command not found" → the tool isn't installed. Use an alternative.

### Chain of Thought

Before running any shell command, ask yourself:
1. Is there a dedicated tool that does this better? (read_file, search_content, etc.)
2. Is this command safe? (no destructive operations)
3. What's the expected output? (stdout, exit code 0)
4. If this fails, what's my fallback?
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(
            name="run_command",
            description="Execute a shell command and return stdout, stderr, and exit code. Use for git, build tools, package managers, and scripts. WARNING: Do NOT run destructive commands (rm -rf, sudo, format) unless explicitly requested. Output is truncated at 50K characters.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute. Keep it focused and specific."},
                    "cwd": {"type": "string", "description": "Working directory. Default: workspace root."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 30. Use higher values for builds/tests."},
                },
                "required": ["command"],
            },
            risk_level="dangerous",
        ),
        run_command,
    )
    agent._prompt.append(SHELL_PROMPT)
