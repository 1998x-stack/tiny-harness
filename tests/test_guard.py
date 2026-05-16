# tests/test_guard.py
import os
import pytest
import tempfile
from tiny_harness._guard import FilesystemGuard, PathAccessError


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = os.path.join(tmp, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")
        yield tmp


def test_guard_allows_file_inside_workspace(workspace):
    guard = FilesystemGuard(workspace)
    test_file = os.path.join(workspace, "test.txt")
    result = guard.guard(test_file, "read")
    assert os.path.realpath(result) == os.path.realpath(test_file)


def test_guard_rejects_file_outside_workspace(workspace):
    guard = FilesystemGuard(workspace)
    outside = "/tmp/outside_file.txt"
    with pytest.raises(PathAccessError, match="outside allowed"):
        guard.guard(outside, "read")


def test_guard_resolves_relative_paths(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    guard = FilesystemGuard(workspace)
    result = guard.guard("test.txt", "read")
    assert os.path.realpath(result) == os.path.realpath(os.path.join(workspace, "test.txt"))


def test_guard_resolves_dot_dot_traversal(workspace):
    guard = FilesystemGuard(workspace)
    path = os.path.join(workspace, "..", "..", "etc", "passwd")
    with pytest.raises(PathAccessError):
        guard.guard(path, "read")


def test_guard_rejects_null_byte(workspace):
    guard = FilesystemGuard(workspace)
    with pytest.raises(PathAccessError, match="null byte"):
        guard.resolve("test.txt\x00extra")
