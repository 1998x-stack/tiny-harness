"""Streaming retries must never replay already delivered output."""
import asyncio
import json

import httpx
import pytest

from tiny_harness._llm import (
    AnthropicProvider, FatalLLMError, LLMRetryConfig, LLMStreamChunk,
    OpenAIProvider, RetryableLLMError, _retry_after_seconds,
    _safe_retry_stream,
)


def _openai_success():
    return ('data: ' + json.dumps({"choices": [{"delta": {"content": "ok"},
                                               "finish_reason": None}]}) + "\n\n"
            + 'data: ' + json.dumps({"choices": [{"delta": {},
                                                   "finish_reason": "stop"}]}) + "\n\n"
            + 'data: [DONE]\n\n')


def _anthropic_success():
    return (
        'event: content_block_delta\ndata: '
        + json.dumps({"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "ok"}})
        + "\n\n"
        + 'event: message_delta\ndata: '
        + json.dumps({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
        + "\n\n"
        + 'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )


@pytest.mark.parametrize("provider_class,body", [
    (OpenAIProvider, _openai_success()),
    (AnthropicProvider, _anthropic_success()),
])
@pytest.mark.asyncio
async def test_retry_429_before_first_event(provider_class, body, monkeypatch):
    attempts = []
    delays = []
    original = httpx.AsyncClient

    def transport(request):
        attempts.append(str(request.url))
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "text/event-stream"})

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return original(*args, **kwargs)

    async def fake_sleep(value):
        delays.append(value)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr("tiny_harness._llm.asyncio.sleep", fake_sleep)
    provider = provider_class(
        api_key="fixture", model="test",
        retry_config=LLMRetryConfig(max_retries=2, base_delay=0,
                                    max_delay=0.05),
    )
    chunks = [c async for c in provider.generate_stream(
        [{"role": "user", "content": "hello"}]
    )]
    assert len(attempts) == 2
    assert delays == [0.05]
    assert [c.content for c in chunks if c.type == "text_delta"] == ["ok"]


@pytest.mark.parametrize("provider_class", [OpenAIProvider, AnthropicProvider])
@pytest.mark.asyncio
async def test_stream_401_is_never_retried(provider_class, monkeypatch):
    attempts = []
    original = httpx.AsyncClient
    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: attempts.append(str(request.url)) or httpx.Response(401)
        )
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = provider_class("fixture", "test",
                              retry_config=LLMRetryConfig(max_retries=2))
    with pytest.raises(FatalLLMError, match="401"):
        [c async for c in provider.generate_stream(
            [{"role": "user", "content": "hi"}]
        )]
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_failure_after_first_chunk_does_not_replay():
    attempts = 0

    async def once():
        nonlocal attempts
        attempts += 1
        yield LLMStreamChunk(type="text_delta", content="visible")
        raise RetryableLLMError("upstream disconnected")

    chunks = []
    with pytest.raises(FatalLLMError, match="not retrying"):
        async for c in _safe_retry_stream(
            once, LLMRetryConfig(max_retries=3, base_delay=0),
        ):
            chunks.append(c.content)
    assert chunks == ["visible"]
    assert attempts == 1


@pytest.mark.asyncio
async def test_retryable_status_exhaustion_fails_cleanly(monkeypatch):
    requests = []
    original = httpx.AsyncClient
    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: requests.append(1) or httpx.Response(503)
        )
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    provider = OpenAIProvider("fixture", "test", retry_config=LLMRetryConfig(
        max_retries=1, base_delay=0, max_delay=0,
    ))
    with pytest.raises(FatalLLMError, match="retries exhausted"):
        [c async for c in provider.generate_stream(
            [{"role": "user", "content": "hi"}]
        )]
    assert len(requests) == 2


def test_retry_after_seconds_and_invalid_header():
    assert _retry_after_seconds("5") == 5.0
    assert _retry_after_seconds("-1") == 0
    assert _retry_after_seconds("not a date") is None
