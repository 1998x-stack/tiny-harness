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
