"""Transcripts must remain API-valid across exceptions and cancellations."""
import asyncio

import pytest

from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._events import EventBus, StreamEvent
from tiny_harness._guard import FilesystemGuard
from tiny_harness._hitl import ApprovalGate
from tiny_harness._llm import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from tiny_harness._loop import AgentLoop
from tiny_harness._messages import MessageManager
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry, ToolResult


@pytest.mark.asyncio
async def test_approval_callback_exception_is_denial(tmp_path):
    async def broken_input(request):
        raise EOFError("stdin closed")
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("write_file", "write", {"type": "object"}, "mutation"),
        lambda args: "must not execute",
    )
    executor = ToolExecutor(
        registry, FilesystemGuard(str(tmp_path)),
        approval_gate=ApprovalGate(handler=broken_input),
    )
    result = await executor.execute("write_file", {}, "tc1")
    assert not result.success and result.denied
    assert "approval failed" in result.content


def _tool_calls():
    return [
        ToolCallRequest(id="c1", name="first", arguments={}),
        ToolCallRequest(id="c2", name="second", arguments={}),
    ]


@pytest.mark.asyncio
async def test_unexpected_executor_failure_keeps_transcript_complete(tmp_path):
    messages = MessageManager(Prompt("system"))
    calls = _tool_calls()

    class Provider:
        turns = 0
        async def generate_stream(self, history, tools):
            self.turns += 1
            if self.turns == 1:
                for call in calls:
                    yield LLMStreamChunk(type="tool_call_end", tool_call=call)
            else:
                assert [m["tool_call_id"] for m in history if m["role"] == "tool"] == ["c1", "c2"]
                yield LLMStreamChunk(type="text_delta", content="recovered")

    class Executor:
        def get_definitions(self):
            return []
        async def execute(self, name, args, call_id):
            if call_id == "c1":
                raise RuntimeError("unavailable")
            return ToolResult.ok(call_id, "ok")

    result = await AgentLoop(
        AgentConfig(model="test", api_key="unused", workspace=str(tmp_path)),
        messages, Provider(), Executor(), EventBus()
    ).run("go")
    assert result == "recovered"
    assert len([m for m in messages.to_list() if m["role"] == "tool"]) == 2


@pytest.mark.asyncio
async def test_cancellation_fills_remaining_tool_results(tmp_path):
    entered = asyncio.Event()
    messages = MessageManager(Prompt("system"))

    class Provider:
        async def generate_stream(self, history, tools):
            for call in _tool_calls():
                yield LLMStreamChunk(type="tool_call_end", tool_call=call)

    class BlockingExecutor:
        def get_definitions(self):
            return []
        async def execute(self, name, args, call_id):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(AgentLoop(
        AgentConfig(model="test", api_key="unused", workspace=str(tmp_path)),
        messages, Provider(), BlockingExecutor(), EventBus()
    ).run("go"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    transcript = messages.to_list()
    assert [m["tool_call_id"] for m in transcript if m["role"] == "tool"] == ["c1", "c2"]


@pytest.mark.asyncio
async def test_observer_errors_do_not_interrupt_agent():
    bus = EventBus()
    called = []

    async def broken(event):
        raise RuntimeError("subscriber failed")

    async def healthy(event):
        called.append(event.type)

    bus.subscribe(broken)
    bus.subscribe(healthy)
    await bus.emit(StreamEvent(type="tool_start", tool_name="read_file"))
    assert called == ["tool_start"]
