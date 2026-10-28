"""Anthropic wire contracts: actual SSE event/data frames and tool message blocks."""
import json

import httpx
import pytest

from tiny_harness._llm import AnthropicProvider, FatalLLMError
from tiny_harness._messages import MessageManager
from tiny_harness._config import Prompt
from tiny_harness._llm import ToolCallRequest


def test_anthropic_message_conversion_round_trips_tool_ids():
    mgr = MessageManager(Prompt("system"))
    mgr.add_user("inspect")
    mgr.add_assistant("checking", [
        ToolCallRequest("c1", "read_file", {"path": "a.py"}),
        ToolCallRequest("c2", "list_directory", {"path": "."}),
    ])
    mgr.add_tool_result("c1", "content")
    mgr.add_tool_result("c2", "listing")
    provider = AnthropicProvider("unused", "fixture")
    converted = provider._convert_messages(mgr.to_list())
    assert [msg["role"] for msg in converted] == ["user", "assistant", "user"]
    tools = converted[1]["content"]
    assert [block["type"] for block in tools] == ["text", "tool_use", "tool_use"]
    assert tools[1]["id"] == "c1" and tools[1]["input"] == {"path": "a.py"}
    results = converted[2]["content"]
    assert [block["tool_use_id"] for block in results] == ["c1", "c2"]
    assert all(block["type"] == "tool_result" for block in results)


def _frame(event, data):
    return "event: " + event + "\ndata: " + json.dumps({"type": event, **data}) + "\n\n"


def _mock_httpx(monkeypatch, payload, observed=None):
    original = httpx.AsyncClient

    def handler(request):
        if observed is not None:
            observed.append(json.loads(request.content.decode()))
        return httpx.Response(200, content=payload.encode(), headers={"content-type": "text/event-stream"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_anthropic_stream_emits_text_and_complete_tool_calls(monkeypatch):
    payload = "".join([
        _frame("message_start", {"message": {"usage": {"input_tokens": 12}}}),
        _frame("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        _frame("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Checking"}}),
        _frame("content_block_stop", {"index": 0}),
        _frame("content_block_start", {"index": 1, "content_block": {
            "type": "tool_use", "id": "c1", "name": "read_file", "input": {},
        }}),
        _frame("content_block_delta", {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":'}}),
        _frame("content_block_delta", {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '"a.py"}'}}),
        _frame("content_block_stop", {"index": 1}),
        _frame("content_block_start", {"index": 2, "content_block": {
            "type": "tool_use", "id": "c2", "name": "list_directory", "input": {},
        }}),
        _frame("content_block_delta", {"index": 2, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
        _frame("content_block_stop", {"index": 2}),
        _frame("message_stop", {}),
    ])
    observed = []
    _mock_httpx(monkeypatch, payload, observed)
    chunks = [c async for c in AnthropicProvider("unused", "fixture").generate_stream(
        [{"role": "system", "content": "system"}, {"role": "user", "content": "inspect"}], []
    )]
    assert observed[0]["system"] == "system"
    assert [c.content for c in chunks if c.type == "text_delta"] == ["Checking"]
    tc = [c.tool_call for c in chunks if c.type == "tool_call_end"]
    assert [(c.id, c.name, c.arguments) for c in tc] == [
        ("c1", "read_file", {"path": "a.py"}),
        ("c2", "list_directory", {}),
    ]


@pytest.mark.asyncio
async def test_anthropic_text_block_stop_does_not_emit_tool_call(monkeypatch):
    payload = "".join([
        _frame("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        _frame("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
        _frame("content_block_stop", {"index": 0}),
        _frame("message_stop", {}),
    ])
    _mock_httpx(monkeypatch, payload)
    chunks = [c async for c in AnthropicProvider("unused", "fixture").generate_stream(
        [{"role": "user", "content": "hi"}]
    )]
    assert [c.content for c in chunks if c.type == "text_delta"] == ["Hello"]
    assert [c for c in chunks if c.type == "tool_call_end"] == []


@pytest.mark.asyncio
async def test_anthropic_stream_rejects_incomplete_tool_json(monkeypatch):
    payload = "".join([
        _frame("content_block_start", {"index": 0, "content_block": {
            "type": "tool_use", "id": "c1", "name": "read_file", "input": {},
        }}),
        _frame("content_block_delta", {"index": 0, "delta": {
            "type": "input_json_delta", "partial_json": '{"path":',
        }}),
        _frame("content_block_stop", {"index": 0}),
    ])
    _mock_httpx(monkeypatch, payload)
    with pytest.raises(FatalLLMError, match="Invalid streamed tool arguments"):
        [c async for c in AnthropicProvider("unused", "fixture").generate_stream(
            [{"role": "user", "content": "read"}]
        )]
