"""Anthropic finish reasons, stream completeness, and gateway routing."""
import json

import httpx
import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._llm import AnthropicProvider, FatalLLMError


def frame(event, data=None):
    return "event: " + event + "\ndata: " + json.dumps({"type": event, **(data or {})}) + "\n\n"


def mock_stream(monkeypatch, response_body, urls=None):
    original = httpx.AsyncClient

    def transport(request):
        if urls is not None:
            urls.append(str(request.url))
        return httpx.Response(
            200, content=response_body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_max_tokens_rejects_complete_tool_block(monkeypatch):
    # A tool-use block can be syntactically complete while the overall model
    # reply is truncated. Tool execution must not proceed.
    payload = "".join([
        frame("content_block_start", {"index": 0, "content_block": {
            "type": "tool_use", "id": "c1", "name": "write_file", "input": {},
        }}),
        frame("content_block_delta", {"index": 0, "delta": {
            "type": "input_json_delta", "partial_json": '{"path":"x"}',
        }}),
        frame("content_block_stop", {"index": 0}),
        frame("message_delta", {"delta": {"stop_reason": "max_tokens"}}),
        frame("message_stop"),
    ])
    mock_stream(monkeypatch, payload)
    with pytest.raises(FatalLLMError, match="max_tokens"):
        [chunk async for chunk in AnthropicProvider("unused", "test").generate_stream(
            [{"role": "user", "content": "test"}]
        )]


@pytest.mark.asyncio
async def test_missing_message_stop_is_not_treated_as_success(monkeypatch):
    payload = frame("content_block_delta", {"index": 0, "delta": {
        "type": "text_delta", "text": "partial",
    }})
    mock_stream(monkeypatch, payload)
    with pytest.raises(FatalLLMError, match="without message_stop"):
        [chunk async for chunk in AnthropicProvider("unused", "test").generate_stream(
            [{"role": "user", "content": "hello"}]
        )]


@pytest.mark.asyncio
async def test_normal_finish_emits_usage_and_reason(monkeypatch):
    payload = "".join([
        frame("message_start", {"message": {"usage": {"input_tokens": 3}}}),
        frame("content_block_delta", {"index": 0, "delta": {
            "type": "text_delta", "text": "complete",
        }}),
        frame("message_delta", {
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 2},
        }),
        frame("message_stop"),
    ])
    urls = []
    mock_stream(monkeypatch, payload, urls)
    provider = AnthropicProvider("unused", "test", base_url="https://gateway.example.test/api")
    chunks = [chunk async for chunk in provider.generate_stream(
        [{"role": "user", "content": "hello"}]
    )]
    assert urls == ["https://gateway.example.test/api/messages"]
    assert [c.content for c in chunks if c.type == "text_delta"] == ["complete"]
    assert [c.content for c in chunks if c.type == "finish"] == ["end_turn"]
    assert len([c for c in chunks if c.type == "usage"]) == 2


def test_agent_forwards_anthropic_gateway(tmp_path):
    agent = Agent(Prompt("system"), Config(
        model="fake", api_key="unused", workspace=str(tmp_path),
        provider="anthropic", api_base_url="https://gateway.example.test/v1",
    ))
    assert agent._llm_provider._base_url == "https://gateway.example.test/v1"
