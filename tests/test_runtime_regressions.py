"""Regression tests for runtime safety and complete provider transcripts."""
import asyncio
import os
import time

import pytest

from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._events import EventBus
from tiny_harness._llm import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from tiny_harness._loop import AgentLoop
from tiny_harness._messages import MessageManager
from tiny_harness._guard import FilesystemGuard
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry, ToolResult, validate_schema
from tiny_harness.tools.files import find_files


@pytest.mark.asyncio
async def test_error_budget_preserves_every_tool_call_result(tmp_path):
    calls = [ToolCallRequest(id=f"call-{i}", name="fail", arguments={"n": i}) for i in range(3)]
    messages = MessageManager(Prompt("test"))

    class Provider:
        async def generate_stream(self, history, tools):
            for call in calls:
                yield LLMStreamChunk(type="tool_call_end", tool_call=call)

        async def generate(self, history, tools):
            assert tools == []
            assert [m["tool_call_id"] for m in history if m["role"] == "tool"] == [c.id for c in calls]
            return LLMResponse(text="finished", tool_calls=[], usage=TokenUsage(input_tokens=1, output_tokens=1), finish_reason="stop")

    class Executor:
        def __init__(self):
            self.calls = 0

        def get_definitions(self):
            return []

        async def execute(self, name, args, call_id):
            self.calls += 1
            return ToolResult.error(call_id, "failure")

    executor = Executor()
    config = AgentConfig(model="test", api_key="unused", workspace=str(tmp_path), max_errors=1)
    result = await AgentLoop(config, messages, Provider(), executor, EventBus()).run("test")
    assert result == "finished"
    assert executor.calls == 1
    assert len([m for m in messages.to_list() if m["role"] == "tool"]) == 3


@pytest.mark.asyncio
async def test_relative_file_path_uses_workspace_not_process_cwd(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("write_file", "write", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, "mutation"),
        lambda args: open(args["path"], "w").write("inside"),
    )
    result = await ToolExecutor(registry, FilesystemGuard(str(workspace))).execute("write_file", {"path": "note.txt"}, "a")
    assert result.success
    assert (workspace / "note.txt").read_text() == "inside"
    assert not (elsewhere / "note.txt").exists()


@pytest.mark.asyncio
async def test_move_validates_both_source_and_destination(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("move_file", "move", {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]}, "mutation"),
        lambda args: "should not execute",
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(workspace)))
    for arguments in (
        {"source": str(outside), "destination": "inside.txt"},
        {"source": "inside.txt", "destination": str(outside)},
    ):
        result = await executor.execute("move_file", arguments, "a")
        assert not result.success
        assert "outside" in result.content
    assert outside.read_text() == "keep"


@pytest.mark.asyncio
async def test_default_directory_path_uses_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    registry = ToolRegistry()
    registry.register_from_def(ToolDef("list_directory", "list", {"type": "object"}), lambda args: args["path"])
    result = await ToolExecutor(registry, FilesystemGuard(str(workspace))).execute("list_directory", {}, "a")
    assert result.content == str(workspace)


@pytest.mark.asyncio
async def test_glob_does_not_return_symlinked_external_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (workspace / "linked.txt").symlink_to(outside)
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("find_files", "find", {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}),
        find_files,
    )
    result = await ToolExecutor(registry, FilesystemGuard(str(workspace))).execute("find_files", {"pattern": "*.txt"}, "a")
    assert result.success
    assert "linked.txt" not in result.content


@pytest.mark.asyncio
async def test_sync_handler_times_out_without_freezing_event_loop(tmp_path):
    registry = ToolRegistry()
    registry.register_from_def(ToolDef("slow", "slow", {"type": "object"}), lambda args: time.sleep(0.3))
    executor = ToolExecutor(registry, FilesystemGuard(str(tmp_path)), timeout_ms=20)
    started = time.monotonic()
    result = await executor.execute("slow", {}, "a")
    assert not result.success
    assert "timed out" in result.content
    assert time.monotonic() - started < 0.25


def test_schema_rejects_bool_as_integer_and_non_object_args():
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    assert validate_schema(schema, {"count": True})
    assert validate_schema(schema, ["invalid"])
