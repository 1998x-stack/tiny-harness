# Skills System

## 1. What Is a Skill?

A Skill is a packaged bundle that extends the Agent with:
1. **Tools** — one or more tool functions registered into the ToolRegistry
2. **Prompt augmentations** — instructions added to the Agent's Prompt telling it how and when to use the tools
3. **Conventions** — usage patterns, expected workflows, constraints

A Skill represents a domain capability: "git operations," "code review," "file management." The Agent acquires capabilities by loading Skills.

```
Agent (core)                      Agent + Skill("git")
┌─────────────────┐              ┌─────────────────────────┐
│ Loop            │              │ Loop                    │
│ MessageManager  │    load      │ MessageManager          │
│ Config          │ ──────────▶  │ Config                  │
│ LLMProvider     │   skill      │ LLMProvider             │
│ ToolRegistry [] │              │ ToolRegistry [git_log,  │
│ Prompt "..."    │              │   git_diff, git_commit] │
└─────────────────┘              │ Prompt "... + git rules"│
                                 └─────────────────────────┘
```

## 2. Skill Structure

### 2.1 Minimal Skill

A Skill is a Python module (or package) with at minimum a `register(agent)` function:

```python
# skills/git.py
from tiny_harness import Agent

def register(agent: Agent):
    """Register git tools and prompt instructions."""
    agent.tools.register(git_log)
    agent.tools.register(git_diff)
    agent.tools.register(git_commit)

    agent.prompt.append("""
## Git Operations
You have git tools available. Use them for version control:
- git_log: View commit history
- git_diff: See uncommitted changes
- git_commit: Create commits with messages

Rules for git:
1. Never commit without a meaningful message
2. Never force push to main/master
3. Create branches for new features
4. Run git_diff before committing to review changes
""")


# Tool handlers
async def git_log(args: dict) -> str:
    """Return formatted git log."""
    ...

async def git_diff(args: dict) -> str:
    """Return git diff output."""
    ...

async def git_commit(args: dict) -> str:
    """Create a git commit."""
    ...
```

### 2.2 Full Skill (Package)

```python
# skills/code_review/__init__.py
from .tools import review_file, review_diff, suggest_fix
from .prompt import PROMPT_EXTENSION

def register(agent):
    agent.tools.register(review_file)
    agent.tools.register(review_diff)
    agent.tools.register(suggest_fix)
    agent.prompt.append(PROMPT_EXTENSION)
```

## 3. Skill Loading Mechanism

### 3.1 Loading API

```python
# By name (from installed packages)
agent.load_skill("git")

# By module path
agent.load_skill("my_project.skills.custom_reviewer")

# By file path
agent.load_skill("/path/to/my_skill.py")

# From a package entry point (future)
agent.load_skill("git")  # Resolves to tiny_harness_skill_git
```

### 3.2 Loading Implementation

```python
class Agent:
    def load_skill(self, skill_ref: str):
        """Load a skill by name, path, or module reference."""
        module = self._resolve_skill(skill_ref)

        if not hasattr(module, "register"):
            raise SkillError(f"Skill '{skill_ref}' has no register() function")

        # Call the skill's register function
        module.register(self)

        # Track loaded skills
        self._loaded_skills.append(skill_ref)

    def _resolve_skill(self, ref: str) -> ModuleType:
        """Resolve a skill reference to a Python module."""
        # 1. Try installed package: tiny_harness_skill_<name>
        try:
            return importlib.import_module(f"tiny_harness_skill_{ref}")
        except ImportError:
            pass

        # 2. Try direct module import
        try:
            return importlib.import_module(ref)
        except ImportError:
            pass

        # 3. Try file path
        path = Path(ref)
        if path.exists():
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        raise SkillError(f"Skill '{ref}' not found")
```

### 3.3 Loading Order

Skills are loaded in this order, and each skill appends to the Prompt:

```
1. Agent created with base Prompt
2. Skill "files" loaded  → Prompt += file tool instructions
3. Skill "git" loaded    → Prompt += git tool instructions
4. Skill "code-review"   → Prompt += code review instructions
─────────────────────────────────────────────────
Final Prompt = base + files + git + code-review
```

## 4. Prompt Augmentation

### 4.1 Prompt API

The Prompt supports appending:

```python
class Prompt:
    def __init__(self, base: str):
        self.sections: list[str] = [base]

    def append(self, section: str):
        """Append a section (from a skill) to the prompt."""
        self.sections.append(section)

    def to_string(self) -> str:
        return "\n\n".join(self.sections)


# Usage in skill
def register(agent: Agent):
    agent.prompt.append("""
## Git Tools
You have git tools available...
""")
```

### 4.2 Prompt Section Conventions

Each skill's prompt section follows this structure:

```markdown
## {Skill Name}

{tools description — when and why to use each tool}

{usage guidelines — rules, constraints, patterns}

{output / error conventions — how to format results, handle failures}
```

Example:
```markdown
## File Operations

You have access to the filesystem through these tools:
- read_file: Read file contents. Use for examining files, verifying writes.
- write_file: Create or overwrite a file. Use for creating new files or modifying existing ones.
- list_directory: List directory contents. Use to discover project structure.
- search_files: Find files by glob pattern. Use to locate files by name or extension.
- delete_file: Permanently delete a file. WARNING: irreversible.

Guidelines:
1. Always verify writes by reading the file back
2. Use specific paths — never guess file locations
3. For large files, use offset/limit to read sections
4. Never delete files without user confirmation
```

## 5. Skill Discovery

### 5.1 Built-in Skills

Shipped with `tiny-harness`:
```
tiny_harness/skills/
  files.py        # File system operations
  shell.py        # Shell command execution
  search.py       # Code search (grep, ast-grep)
```

These are bundled with the package but NOT auto-loaded. The user chooses which to load.

### 5.2 Third-Party Skills

Installed as separate packages:
```bash
pip install tiny-harness-skill-git
pip install tiny-harness-skill-docker
pip install tiny-harness-skill-postgres
```

Package name convention: `tiny-harness-skill-{name}`

Each package exposes a `register(agent)` function at its top level.

### 5.3 Listing Available Skills

```bash
tiny-harness skills
# Installed skills:
#   files         File system operations (built-in)
#   shell         Shell command execution (built-in)
#   search        Code search tools (built-in)
#   git           Git version control (tiny-harness-skill-git v1.0.0)
```

## 6. Skill Metadata

A skill can optionally expose metadata:

```python
# skills/git.py

SKILL_META = {
    "name": "git",
    "version": "1.0.0",
    "description": "Git version control operations",
    "author": "tiny-harness",
    "requires": [],            # Other skills this depends on
    "conflicts": [],           # Skills this is incompatible with
    "tools_provided": [        # Tool names registered by this skill
        "git_log",
        "git_diff",
        "git_commit",
        "git_branch",
    ],
    "risk_level": "mutation",  # Overall risk level of this skill's tools
}

def register(agent):
    ...
```

The Agent reads this metadata for discovery and conflict detection.

## 7. Skill Conflicts and Dependencies

```python
class Agent:
    def load_skill(self, skill_ref: str):
        module = self._resolve_skill(skill_ref)
        meta = getattr(module, "SKILL_META", {})

        # Check dependencies
        for dep in meta.get("requires", []):
            if dep not in self._loaded_skills:
                raise SkillError(
                    f"Skill '{skill_ref}' requires '{dep}' — load it first"
                )

        # Check conflicts
        for conflict in meta.get("conflicts", []):
            if conflict in self._loaded_skills:
                raise SkillError(
                    f"Skill '{skill_ref}' conflicts with '{conflict}'"
                )

        # Check tool name collisions
        new_tools = set(meta.get("tools_provided", []))
        existing = set(self.tools.names())
        overlap = new_tools & existing
        if overlap:
            raise SkillError(
                f"Skill '{skill_ref}' provides tools that already exist: {overlap}"
            )

        module.register(self)
        self._loaded_skills.append(skill_ref)
```

## 8. Design Decisions

| Decision | Rationale |
|---|---|
| `register(agent)` as the sole interface | Simple, explicit, no magic. The skill explicitly adds tools and prompt. |
| Prompt as append-only sections | Predictable ordering; each skill's instructions are a distinct section. |
| Package naming convention | Enables discovery without a central registry. |
| No auto-loading of built-in skills | User controls capabilities; zero-tool default is safer. |
| Tool name collision detection | Prevents silent overwrites when two skills provide the same tool name. |
| Skill metadata optional | Minimal skills just need `register()`. Metadata enables tooling. |
| No skill unloading (MVP) | Simplifies implementation; restart the session to change skills. |

## 9. MVP Scope

| Feature | MVP | Future |
|---|---|---|
| `register(agent)` interface | ✓ | |
| Prompt append sections | ✓ | |
| Built-in skills (files, shell, search) | ✓ | |
| Third-party skill loading (`tiny-harness-skill-*`) | | ✓ |
| Skill metadata | ✓ (optional) | |
| Skill dependencies/conflicts | ✓ | |
| Skill unloading | | ✓ |
| MCP server as a skill source | | ✓ |
| Skill marketplace | | ✓ |
