# tests/test_file_tools.py
import os
import tempfile
import pytest
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file,
)


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_write_and_read_file(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    result = write_file({"path": path, "content": "hello world"})
    assert "Created" in result or "Updated" in result
    content = read_file({"path": path})
    assert "hello world" in content


def test_list_directory(tmpdir):
    write_file({"path": os.path.join(tmpdir, "a.txt"), "content": "a"})
    write_file({"path": os.path.join(tmpdir, "b.txt"), "content": "b"})
    result = list_directory({"path": tmpdir})
    assert "a.txt" in result
    assert "b.txt" in result


def test_find_files(tmpdir):
    write_file({"path": os.path.join(tmpdir, "hello.py"), "content": "print('hi')"})
    write_file({"path": os.path.join(tmpdir, "readme.md"), "content": "# hi"})
    result = find_files({"pattern": "*.py", "path": tmpdir})
    assert "hello.py" in result


def test_delete_file(tmpdir):
    path = os.path.join(tmpdir, "to_delete.txt")
    write_file({"path": path, "content": "delete me"})
    result = delete_file({"path": path})
    assert "Deleted" in result or "deleted" in result.lower()
    assert not os.path.exists(path)


def test_create_directory(tmpdir):
    new_dir = os.path.join(tmpdir, "new_dir", "sub")
    result = create_directory({"path": new_dir})
    assert "Created" in result
    assert os.path.isdir(new_dir)


def test_move_file(tmpdir):
    src = os.path.join(tmpdir, "src.txt")
    dst = os.path.join(tmpdir, "dst.txt")
    write_file({"path": src, "content": "move me"})
    result = move_file({"source": src, "destination": dst})
    assert "Moved" in result or "moved" in result.lower()
    assert not os.path.exists(src)
    assert os.path.exists(dst)


def test_read_file_not_found():
    result = read_file({"path": "/nonexistent/path/file.txt"})
    assert "not found" in result.lower()


def test_read_file_is_directory(tmpdir):
    result = read_file({"path": tmpdir})
    assert "directory" in result.lower()


def test_read_file_with_offset_and_limit(tmpdir):
    path = os.path.join(tmpdir, "lines.txt")
    write_file({"path": path, "content": "line1\nline2\nline3\nline4\n"})
    result = read_file({"path": path, "offset": 2, "limit": 2})
    assert "line2" in result
    assert "line3" in result
    assert "line1" not in result.split("\n", 1)[1][:100]
    assert "line4" not in result.split("\n")[-2] if "\n" in result else True


def test_read_file_empty(tmpdir):
    path = os.path.join(tmpdir, "empty.txt")
    write_file({"path": path, "content": ""})
    result = read_file({"path": path})
    assert "Lines" in result


def test_list_directory_recursive(tmpdir):
    sub = os.path.join(tmpdir, "sub", "deep")
    create_directory({"path": sub})
    write_file({"path": os.path.join(sub, "f.txt"), "content": "x"})
    result = list_directory({"path": tmpdir, "recursive": True})
    assert "f.txt" in result


def test_list_directory_with_pattern(tmpdir):
    write_file({"path": os.path.join(tmpdir, "a.py"), "content": "x"})
    write_file({"path": os.path.join(tmpdir, "b.md"), "content": "y"})
    result = list_directory({"path": tmpdir, "pattern": "*.py"})
    assert "a.py" in result
    assert "b.md" not in result


def test_find_files_no_match(tmpdir):
    result = find_files({"pattern": "*.zzz", "path": tmpdir})
    assert "No files matching" in result


def test_delete_file_not_found():
    result = delete_file({"path": "/nonexistent/file.txt"})
    assert "not found" in result.lower()


def test_create_directory_already_exists(tmpdir):
    result = create_directory({"path": tmpdir})
    assert "Already exists" in result


def test_move_file_source_not_found():
    result = move_file({"source": "/nonexistent/src.txt", "destination": "/tmp/dst.txt"})
    assert "not found" in result.lower()


def test_write_file_overwrite(tmpdir):
    path = os.path.join(tmpdir, "overwrite.txt")
    write_file({"path": path, "content": "original"})
    result = write_file({"path": path, "content": "updated"})
    assert "Updated" in result
    with open(path) as f:
        assert f.read() == "updated"


def test_read_file_truncates_large_output(tmpdir):
    path = os.path.join(tmpdir, "large.txt")
    large_content = "x" * 60000
    write_file({"path": path, "content": large_content})
    result = read_file({"path": path})
    assert "truncated" in result.lower() or len(result) < 55000


def test_list_directory_empty(tmpdir):
    result = list_directory({"path": tmpdir})
    assert "empty" in result.lower() or "0 items" in result


def test_list_directory_nonexistent():
    result = list_directory({"path": "/nonexistent_dir_xyz"})
    assert "not a directory" in result.lower()


def test_find_files_max_results(tmpdir):
    for i in range(5):
        write_file({"path": os.path.join(tmpdir, f"file_{i}.txt"), "content": "x"})
    result = find_files({"pattern": "*.txt", "path": tmpdir, "max_results": 2})
    assert result.count("\n") >= 2
    assert "5" not in result.split("\n")[0]  # Should not say "Found 5"
