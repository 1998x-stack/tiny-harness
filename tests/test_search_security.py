"""Regression checks for search command argument safety and workspace isolation."""
import subprocess
from types import SimpleNamespace

import pytest

from tiny_harness._guard import FilesystemGuard
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry
from tiny_harness.tools.search import search_content


def test_regex_looking_like_ripgrep_flag_is_literal(monkeypatch, tmp_path):
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = search_content({"pattern": "--pre=sh", "path": str(tmp_path)})
    assert "No matches" in result
    assert observed["argv"][-4:] == ["-e", "--pre=sh", "--", str(tmp_path)]
    assert observed["kwargs"]["stdin"] == subprocess.DEVNULL
    assert "cwd" not in observed["kwargs"]


@pytest.mark.asyncio
async def test_search_defaults_to_workspace_even_if_process_cwd_differs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("search_content", "search", {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}
        }, "required": ["pattern"]}),
        lambda args: args["path"],
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(workspace)))
    result = await executor.execute("search_content", {"pattern": "example"}, "search-1")
    assert result.success
    assert result.content == str(workspace)
    denied = await executor.execute("search_content", {"pattern": "example", "path": str(elsewhere)}, "search-2")
    assert not denied.success
    assert "outside" in denied.content
