# Tool Definition Format

## 1. The Problem: How Does the LLM Know What Tools Can Do?

The LLM needs three pieces of information to use a tool correctly:

1. **Identity**: What is this tool called? (name)
2. **Purpose**: When and why should I use it? (description)
3. **Contract**: What arguments does it need, in what shape? (parameters schema)

These three fields form the **tool definition** — the interface between the LLM and the harness. The LLM reads this definition and decides: "Should I call this tool? If yes, with what arguments?"

---

## 2. The Standard Format

Modern LLMs (Anthropic Claude, OpenAI GPT-4+, Google Gemini) all converge on the same format:

```json
{
  "name": "read_file",
  "description": "Read the contents of a file from the local filesystem. Returns the file content as a UTF-8 string. Use this when you need to examine file contents or verify what was written.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to read. Must be accessible from the current working directory."
      },
      "offset": {
        "type": "integer",
        "description": "Line number to start reading from (1-indexed). Defaults to 1."
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

### 2.1 The Three Fields

**`name`** (required, string)
- Unique identifier within the tool registry
- Used by the LLM to specify which tool to invoke
- Convention: `snake_case`, verb-first (`read_file`, `search_code`, `run_command`)
- Must be valid as a programming identifier (no spaces, special chars)
- Once established, NEVER rename — it's baked into the LLM's behavior

**`description`** (required, string)
- Natural language explanation of what the tool does
- The LLM reads this to decide WHEN to use the tool
- Should describe: purpose, input/output, side effects, limitations
- Good descriptions are 2-5 sentences
- Write for an LLM reader: be specific about behavior, not vague

**`input_schema`** (required, JSON Schema object)
- Defines the shape of arguments the LLM must provide
- Must be `{"type": "object", "properties": {...}}`
- Each property has: type, description, optional enum, default
- The `required` array lists mandatory parameters

---

## 3. JSON Schema for Tools: The Essential Subset

JSON Schema is a large spec. For tool definitions, you only need a tiny subset:

### 3.1 Types

| Schema Type | What it means | Example |
|---|---|---|
| `"string"` | Text value | `"path": {"type": "string"}` |
| `"number"` | Floating point | `"temperature": {"type": "number"}` |
| `"integer"` | Whole number | `"count": {"type": "integer"}` |
| `"boolean"` | True/false | `"verbose": {"type": "boolean"}` |
| `"array"` | List of items | `"paths": {"type": "array", "items": {"type": "string"}}` |
| `"object"` | Nested structure | `"options": {"type": "object", "properties": {...}}` |

### 3.2 Constraints

| Feature | When to use |
|---|---|
| `required: ["x"]` | Parameter must be provided |
| `enum: ["a", "b"]` | Restrict to specific values |
| `default: value` | LLM can omit this parameter |
| `description` (per property) | Tell LLM what this parameter means |
| `minimum` / `maximum` | Numeric range bounds |

### 3.3 What to AVOID

- `$ref`, `$defs`, `allOf`, `anyOf`, `oneOf`: Most LLMs don't reliably handle schema composition
- `pattern` (regex): The LLM can't reliably generate strings matching arbitrary regex
- `additionalProperties: false`: Unnecessary; the LLM won't send extra fields unless confused
- `minLength`, `maxLength` on strings: The LLM doesn't count characters; it understands semantics
- Deep nesting (>2 levels): Keep schema flat. The LLM gets lost in deep structures.

### 3.4 The Golden Rule of Schema Design

**Schema complexity should match the LLM's ability to generate valid arguments.**

If the LLM consistently fails to generate valid arguments for a schema, the schema is too complex — not the LLM's fault. Simplify. Flatten nested objects into top-level parameters. Split complex tools into multiple simpler tools.

---

## 4. Writing Good Tool Descriptions

The description is the most underrated part of a tool definition. It's the only thing telling the LLM WHEN and WHY to use the tool.

### 4.1 Anatomy of a Good Description

```
"<what the tool does>. <input expectations>. <output format>. <when to use / not use>."
```

Examples:

```
Good:
"Search the codebase for text patterns using regular expressions.
 Returns matching file paths and line numbers.
 Use this for finding function definitions, variable usages, or error messages.
 For structural search (AST-aware), use search_code_structure instead."

Bad:
"Searches code."
```

### 4.2 Description Patterns

**Tool with side effects** — mention them explicitly:
```
"Write content to a file, overwriting if it already exists.
 WARNING: This is destructive for existing files. Use read_file first
 if you need to check current contents before overwriting."
```

**Tool with large output** — warn about context consumption:
```
"Return the git diff of all changes. WARNING: Output may be very large
 for extensive changes. Consider using git_diff_file for a specific file
 if you only need to see changes in one location."
```

**Tool with alternatives** — guide the LLM:
```
"Run a shell command. Use this for git operations, build commands,
 and package management. For file reading, use read_file instead.
 For code searching, use search_code instead."
```

### 4.3 What NOT to Put in Descriptions

- Marketing language ("powerful", "amazing", "best-in-class")
- Implementation details the LLM doesn't need ("uses os.open() with O_RDONLY")
- Future plans ("will support X in v2")
- Internal IDs or codes the LLM can't use
- Formatting instructions for human readers

---

## 5. Naming Conventions

### 5.1 Tool Names

```
Convention: verb_noun (snake_case)

Good:
  read_file          search_code         run_command
  write_file         list_directory      get_weather
  create_issue       delete_record       send_email

Bad:
  fileReader         get-file           READ
  file_reader_1      do_the_thing      tool_a
```

Rules:
1. Start with a verb (action-oriented)
2. Use `snake_case` (consistent, readable)
3. Be specific enough to distinguish: `read_file` vs `read_config` vs `read_env`
4. Avoid generic names: `execute`, `run`, `do` — too ambiguous
5. Never include version numbers or suffixes in names

### 5.2 Parameter Names

```
Convention: also snake_case, descriptive

Good:
  file_path           max_results      include_hidden
  search_pattern      timeout_ms       dry_run

Bad:
  fp                  max              hidden
  pattern1            t                flag
```

Rules:
1. Full words, not abbreviations (unless universally standard like `id`, `url`)
2. Consistent terminology across tools (always `path`, never `file_path` in one and `filepath` in another)
3. Boolean parameters: use `is_` or `has_` prefix sparingly; `dry_run` is better than `is_dry_run`

---

## 6. Schema Design Patterns

### 6.1 Optional Parameters with Sensible Defaults

```json
{
  "limit": {
    "type": "integer",
    "description": "Maximum number of results. Defaults to 50 if omitted.",
    "default": 50
  }
}
```

Let the LLM omit non-critical parameters. Every required parameter adds cognitive load.

### 6.2 Enum for Constrained Choices

```json
{
  "sort_order": {
    "type": "string",
    "enum": ["ascending", "descending"],
    "description": "Sort direction for results. Default: ascending."
  }
}
```

Enums are powerful — they constrain the LLM to valid values without requiring it to "guess" what's accepted.

### 6.3 Flat Over Nested

```json
// Good: flat parameters
{
  "host": { "type": "string" },
  "port": { "type": "integer" },
  "use_tls": { "type": "boolean" },
  "timeout_ms": { "type": "integer" }
}

// Bad: unnecessary nesting (LLM struggles)
{
  "connection": {
    "type": "object",
    "properties": {
      "host": { "type": "string" },
      "port": { "type": "integer" }
    }
  }
}
```

Flatten when possible. Only nest when the grouping has clear semantic meaning AND the LLM would naturally think of those parameters as a group.

### 6.4 Array of Simple Items

```json
{
  "file_paths": {
    "type": "array",
    "items": { "type": "string" },
    "description": "List of absolute file paths to read."
  }
}
```

Arrays of strings/numbers work well. Arrays of objects are harder for the LLM to generate correctly — avoid if possible.

---

## 7. Tool Definition Examples

### Simple Read-Only Tool

```json
{
  "name": "get_current_time",
  "description": "Get the current date and time in the specified timezone. Returns an ISO 8601 formatted timestamp.",
  "input_schema": {
    "type": "object",
    "properties": {
      "timezone": {
        "type": "string",
        "description": "IANA timezone name (e.g., 'America/New_York', 'Asia/Shanghai'). Defaults to 'UTC'.",
        "default": "UTC"
      }
    }
  }
}
```

### Destructive Tool (with warning)

```json
{
  "name": "delete_file",
  "description": "Permanently delete a file from the filesystem. WARNING: This operation cannot be undone. Use with caution. Consider using move_to_trash instead for recoverable deletion.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Absolute path to the file to delete. Must exist and be deletable."
      },
      "force": {
        "type": "boolean",
        "description": "If true, skip confirmation and delete immediately. Default: false.",
        "default": false
      }
    },
    "required": ["path"]
  }
}
```

### Tool with Complex Output

```json
{
  "name": "search_codebase",
  "description": "Search the entire codebase for a text pattern using regex. Returns matching file paths with line numbers and surrounding context. For large codebases, results may be truncated at 500 matches. Use more specific patterns to narrow results.",
  "input_schema": {
    "type": "object",
    "properties": {
      "pattern": {
        "type": "string",
        "description": "Regular expression pattern to search for. Example: 'function\s+\w+'. Supports full regex syntax."
      },
      "file_pattern": {
        "type": "string",
        "description": "Glob pattern to filter files. Example: '*.ts' for TypeScript files only. Omit to search all files."
      },
      "max_results": {
        "type": "integer",
        "description": "Maximum number of matches to return. Default: 100.",
        "default": 100
      }
    },
    "required": ["pattern"]
  }
}
```

---

## 8. MVP Decisions

For `tiny-harness`:

| Decision | Rationale |
|---|---|
| Use standard Anthropic/OpenAI format | Both use identical structure; no need for abstraction |
| JSON Schema subset only (types + required + enum + description) | LLMs handle this reliably; complex schema features cause failures |
| Flat parameters, no nesting | LLMs generate flat objects more reliably |
| `snake_case` names | Consistent, readable, standard in Python/JS tool ecosystems |
| English descriptions only | LLMs work best with English; i18n is premature |
| No `$ref`, `allOf`, `anyOf`, `oneOf` | Schema composition is unreliable with current LLMs |
| `description` on every parameter | Cheap to add, high value for LLM accuracy |
