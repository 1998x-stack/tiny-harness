# File System Tools: Design

## 1. First Principles: What Does an Agent Need from the Filesystem?

From the agent's perspective, the filesystem is a **hierarchical key-value store**. The agent needs to:

1. **Read** values (file contents, directory listings)
2. **Write** values (create/overwrite files)
3. **Discover** keys (list directories, search by pattern)
4. **Organize** keys (create directories, move/rename files)
5. **Remove** keys (delete files and directories)

Everything the agent does with files maps to one of these five operations. The tool design should mirror this.

---

## 2. The Core File Tools

### 2.1 `read_file` — Read File Contents

```python
{
    "name": "read_file",
    "description": "Read the contents of a file. Returns the file content as text. "
                   "For binary files, returns a description of the file type and size. "
                   "Use offset and limit to read specific sections of large files.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative path to the file."
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Default: 1.",
                "default": 1
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Omit to read the entire file."
            }
        },
        "required": ["path"]
    }
}
```

**Handler pseudocode**:
```python
async def read_file(path: str, offset: int = 1, limit: int | None = None) -> str:
    full_path = resolve_path(path)

    if not os.path.exists(full_path):
        return f"Error: File '{full_path}' not found."

    if os.path.isdir(full_path):
        return f"Error: '{full_path}' is a directory. Use list_directory instead."

    # Handle binary files
    if is_binary(full_path):
        size = os.path.getsize(full_path)
        return f"Binary file: {os.path.basename(full_path)} ({format_size(size)})"

    with open(full_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    selected = lines[offset-1 : (offset-1 + limit) if limit else None]

    result = "".join(selected)

    # Context info
    header = f"[{full_path}] Lines {offset}-{offset + len(selected) - 1} of {total_lines}\n"
    return header + truncate(result, max_chars=50_000)
```

### 2.2 `write_file` — Create or Overwrite a File

```python
{
    "name": "write_file",
    "description": "Write content to a file. Creates the file if it doesn't exist, "
                   "overwrites it if it does. Creates parent directories automatically. "
                   "WARNING: This overwrites existing files without confirmation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file. Parent directories will be created if needed."
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file."
            }
        },
        "required": ["path", "content"]
    }
}
```

**Handler pseudocode**:
```python
async def write_file(path: str, content: str) -> str:
    full_path = resolve_path(path)

    # Create parent directories
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    existed = os.path.exists(full_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

    size = len(content.encode("utf-8"))
    action = "Updated" if existed else "Created"
    lines = content.count("\n") + 1

    return f"{action} '{full_path}' ({lines} lines, {format_size(size)})"
```

### 2.3 `list_directory` — List Directory Contents

```python
{
    "name": "list_directory",
    "description": "List files and subdirectories in a directory. "
                   "Returns names, types (file/dir), and sizes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the directory. Defaults to current working directory.",
                "default": "."
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern to filter results (e.g., '*.py'). Omit to show all."
            },
            "recursive": {
                "type": "boolean",
                "description": "If true, list recursively. Default: false.",
                "default": False
            }
        },
        "required": []
    }
}
```

**Handler pseudocode**:
```python
async def list_directory(path: str = ".", pattern: str = None,
                          recursive: bool = False) -> str:
    full_path = resolve_path(path)

    if not os.path.isdir(full_path):
        return f"Error: '{full_path}' is not a directory."

    entries = []
    if recursive:
        for root, dirs, files in os.walk(full_path):
            for name in dirs + files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, full_path)
                if not pattern or fnmatch(rel, pattern):
                    entries.append(format_entry(full, rel))
    else:
        for name in sorted(os.listdir(full_path)):
            full = os.path.join(full_path, name)
            if not pattern or fnmatch(name, pattern):
                entries.append(format_entry(full, name))

    if not entries:
        return f"Directory '{full_path}' is empty."

    header = f"[{full_path}] {len(entries)} items:\n"
    return header + "\n".join(entries)


def format_entry(full_path: str, name: str) -> str:
    is_dir = os.path.isdir(full_path)
    prefix = "📁" if is_dir else "📄"
    size = "" if is_dir else format_size(os.path.getsize(full_path))
    return f"  {prefix} {name}{('  ' + size) if size else ''}"
```

### 2.4 `search_files` — Find Files by Pattern

```python
{
    "name": "search_files",
    "description": "Find files matching a glob pattern. Returns relative file paths. "
                   "Use this to discover files in the project structure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g., '**/*.py', 'src/**/*.ts')."
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Default: current directory.",
                "default": "."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum files to return. Default: 200.",
                "default": 200
            }
        },
        "required": ["pattern"]
    }
}
```

### 2.5 `delete_file` — Delete a File

```python
{
    "name": "delete_file",
    "description": "Permanently delete a file. WARNING: This cannot be undone. "
                   "Consider moving to a backup location instead.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to delete."
            }
        },
        "required": ["path"]
    }
}
```

### 2.6 `create_directory` — Create a Directory

```python
{
    "name": "create_directory",
    "description": "Create a directory (and any parent directories as needed). "
                   "Does nothing if the directory already exists.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the directory to create."
            }
        },
        "required": ["path"]
    }
}
```

### 2.7 `move_file` — Move or Rename

```python
{
    "name": "move_file",
    "description": "Move or rename a file or directory. "
                   "Overwrites destination if it exists.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Current path of the file/directory."
            },
            "destination": {
                "type": "string",
                "description": "New path for the file/directory."
            }
        },
        "required": ["source", "destination"]
    }
}
```

---

## 3. Shared Utilities

### 3.1 Path Resolution

Every file tool resolves paths the same way:

```python
def resolve_path(path: str, cwd: str | None = None) -> str:
    """Resolve a path to an absolute path, relative to the working directory."""
    cwd = cwd or os.getcwd()

    if os.path.isabs(path):
        return os.path.normpath(path)

    return os.path.normpath(os.path.join(cwd, path))
```

### 3.2 Output Truncation

Large outputs consume context. Truncate with clear indicators:

```python
def truncate(text: str, max_chars: int = 50_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + (
        f"\n\n[... Output truncated at {max_chars:,} characters. "
        f"Original: {len(text):,} characters. "
        f"Use offset/limit to read specific sections.]"
    )
```

### 3.3 Size Formatting

```python
def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
```

### 3.4 Binary Detection

```python
def is_binary(file_path: str) -> bool:
    """Detect if a file is binary by reading the first few bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
        # Check for null bytes (strong binary indicator)
        if b"\x00" in chunk:
            return True
        # Try decoding as UTF-8
        chunk.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True
```

---

## 4. Tool Registration (Complete Set)

```python
def register_file_tools(registry: ToolRegistry, workspace: str) -> None:
    """Register all file system tools in the registry."""

    cwd = workspace  # Capture workspace for path resolution

    registry.register(Tool(
        definition=ToolDef(
            name="read_file",
            description="Read the contents of a file...",
            parameters={...},
            risk_level="read_only"
        ),
        handler=lambda path, offset=1, limit=None: read_file(
            resolve_path(path, cwd), offset, limit
        )
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="write_file",
            description="Write content to a file...",
            parameters={...},
            risk_level="mutation"
        ),
        handler=lambda path, content: write_file(resolve_path(path, cwd), content)
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="list_directory",
            description="List files and subdirectories...",
            parameters={...},
            risk_level="read_only"
        ),
        handler=lambda path=".", pattern=None, recursive=False: list_directory(
            resolve_path(path, cwd), pattern, recursive
        )
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="search_files",
            description="Find files matching a glob pattern...",
            parameters={...},
            risk_level="read_only"
        ),
        handler=lambda pattern, path=".", max_results=200: search_files(
            pattern, resolve_path(path, cwd), max_results
        )
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="delete_file",
            description="Permanently delete a file...",
            parameters={...},
            risk_level="destructive"
        ),
        handler=lambda path: delete_file(resolve_path(path, cwd))
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="create_directory",
            description="Create a directory...",
            parameters={...},
            risk_level="mutation"
        ),
        handler=lambda path: create_directory(resolve_path(path, cwd))
    ))

    registry.register(Tool(
        definition=ToolDef(
            name="move_file",
            description="Move or rename a file...",
            parameters={...},
            risk_level="mutation"
        ),
        handler=lambda source, destination: move_file(
            resolve_path(source, cwd),
            resolve_path(destination, cwd)
        )
    ))
```

---

## 5. Design Decisions

### 5.1 Why Separate `list_directory` and `search_files`?

`list_directory` shows **what's in one directory** (flat or recursive tree). `search_files` finds files by **glob pattern** across the tree. They serve different LLM mental models:

- "What's in this directory?" → `list_directory`
- "Where are all the Python files?" → `search_files`

Combining them into one tool with flags would confuse the LLM about which flag combination to use.

### 5.2 Why `offset`/`limit` Instead of `start_line`/`end_line`?

The offset/limit pattern is familiar from pagination APIs. The LLM understands it immediately. Start/end line is more ambiguous (is end inclusive?).

### 5.3 Why Auto-Create Parent Directories in `write_file`?

Without this, writing `src/utils/helpers.py` requires two tool calls (create directories, then write file). Auto-creating parents makes single-file creation a one-call operation. The LLM doesn't need to think about directory structure for simple writes.

---

## 6. MVP Decisions

| Decision | Rationale |
|---|---|
| 7 core tools (read, write, list, search, delete, mkdir, move) | Covers all essential filesystem operations |
| Paths resolved relative to workspace root | Simple, predictable, sandboxable |
| UTF-8 text only for read/write | Binary files are a separate concern; MVP handles text |
| Auto-create parent dirs on write | One-call file creation; reduces LLM iteration count |
| Output truncated at 50K chars | Prevents context bombs from large files |
| Binary files return description, not content | LLM can't process binary content anyway |
| No file watching or live reload | Premature for MVP |
| No backup/undo for writes | Simplifies implementation; add when needed |
