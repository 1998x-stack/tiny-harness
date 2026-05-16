# tests/test_search_tools.py
from tiny_harness.tools.search import search_content
from tiny_harness.tools.shell import run_command


def test_run_command_echo():
    result = run_command({"command": "echo hello"})
    assert "hello" in result


def test_run_command_with_cwd():
    result = run_command({"command": "pwd", "cwd": "/tmp"})
    assert "/tmp" in result


def test_run_command_exit_code():
    result = run_command({"command": "exit 1"})
    assert "exit code: 1" in result


def test_run_command_timeout():
    result = run_command({"command": "sleep 10", "timeout": 1})
    assert "timed out" in result.lower()


def test_search_content_finds_pattern():
    result = search_content({"pattern": "def test_", "path": "tests", "file_pattern": "*.py"})
    assert "test_" in result


def test_search_content_no_match():
    result = search_content({"pattern": "xyznonexistent12345", "path": "tiny_harness", "file_pattern": "*.py"})
    assert "No matches" in result


def test_search_content_invalid_regex():
    result = search_content({"pattern": "[invalid", "path": "tiny_harness", "file_pattern": "*.py"})
    assert "Error" in result or "No matches" in result


def test_search_content_file_filter():
    result = search_content({"pattern": "import", "path": "tiny_harness", "file_pattern": "*.py", "max_results": 5})
    assert "import" in result.lower()
