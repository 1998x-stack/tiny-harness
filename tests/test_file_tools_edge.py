# tests/test_file_tools_edge.py
"""Edge case and robustness tests for file operation tools."""
import os
import tempfile
import stat
import pytest
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file, _format_size,
)


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_write_file_special_chars_in_path(tmpdir):
    path = os.path.join(tmpdir, "test with spaces.txt")
    result = write_file({"path": path, "content": "hello"})
    assert "Created" in result
    assert os.path.exists(path)


def test_write_file_unicode_content(tmpdir):
    path = os.path.join(tmpdir, "unicode.txt")
    content = "Hello 世界 🌍"
    write_file({"path": path, "content": content})
    with open(path, "r", encoding="utf-8") as f:
        assert f.read() == content


def test_write_file_empty_content(tmpdir):
    path = os.path.join(tmpdir, "empty.txt")
    result = write_file({"path": path, "content": ""})
    assert "Created" in result
    # empty content = 1 empty line (content.count("\n") + 1 = 1)


def test_write_file_nested_path(tmpdir):
    path = os.path.join(tmpdir, "a", "b", "c", "file.txt")
    write_file({"path": path, "content": "deep"})
    assert os.path.exists(path)


def test_read_file_negative_offset_clamped(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    write_file({"path": path, "content": "line1\nline2\n"})
    result = read_file({"path": path, "offset": -5})
    assert "line1" in result


def test_read_file_limit_zero(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    write_file({"path": path, "content": "line1\nline2\n"})
    result = read_file({"path": path, "limit": 0})
    assert "limit must be positive" in result


def test_list_directory_recursive_with_hidden(tmpdir):
    hidden = os.path.join(tmpdir, ".hidden_dir")
    os.makedirs(hidden)
    write_file({"path": os.path.join(hidden, "f.txt"), "content": "x"})
    result = list_directory({"path": tmpdir, "recursive": True})
    assert ".hidden_dir" in result or "f.txt" in result


def test_find_files_recursive():
    result = find_files({"pattern": "**/*.py", "path": "tiny_harness"})
    assert ".py" in result.lower() or "No files" in result


def test_delete_readonly_file(tmpdir):
    path = os.path.join(tmpdir, "readonly.txt")
    write_file({"path": path, "content": "x"})
    os.chmod(path, stat.S_IREAD)
    result = delete_file({"path": path})
    assert "Deleted" in result or "Error" in result


def test_create_directory_path_with_trailing_slash(tmpdir):
    path = os.path.join(tmpdir, "newdir") + os.sep
    result = create_directory({"path": path})
    assert "Created" in result


def test_move_file_overwrite_existing(tmpdir):
    src = os.path.join(tmpdir, "src.txt")
    dst = os.path.join(tmpdir, "dst.txt")
    write_file({"path": src, "content": "new"})
    write_file({"path": dst, "content": "old"})
    move_file({"source": src, "destination": dst})
    with open(dst) as f:
        assert f.read() == "new"


def test_format_size_all_units():
    assert "B" in _format_size(500)
    assert "KB" in _format_size(5000)
    assert "MB" in _format_size(5_000_000)
    assert "GB" in _format_size(5_000_000_000)
