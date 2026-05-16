# tests/test_shell_tools.py
"""Comprehensive tests for shell command tool."""
import os
import pytest
from tiny_harness.tools.shell import run_command


def test_basic_echo():
    result = run_command({"command": "echo hello"})
    assert "hello" in result
    assert "exit code" not in result


def test_cwd():
    result = run_command({"command": "pwd", "cwd": "/tmp"})
    assert "/tmp" in result


def test_exit_code_nonzero():
    result = run_command({"command": "python3 -c \"import sys; sys.exit(1)\""})
    assert "[exit code: 1]" in result


def test_timeout():
    result = run_command({"command": "sleep 10", "timeout": 1})
    assert "timed out" in result.lower()


def test_stderr_captured():
    result = run_command({"command": "echo err >&2; echo out"})
    assert "err" in result
    assert "[stderr]" in result


def test_no_output():
    result = run_command({"command": "true"})
    assert result == "(no output)"


def test_empty_command():
    result = run_command({"command": ""})
    assert "(no output)" in result


def test_multiline_output():
    result = run_command({"command": "printf 'a\nb\nc'"})
    assert "a" in result
    assert "b" in result
    assert "c" in result


def test_command_with_special_chars():
    result = run_command({"command": "echo 'hello world'"})
    assert "hello world" in result


def test_command_with_env():
    result = run_command({"command": "MYVAR=hello python3 -c 'import os; print(os.environ[\"MYVAR\"])'"})
    assert "hello" in result.lower()

@pytest.mark.skipif(os.name == "nt", reason="Unix only")
def test_custom_timeout():
    result = run_command({"command": "sleep 2", "timeout": 1})
    assert "timed out" in result.lower()


def test_output_truncation():
    large_cmd = "python3 -c \"print('x' * 60000)\""
    result = run_command({"command": large_cmd})
    assert "truncated" in result.lower()
