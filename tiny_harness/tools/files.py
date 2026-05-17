# tiny_harness/tools/files.py
import os
import glob
import shutil


def read_file(args: dict) -> str:
    path = args["path"]
    offset = max(1, args.get("offset", 1))
    limit = args.get("limit")
    if limit is not None and limit <= 0:
        return f"Error: limit must be positive, got {limit}."
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."
    if os.path.isdir(path):
        return f"Error: '{path}' is a directory."
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    if total == 0:
        return f"[{path}] Lines 0-0 of 0 (empty)\n"
    if offset > total:
        return f"Error: offset {offset} exceeds file length {total}."
    selected = lines[offset - 1 : (offset - 1 + limit) if limit else None]
    result = "".join(selected)
    end = offset + len(selected) - 1
    header = f"[{path}] Lines {offset}-{end} of {total}\n"
    output = header + result
    if len(output) > 50000:
        output = output[:50000] + "\n\n[... truncated at 50,000 characters]"
    return output


def write_file(args: dict) -> str:
    path = args["path"]
    content = args["content"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    size = len(content.encode("utf-8"))
    action = "Updated" if existed else "Created"
    lines = content.count("\n") + 1
    return f"{action} '{path}' ({lines} lines, {_format_size(size)})"


def list_directory(args: dict) -> str:
    path = args.get("path", ".")
    pattern = args.get("pattern")
    recursive = args.get("recursive", False)
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory."
    entries = []
    if recursive:
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full = os.path.join(root, name)
                if not pattern or _glob_match(name, pattern):
                    entries.append(_format_entry(full, os.path.relpath(full, path)))
    else:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if not pattern or _glob_match(name, pattern):
                entries.append(_format_entry(full, name))
    if not entries:
        return f"Directory '{path}' is empty."
    return f"[{path}] {len(entries)} items:\n" + "\n".join(entries)


def find_files(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    max_results = args.get("max_results", 200)
    matches = []

    import os as _os
    base = _os.path.realpath(path)
    search_path = _os.path.join(base, pattern)
    if _os.path.isabs(pattern) or ".." in pattern.split(_os.sep):
        resolved = _os.path.realpath(search_path) if _os.path.exists(search_path) else _os.path.realpath(base)
        if not resolved.startswith(base + _os.sep) and resolved != base:
            return f"Error: pattern '{pattern}' escapes workspace."

    for i, match in enumerate(glob.glob(search_path, recursive=True)):
        if i >= max_results:
            break
        matches.append(os.path.relpath(match, path))
    if not matches:
        return f"No files matching '{pattern}' found in '{path}'."
    return f"Found {len(matches)} files matching '{pattern}':\n" + "\n".join(f"  {m}" for m in matches)


def delete_file(args: dict) -> str:
    path = args["path"]
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."
    if os.path.isdir(path):
        return f"Error: '{path}' is a directory. Use a directory removal tool instead."
    os.remove(path)
    return f"Deleted '{path}'."


def create_directory(args: dict) -> str:
    path = args["path"]
    existed = os.path.isdir(path)
    os.makedirs(path, exist_ok=True)
    action = "Already exists" if existed else "Created"
    return f"{action} directory '{path}'."


def move_file(args: dict) -> str:
    src = args["source"]
    dst = args["destination"]
    if not os.path.exists(src):
        return f"Error: Source '{src}' not found."
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.move(src, dst)
    return f"Moved '{src}' -> '{dst}'."


def _format_entry(full_path: str, name: str) -> str:
    is_dir = os.path.isdir(full_path)
    prefix = "D" if is_dir else "F"
    size = "" if is_dir else _format_size(os.path.getsize(full_path))
    return f"  [{prefix}] {name}{'  ' + size if size else ''}"


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}" if unit != "B" else f"{size_bytes}B"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def _glob_match(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern)
