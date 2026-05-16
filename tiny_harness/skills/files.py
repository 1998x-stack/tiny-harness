# tiny_harness/skills/files.py
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file,
)
from tiny_harness._tools import ToolDef


FILES_PROMPT_SECTION = """
## File Operations

You have filesystem access through these tools:
- read_file(path, offset?, limit?): Read file contents.
- write_file(path, content): Create or overwrite a file.
- list_directory(path?, pattern?, recursive?): List directory contents.
- find_files(pattern, path?): Find files by glob pattern.
- delete_file(path): Permanently delete a file. WARNING: irreversible.
- create_directory(path): Create a directory and parents.
- move_file(source, destination): Move or rename a file.

Guidelines:
1. Always verify writes by reading the file back
2. Use specific paths - don't guess file locations
3. Use find_files to discover files before reading them
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(name="read_file", description="Read file contents.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}, risk_level="read_only"),
        read_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="write_file", description="Create or overwrite a file.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, risk_level="mutation"),
        write_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="list_directory", description="List directory contents.", parameters={"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}, "recursive": {"type": "boolean"}}}, risk_level="read_only"),
        list_directory,
    )
    agent.tools.register_from_def(
        ToolDef(name="find_files", description="Find files matching a glob pattern.", parameters={"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["pattern"]}, risk_level="read_only"),
        find_files,
    )
    agent.tools.register_from_def(
        ToolDef(name="delete_file", description="Permanently delete a file.", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level="destructive"),
        delete_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="create_directory", description="Create a directory.", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level="mutation"),
        create_directory,
    )
    agent.tools.register_from_def(
        ToolDef(name="move_file", description="Move or rename a file.", parameters={"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]}, risk_level="mutation"),
        move_file,
    )
    agent._prompt.append(FILES_PROMPT_SECTION)
