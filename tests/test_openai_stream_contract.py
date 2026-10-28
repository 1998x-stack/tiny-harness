"""OpenAI-compatible streaming contract regression tests."""
import json

import httpx
import pytest

from tiny_harness._llm import FatalLLMError, OpenAIProvider


def _chunk(delta=None, finish=None, usage=None):
    if usage is not None:
        item = {"choices": [], "usage": usage}
    else:
        item = {"choices": [{"delta": delta or {}, "finish_reason": finish}]}
    return "data: " + json.dumps(item) + "\n\n"


def _httpx_fixture(monkeypatch, payload):
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload.encode(),
                                           headers={"content-type": "text/event-stream"})
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_empty_arguments_are_valid_tool_call(monkeypatch):
    payload = "".join([
        _chunk({"tool_calls": [{"index": 0, "id": "c1",
                                "function": {"name": "list_directory", "arguments": ""}}]}),
        _chunk(finish="tool_calls"),
        _chunk(usage={"prompt_tokens": 10, "completion_tokens": 3}),
        "data: [DONE]\n\n",
    ])
    _httpx_fixture(monkeypatch, payload)
    chunks = [c async for c in OpenAIProvider("unused", "fixture").generate_stream(
        [{"role": "user", "content": "list"}]
    )]
    calls = [c.tool_call for c in chunks if c.type == "tool_call_end"]
    assert len(calls) == 1
    assert calls[0].name == "list_directory"
    assert calls[0].arguments == {}
    assert any(c.type == "usage" for c in chunks)
    assert any(c.type == "finish" and c.content == "tool_calls" for c in chunks)


@pytest.mark.asyncio
async def test_usage_only_chunk_and_text_finish(monkeypatch):
    payload = "".join([
        _chunk({"content": "hello"}),
        _chunk(finish="stop"),
        _chunk(usage={"prompt_tokens": 1, "completion_tokens": 1}),
    ])
    _httpx_fixture(monkeypatch, payload)
    chunks = [c async for c in OpenAIProvider("unused", "fixture").generate_stream(
        [{"role": "user", "content": "hi"}]
    )]
    assert [c.content for c in chunks if c.type == "text_delta"] == ["hello"]


@pytest.mark.asyncio
async def test_truncated_stream_must_not_execute_partial_tool(monkeypatch):
    payload = "".join([
        _chunk({"tool_calls": [{"index": 0, "id": "c1",
                                "function": {"name": "write_file", "arguments": '{"path":'}}]}),
        _chunk(finish="length"),
    ])
    _httpx_fixture(monkeypatch, payload)
    with pytest.raises(FatalLLMError, match="complete answer"):
        [c async for c in OpenAIProvider("unused", "fixture").generate_stream(
            [{"role": "user", "content": "write"}]
        )]


@pytest.mark.asyncio
async def test_malformed_json_tool_args_are_not_silently_replaced(monkeypatch):
    payload = "".join([
        _chunk({"tool_calls": [{"index": 0, "id": "c1",
                                "function": {"name": "read_file", "arguments": "{oops"}}]}),
        _chunk(finish="tool_calls"),
    ])
    _httpx_fixture(monkeypatch, payload)
    with pytest.raises(FatalLLMError, match="Invalid streamed tool arguments"):
        [c async for c in OpenAIProvider("unused", "fixture").generate_stream(
            [{"role": "user", "content": "read"}]
        )]
