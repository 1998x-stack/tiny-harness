# tiny_harness/skills/files.py
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file,
)
from tiny_harness._tools import ToolDef


FILES_PROMPT_SECTION = """
## File Operations

You have full filesystem access within the workspace. All paths are relative to the workspace root unless absolute.

### Tools

**read_file(path, offset?, limit?)**
Read file contents as text. Binary files return size/type descriptions.
- Use `offset` and `limit` for large files — read sections instead of entire files.
- After writing a file, always read it back to verify correctness.
- If a file doesn't exist, the error will tell you. Use find_files to discover files first.

**write_file(path, content)**
Create or overwrite a file. Parent directories are created automatically.
- Overwrites without confirmation — check with read_file first if unsure.
- For appending, read the file, modify content, then write back.
- For configuration changes, prefer editing over full rewrite when possible.

**list_directory(path?, pattern?, recursive?)**
List files and subdirectories with sizes and types.
- Use to understand project structure before making changes.
- `pattern` filters by glob (e.g., "*.py" for Python files only).
- `recursive=true` shows the full tree; omit for single-level listing.

**find_files(pattern, path?, max_results?)**
Find files by glob pattern. Supports recursive wildcards like `**/*.py`.
- Use before read_file to discover file locations.
- Use specific patterns to narrow results: `src/**/*test*` not `*`.

**delete_file(path)**
Permanently delete a file. IRREVERSIBLE.
- Never delete without strong justification. Prefer move_file to archive.
- Always list_directory or read_file first to confirm what you're deleting.

**create_directory(path)**
Create a directory and all needed parents. Safe if directory already exists.

**move_file(source, destination)**
Move or rename a file or directory. Overwrites destination silently.
- Use for renaming, reorganizing, or archiving files.
- Prefer move_file over delete_file for "removing" files.

### Workflows

Discover → Read → Write → Verify is the standard pattern:
1. `find_files` or `list_directory` to locate files
2. `read_file` to examine contents (use offset/limit for large files)
3. `write_file` to create or modify
4. `read_file` again to verify the result

### Error Handling

- "File not found" → check the path with list_directory, or try find_files.
- "Is a directory" → use list_directory instead of read_file.
- "Permission denied" → the path is outside the workspace. Use a different location.
- All errors are informative — read them carefully and try a different approach.

### Do NOT

- Guess file paths. Discover with find_files or list_directory first.
- Read entire large files (>1000 lines). Use offset/limit to read sections.
- Delete files unless explicitly asked or absolutely necessary.
- Write to locations outside the project structure unless requested.
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(name="read_file", description="Read file contents from the filesystem. Returns text content. For large files, use offset and limit to read specific sections. Binary files return a size/type description instead of raw content.", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file to read."}, "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed). Default: 1."}, "limit": {"type": "integer", "description": "Maximum number of lines to read. Omit to read the entire file."}}, "required": ["path"]}, risk_level="read_only"),
        read_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="write_file", description="Create a new file or overwrite an existing one. Auto-creates parent directories. WARNING: Overwrites existing files without confirmation. Verify with read_file if unsure about current contents.", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file to create or overwrite."}, "content": {"type": "string", "description": "The text content to write to the file."}}, "required": ["path", "content"]}, risk_level="mutation"),
        write_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="list_directory", description="List files and subdirectories in a directory. Shows names, types (file/dir), and sizes. Use to understand project structure before making changes.", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Directory to list. Default: current directory."}, "pattern": {"type": "string", "description": "Glob pattern to filter (e.g., '*.py')."}, "recursive": {"type": "boolean", "description": "List recursively if true. Default: false."}}}, risk_level="read_only"),
        list_directory,
    )
    agent.tools.register_from_def(
        ToolDef(name="find_files", description="Find files matching a glob pattern. Supports recursive wildcards like '**/*.py'. Use to discover file locations before reading them.", parameters={"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py', 'src/**/*test*')."}, "path": {"type": "string", "description": "Directory to search in. Default: current directory."}, "max_results": {"type": "integer", "description": "Maximum number of results. Default: 200."}}, "required": ["pattern"]}, risk_level="read_only"),
        find_files,
    )
    agent.tools.register_from_def(
        ToolDef(name="delete_file", description="Permanently delete a file. IRREVERSIBLE — cannot be undone. Prefer move_file to archive. Always confirm what you're deleting by reading or listing first.", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file to delete permanently."}}, "required": ["path"]}, risk_level="destructive"),
        delete_file,
    )
    agent.tools.register_from_def(
        ToolDef(name="create_directory", description="Create a directory and any needed parent directories. Safe to call on existing directories (no error).", parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Path to the directory to create."}}, "required": ["path"]}, risk_level="mutation"),
        create_directory,
    )
    agent.tools.register_from_def(
        ToolDef(name="move_file", description="Move or rename a file or directory. Overwrites the destination if it already exists. Safer alternative to delete_file for removing files.", parameters={"type": "object", "properties": {"source": {"type": "string", "description": "Current path of the file or directory."}, "destination": {"type": "string", "description": "New path for the file or directory."}}, "required": ["source", "destination"]}, risk_level="mutation"),
        move_file,
    )
    agent._prompt.append(FILES_PROMPT_SECTION)
