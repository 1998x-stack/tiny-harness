# tiny_harness/_guard.py
import os


class PathAccessError(Exception):
    pass


class FilesystemGuard:
    def __init__(self, workspace: str):
        self._workspace = os.path.realpath(workspace)

    def resolve(self, path: str) -> str:
        if "\x00" in path:
            raise PathAccessError(f"Path contains null byte: {path!r}")
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self._workspace, expanded)
        try:
            return os.path.realpath(expanded)
        except OSError as e:
            raise PathAccessError(f"Cannot resolve path: {e}")

    def guard(self, path: str, operation: str = "read") -> str:
        resolved = self.resolve(path)
        if not (resolved == self._workspace or resolved.startswith(self._workspace + os.sep)):
            raise PathAccessError(
                f"Access denied: '{path}' (resolved: '{resolved}') "
                f"is outside allowed workspace."
            )
        return resolved
