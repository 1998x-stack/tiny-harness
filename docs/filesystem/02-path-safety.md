# File System: Path Safety and Sandboxing

## 1. The Threat Model

An AI agent with filesystem access is inherently dangerous. The LLM might:

1. **Accidentally** read sensitive files (`.env`, SSH keys, credentials)
2. **Hallucinate** paths and overwrite critical system files
3. **Follow symlinks** into restricted directories
4. **Use path traversal** (`../../../etc/passwd`) to escape the workspace
5. **Execute commands** via shell injection (if `run_command` is available)

The path safety system must ensure the agent **only operates within its designated workspace**, regardless of what the LLM asks for.

---

## 2. Defense Layers

Path safety is a **defense-in-depth** problem. No single check is sufficient:

```
Layer 1: Path Normalization   → Resolve ., .., ~, symlinks
Layer 2: Boundary Check       → Reject paths outside allowed roots
Layer 3: Symlink Guard        → Prevent symlink escape
Layer 4: Tool-Level Guard     → Per-operation safety checks
Layer 5: OS-Level Sandbox     → Container/process isolation (beyond MVP)
```

Each layer independently prevents a class of attacks. If one fails, the next catches it.

---

## 3. Layer 1: Path Normalization

### 3.1 The Problem with Raw Paths

```
User workspace: /home/user/project
LLM requests: read_file("../../../etc/passwd")
Raw path:      /home/user/project/../../../etc/passwd
Resolved:      /etc/passwd  ← ESCAPED! Outside workspace.
```

Path traversal (`..`) lets the LLM access any file the process can read.

### 3.2 Normalization

```python
def normalize_path(path: str, cwd: str) -> str:
    """Normalize a path to its canonical absolute form.

    Handles:
    - Relative paths         → absolute
    - Home directory (~)     → resolved
    - Path traversal (..)    → collapsed
    - Redundant separators   → cleaned
    - Trailing slashes       → removed
    """
    # Expand ~ to home directory
    expanded = os.path.expanduser(path)

    # Join with cwd if relative
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)

    # Resolve . and .. components
    normalized = os.path.normpath(expanded)

    return normalized
```

### 3.3 Real Path Resolution (Symlink-Aware)

`os.path.normpath` only handles `.` and `..`. It does NOT resolve symlinks. For that, use `os.path.realpath`:

```python
def resolve_path(path: str, cwd: str) -> str:
    """Fully resolve a path, including symlinks and .. traversal."""
    normalized = normalize_path(path, cwd)
    return os.path.realpath(normalized)
```

**Critical**: `os.path.realpath` resolves ALL symlinks in the path. This is essential for security — a symlink inside the workspace can point outside it.

---

## 4. Layer 2: Boundary Check

### 4.1 Allowlist-Based Access Control

Define a set of allowed directory roots. The agent can only access files within these roots.

```python
class PathGuard:
    def __init__(self, allowed_roots: list[str]):
        """allowed_roots: list of absolute directory paths the agent may access."""
        self.allowed_roots = [os.path.realpath(r) for r in allowed_roots]

    def is_allowed(self, path: str, operation: str = "read") -> bool:
        """Check if a path is within allowed boundaries."""
        try:
            resolved = os.path.realpath(path)
        except OSError:
            return False  # Can't resolve → deny

        for root in self.allowed_roots:
            # Check: resolved path starts with root
            # OR resolved path IS root
            if resolved == root or resolved.startswith(root + os.sep):
                return True

        return False

    def guard(self, path: str, operation: str = "read") -> str:
        """Resolve and validate a path. Returns resolved path or raises."""
        resolved = os.path.realpath(path)

        if not self.is_allowed(resolved, operation):
            raise PathAccessError(
                f"Access denied: '{path}' is outside allowed paths.\n"
                f"  Resolved to: {resolved}\n"
                f"  Allowed roots: {', '.join(self.allowed_roots)}"
            )

        return resolved
```

### 4.2 Usage in Tool Handlers

```python
guard = PathGuard(allowed_roots=["/home/user/project", "/tmp/agent"])

async def read_file(path: str, offset: int = 1, limit: int = None) -> str:
    try:
        safe_path = guard.guard(path, operation="read")
    except PathAccessError as e:
        return f"Error: {e}"

    # Now safe_path is guaranteed to be within allowed roots
    with open(safe_path, "r") as f:
        ...
```

---

## 5. Layer 3: Symlink Guard

### 5.1 The Symlink Escape Attack

```
Workspace: /home/user/project
Inside workspace: /home/user/project/data → /etc (symlink)

LLM calls: read_file("data/passwd")
Path:        /home/user/project/data/passwd
realpath:    /etc/passwd  ← ESCAPED via symlink!
```

Even with boundary checking, symlinks can bypass the guard if we check BEFORE symlink resolution.

### 5.2 Defense: Resolve Before Check

Always resolve the full realpath BEFORE checking boundaries:

```python
# CORRECT: Resolve first, then check
safe_path = os.path.realpath(user_path)   # Resolves ALL symlinks
if not is_within_boundary(safe_path):     # Now check
    raise AccessDenied()

# WRONG: Check first, then resolve
if not is_within_boundary(user_path):     # Symlink not resolved yet!
    raise AccessDenied()
safe_path = os.path.realpath(user_path)   # Oops, could be outside
```

### 5.3 Write Operation Symlink Guard

For write operations, also check that the target isn't a symlink:

```python
def guard_write(path: str) -> str:
    """Guard for write operations — extra symlink check."""
    resolved = os.path.realpath(path)

    if not is_allowed(resolved):
        raise PathAccessError(f"Write denied: '{path}' is outside allowed paths")

    # For writes, also check that no component is a symlink
    # (prevents writing through a symlink that was created after startup)
    components = path.split(os.sep)
    check_path = "/" if path.startswith("/") else "."
    for component in components:
        if not component:
            continue
        check_path = os.path.join(check_path, component)
        if os.path.islink(check_path):
            raise PathAccessError(
                f"Write denied: '{path}' contains a symlink component '{check_path}'"
            )

    return resolved
```

---

## 6. Layer 4: Tool-Level Guards

### 6.1 Read Operations

Reads are generally lower risk than writes:

```python
def guard_read(path: str) -> str:
    """Guard for read operations."""
    resolved = os.path.realpath(path)

    if not is_allowed(resolved):
        raise PathAccessError(f"Read denied: outside workspace")

    # Optionally: block reading of known sensitive files
    basename = os.path.basename(resolved)
    if basename in SENSITIVE_FILES:
        raise PathAccessError(f"Read denied: '{basename}' is a sensitive file")

    return resolved

SENSITIVE_FILES = {".env", ".env.local", ".env.production",
                   "credentials.json", "id_rsa", "id_ed25519",
                   ".git-credentials", ".npmrc", ".pypirc"}
```

### 6.2 Write Operations

Writes are higher risk — they can destroy data:

```python
def guard_write(path: str) -> str:
    """Guard for write operations — stricter checks."""
    resolved = guard_read(path)  # Base checks

    # Block writes to version control internals
    if ".git/" in resolved:
        raise PathAccessError("Write denied: cannot modify .git directory")

    # Block writes to project config files (unless explicitly allowed)
    basename = os.path.basename(resolved)
    if basename in PROTECTED_FILES:
        raise PathAccessError(f"Write denied: '{basename}' is protected")

    return resolved

PROTECTED_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                   "Cargo.lock", "Gemfile.lock", "poetry.lock"}
```

### 6.3 Delete Operations

Deletes are the highest risk — irreversible:

```python
def guard_delete(path: str) -> str:
    """Guard for delete operations — strictest checks."""
    resolved = guard_write(path)  # All write checks apply

    # Additional: require explicit confirmation for certain paths
    # (MVP: just log a warning; production: ask user)
    if resolved.endswith((".py", ".js", ".ts", ".rs", ".go")):
        print(f"WARNING: Deleting source file: {resolved}")

    return resolved
```

---

## 7. Complete Path Safety Implementation

```python
class FilesystemGuard:
    def __init__(self, allowed_roots: list[str],
                 sensitive_files: set[str] | None = None,
                 protected_files: set[str] | None = None):
        self.allowed_roots = [os.path.realpath(r) for r in allowed_roots]
        self.sensitive_files = sensitive_files or SENSITIVE_FILES
        self.protected_files = protected_files or PROTECTED_FILES

    def resolve(self, path: str, cwd: str | None = None) -> str:
        """Resolve path to canonical form. Raises on invalid/bad paths."""
        cwd = cwd or os.getcwd()

        # Block null bytes (path injection)
        if "\x00" in path:
            raise PathAccessError("Path contains null byte")

        # Expand and normalize
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(cwd, expanded)

        # Resolve symlinks + collapse ..
        try:
            resolved = os.path.realpath(expanded)
        except OSError as e:
            raise PathAccessError(f"Cannot resolve path: {e}")

        return resolved

    def guard(self, path: str, operation: str = "read",
              cwd: str | None = None) -> str:
        """Full guard: resolve → boundary check → operation check.
        Returns the safe, resolved path."""
        resolved = self.resolve(path, cwd)

        # Boundary check
        if not self._is_within_bounds(resolved):
            raise PathAccessError(
                f"Access denied: '{path}' (resolved: '{resolved}') "
                f"is outside allowed workspace boundaries."
            )

        # Operation-specific checks
        if operation in ("write", "delete"):
            basename = os.path.basename(resolved)
            if basename in self.sensitive_files:
                raise PathAccessError(
                    f"Access denied: '{basename}' is a sensitive file."
                )
            if operation == "delete" and basename in self.protected_files:
                raise PathAccessError(
                    f"Delete denied: '{basename}' is a protected file."
                )

        return resolved

    def _is_within_bounds(self, resolved: str) -> bool:
        for root in self.allowed_roots:
            if resolved == root or resolved.startswith(root + os.sep):
                return True
        return False
```

---

## 8. Integration with Tool Handlers

Every file tool wraps its path argument through the guard:

```python
class SafeFileTools:
    def __init__(self, guard: FilesystemGuard):
        self.guard = guard

    async def read_file(self, path: str, offset: int = 1,
                        limit: int = None) -> str:
        try:
            safe_path = self.guard.guard(path, "read")
        except PathAccessError as e:
            return f"Error: {e}"
        return _read_file_impl(safe_path, offset, limit)

    async def write_file(self, path: str, content: str) -> str:
        try:
            safe_path = self.guard.guard(path, "write")
        except PathAccessError as e:
            return f"Error: {e}"
        return _write_file_impl(safe_path, content)

    async def delete_file(self, path: str) -> str:
        try:
            safe_path = self.guard.guard(path, "delete")
        except PathAccessError as e:
            return f"Error: {e}"
        return _delete_file_impl(safe_path)
```

---

## 9. OS-Level Sandbox (Beyond MVP)

For production, add OS-level isolation:

### 9.1 chroot / container

Run the agent in a chroot or Docker container with only the workspace mounted:

```bash
docker run --rm \
  -v "$(pwd):/workspace:rw" \
  -v /tmp/agent-cache:/tmp:rw \
  --network none \
  --memory 2g \
  --read-only=false \
  tiny-harness run "Do X in /workspace"
```

### 9.2 seccomp / Landlock (Linux)

Use Linux security modules to restrict filesystem access at the kernel level.

---

## 10. MVP Decisions

| Decision | Rationale |
|---|---|
| **PathGuard as a class** | Single point of enforcement; every file tool wraps through it |
| **`os.path.realpath` for all paths** | Resolves symlinks; essential for boundary checking |
| **Allowlist of roots (not denylist)** | Default-deny is safer than default-allow |
| **Operation-specific guards** | Read/write/delete have different risk profiles |
| **Sensitive file blocking** | Prevents accidental .env reads |
| **Error messages explain WHY access was denied** | LLM can learn from the message and try different paths |
| **No OS-level sandbox (MVP)** | Overkill for local development; add for production/deployment |
| **Null byte rejection** | Prevents path injection attacks |
