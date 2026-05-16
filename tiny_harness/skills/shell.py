# tiny_harness/skills/shell.py
from tiny_harness.tools.shell import run_command
from tiny_harness._tools import ToolDef

SHELL_PROMPT = """
## Shell Commands

You can execute shell commands with run_command(command, cwd?, timeout?).
- Use for git, pip, npm, python, ls, cat, and other terminal operations.
- For file reading/writing, prefer read_file/write_file tools.
- NEVER run destructive commands (rm -rf, format, etc.) without asking.
- Commands time out after 30 seconds by default.
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(
            name="run_command",
            description="Execute a shell command. Use for git, build tools, package managers. WARNING: be careful with destructive commands.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "cwd": {"type": "string", "description": "Working directory for the command."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds. Default: 30."},
                },
                "required": ["command"],
            },
            risk_level="dangerous",
        ),
        run_command,
    )
    agent._prompt.append(SHELL_PROMPT)
