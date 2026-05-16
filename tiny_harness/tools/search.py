# tiny_harness/tools/search.py
import os
import re
import subprocess


def search_content(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    file_pattern = args.get("file_pattern")
    max_results = args.get("max_results", 100)

    try:
        cmd = ["rg", "--line-number", "--no-heading", "--color=never",
               "--max-count", str(max_results), "--no-ignore",
               "--glob", "!.git", "--glob", "!__pycache__", "--glob", "!*.pyc",
               pattern, path if os.path.isdir(path) else os.path.dirname(path) or "."]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=10, cwd=path,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (FileNotFoundError, Exception):
        lines = _fallback_grep(pattern, path, file_pattern, max_results)

    if file_pattern:
        lines = [ln for ln in lines if _match_file(ln, file_pattern)]

    lines = lines[:max_results]

    if not lines:
        return f"No matches for '{pattern}' in '{path}'."

    result = f"Found {len(lines)} matches for '{pattern}':\n"
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            result += f"  {parts[0]}:{parts[1]}: {parts[2][:100]}\n"
        else:
            result += f"  {line[:150]}\n"
    return result


def _fallback_grep(pattern: str, path: str, file_pattern: str | None, max_results: int = 100) -> list[str]:
    results = []
    try:
        compiled = re.compile(pattern)
    except re.error:
        return [f"Error: invalid regex pattern '{pattern}'"]

    if os.path.isfile(path):
        results = _grep_file(path, compiled, file_pattern, max_results)
        return results[:max_results]

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if len(results) >= max_results:
                return results
            if file_pattern and not _match_filename(f, file_pattern):
                continue
            fpath = os.path.join(root, f)
            results.extend(_grep_file(fpath, compiled, None, max_results - len(results)))
    return results[:max_results]


def _grep_file(fpath: str, compiled, file_pattern: str | None, max_results: int | None = None) -> list[str]:
    results = []
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                if compiled.search(line):
                    results.append(f"{fpath}:{i}:{line.rstrip()}")
                    if max_results and len(results) >= max_results:
                        return results
    except Exception:
        pass
    return results


def _match_file(line: str, pattern: str) -> bool:
    parts = line.split(":", 1)
    if not parts:
        return False
    return _match_filename(parts[0], pattern)


def _match_filename(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(os.path.basename(name), pattern)
