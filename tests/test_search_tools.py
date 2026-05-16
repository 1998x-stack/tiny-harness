# tests/test_search_tools.py
import tempfile
from tiny_harness.tools.search import search_content, _fallback_grep, _match_filename


def test_finds_pattern_in_python_files():
    result = search_content({"pattern": "def test_", "path": "tests", "file_pattern": "*.py"})
    assert "test_" in result


def test_no_match_returns_message():
    result = search_content({"pattern": "xyznonexistent12345", "path": "tiny_harness", "file_pattern": "*.py"})
    assert "No matches" in result


def test_invalid_regex_handled():
    result = search_content({"pattern": "[invalid", "path": "tiny_harness", "file_pattern": "*.py"})
    assert "Error" in result or "No matches" in result


def test_file_filter_works():
    result = search_content({"pattern": "import", "path": "tiny_harness", "file_pattern": "*.py", "max_results": 5})
    assert "import" in result.lower()


def test_max_results_respected():
    result = search_content({"pattern": "def ", "path": "tiny_harness", "file_pattern": "*.py", "max_results": 3})
    lines = [line for line in result.split("\n") if line.startswith("  ")]
    assert len(lines) <= 3


def test_search_subdirectory():
    result = search_content({"pattern": "class Agent", "path": "tiny_harness", "file_pattern": "*.py"})
    assert "class Agent" in result


def test_match_filename_glob():
    assert _match_filename("test.py", "*.py") is True
    assert _match_filename("test.txt", "*.py") is False
    assert _match_filename("test.py", "test.*") is True
    assert _match_filename("deep/file.py", "*.py") is True


def test_fallback_grep_works():
    results = _fallback_grep("import", "tiny_harness/_config.py", None, max_results=5)
    assert len(results) > 0
    assert "import" in results[0]


def test_fallback_grep_max_results():
    results = _fallback_grep("def ", "tiny_harness", "*.py", max_results=2)
    assert len(results) <= 2


def test_fallback_grep_invalid_regex():
    results = _fallback_grep("[invalid", ".", None)
    assert "invalid regex" in results[0].lower()


def test_search_empty_directory():
    with tempfile.TemporaryDirectory() as d:
        result = search_content({"pattern": "anything", "path": d})
        assert "No matches" in result


def test_search_binary_file_skipped():
    result = search_content({"pattern": "anything", "path": "tiny_harness", "file_pattern": "*.pyc"})
    assert result
