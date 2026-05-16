# tiny_harness/skills/search.py
from tiny_harness.tools.search import search_content
from tiny_harness._tools import ToolDef

SEARCH_PROMPT = """
## Code Search

Search file contents across the codebase using regular expressions. Essential for understanding code, finding definitions, and discovering patterns.

### search_content(pattern, path?, file_pattern?, max_results?)

Search file contents with regex. Returns matching file paths, line numbers, and context.

**When to use:**
- Find function/class definitions: `def function_name`, `class ClassName`
- Find variable usages: `variable_name\\s*=`
- Find imports: `^import |^from `
- Find TODO/FIXME comments: `TODO|FIXME|HACK`
- Find error messages: `raise \\w+Error`
- Find configuration patterns: `API_KEY|DATABASE_URL`
- Trace code patterns: `@app.route|@router.get`

**When NOT to use (use other tools):**
- Finding files by name → use find_files (glob pattern)
- Reading a specific file → use read_file (full content)
- Listing a directory → use list_directory (file tree)
- Shell grep → use search_content (structured, with fallback)

### Pattern Tips

- **Literal text**: `search_content(pattern="def main")`
- **Word boundaries**: `search_content(pattern="\\\\bAgent\\\\b")` to match the class name exactly
- **Alternation**: `search_content(pattern="class (Agent|Loop|Config)")`
- **Anchors**: `search_content(pattern="^import os$")` for exact lines
- **File filtering**: `search_content(pattern="TODO", file_pattern="*.py")` for Python only

Use `file_pattern` to narrow results by file type (e.g., `"*.py"`, `"*.{ts,tsx}"`, `"*.md"`). Use `max_results` to limit output for broad searches.

### Workflow

1. **Broad search** — find all occurrences: `search_content(pattern="TODO", file_pattern="*.py")`
2. **Narrow down** — refine pattern or add file_pattern: `search_content(pattern="TODO.*urgent", file_pattern="src/**/*.py")`
3. **Read context** — for interesting matches, use read_file to see surrounding code
4. **Act** — make changes with write_file or run_command based on findings

### Error Handling

- "No matches" → Broaden the pattern, remove file_pattern, or check a different directory.
- "invalid regex" → Fix the pattern. Remember to escape special chars like `\\\\` for backslash.
- Results are truncated at max_results — narrow your search if you hit the limit.

### Common Patterns

```
# Find all Python class definitions
search_content(pattern="^class \\\\w+", file_pattern="*.py")

# Find TODO comments
search_content(pattern="TODO", file_pattern="*.py")

# Find test files referencing a function
search_content(pattern="def test_.*agent", file_pattern="test_*.py")

# Find all imports from a module
search_content(pattern="from tiny_harness", file_pattern="*.py")

# Find configuration values
search_content(pattern="API_KEY|SECRET|TOKEN", file_pattern="*.{py,env,yml,yaml}")
```
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(
            name="search_content",
            description="Search file contents across the codebase using regex. Returns matching file paths with line numbers and content preview. Uses ripgrep for speed (falls back to Python). Use file_pattern to filter by file type (e.g., '*.py') and max_results to limit output.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression pattern. Examples: 'def function_name', 'class \\\\w+Error', 'TODO|FIXME'."},
                    "path": {"type": "string", "description": "Directory or file to search. Default: current directory."},
                    "file_pattern": {"type": "string", "description": "Glob to filter files (e.g., '*.py', '*.{ts,tsx}', 'src/**/*.py')."},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return. Default: 100."},
                },
                "required": ["pattern"],
            },
            risk_level="read_only",
        ),
        search_content,
    )
    agent._prompt.append(SEARCH_PROMPT)
