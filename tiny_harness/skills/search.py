# tiny_harness/skills/search.py
from tiny_harness.tools.search import search_content
from tiny_harness._tools import ToolDef

SEARCH_PROMPT = """
## Code Search

Use search_content(pattern, path?, file_pattern?, max_results?) to search code.
- Uses ripgrep (rg) for speed, falls back to Python regex.
- file_pattern filters by filename glob (e.g., '*.py', '*.{ts,tsx}').
- Use for finding function definitions, variable usages, error messages, TODO comments.
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(
            name="search_content",
            description="Search file contents using regex. Returns matching file paths with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for."},
                    "path": {"type": "string", "description": "Directory to search. Default: current."},
                    "file_pattern": {"type": "string", "description": "Glob to filter files (e.g. '*.py')."},
                    "max_results": {"type": "integer", "description": "Max results. Default: 100."},
                },
                "required": ["pattern"],
            },
            risk_level="read_only",
        ),
        search_content,
    )
    agent._prompt.append(SEARCH_PROMPT)
