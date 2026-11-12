# tiny_harness/_llm.py
from dataclasses import dataclass
from collections.abc import AsyncIterator
from abc import ABC, abstractmethod
from typing import Any
import json
import asyncio
import random

from tiny_harness._sse import anthropic_events, openai_events
from tiny_harness._llm_response import ResponseAdapter


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCallRequest]
    usage: TokenUsage
    finish_reason: str

    def is_final(self) -> bool:
        return len(self.tool_calls) == 0


@dataclass
class LLMStreamChunk:
    type: str
    content: str | None = None
    tool_call: ToolCallRequest | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def generate_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMStreamChunk]:
        ...


@dataclass
class LLMRetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0


class RetryableLLMError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class FatalLLMError(Exception):
    pass


def _retry_after_seconds(value: str | None) -> float | None:
    """Retry-After may be delta-seconds or an HTTP-date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (ValueError, TypeError):
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


async def _safe_retry_stream(factory, config: LLMRetryConfig):
    """Retry stream failures only before the first externally visible chunk.

    Once any chunk has been yielded, the consumer may already have printed it
    or collected tool-call state. Replaying would duplicate content or actions.
    """
    import httpx

    retryable_transport = (
        httpx.TimeoutException, httpx.ConnectError, httpx.ReadError,
        httpx.RemoteProtocolError,
    )
    for attempt in range(config.max_retries + 1):
        emitted = False
        try:
            async for chunk in factory():
                emitted = True
                yield chunk
            return
        except (RetryableLLMError, *retryable_transport) as exc:
            if emitted:
                raise FatalLLMError(
                    f"Stream failed after output began; not retrying: {exc}"
                ) from exc
            if attempt >= config.max_retries:
                raise FatalLLMError(f"Stream retries exhausted: {exc}") from exc
            backoff = min(
                config.base_delay * config.backoff_factor ** attempt,
                config.max_delay,
            )
            if isinstance(exc, RetryableLLMError) and exc.retry_after is not None:
                delay = min(exc.retry_after, config.max_delay)
            else:
                delay = backoff + random.uniform(0, backoff * 0.5)
            await asyncio.sleep(delay)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, retry_config: LLMRetryConfig | None = None, max_tokens: int = 16384, base_url: str = "https://api.anthropic.com/v1"):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._retry_config = retry_config or LLMRetryConfig()
        self._max_tokens = max_tokens

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        converted: list[dict] = []
        for message in messages:
            role = message["role"]
            if role == "system":
                continue
            if role == "assistant" and message.get("tool_calls"):
                content = []
                if message.get("content"):
                    content.append({"type": "text", "text": message["content"]})
                for tool_call in message["tool_calls"]:
                    function = tool_call.get("function", {})
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    content.append({
                        "type": "tool_use",
                        "id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "input": arguments,
                    })
                converted.append({"role": "assistant", "content": content})
            elif role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id", ""),
                    "content": message.get("content", ""),
                }
                if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                    converted[-1]["content"].append(block)
                else:
                    converted.append({"role": "user", "content": [block]})
            else:
                converted.append({"role": role, "content": message.get("content", "")})
        return converted

    def _extract_system(self, messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "system":
                return m["content"]
        return ""

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]

    def _parse_response(self, response) -> LLMResponse:
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=block.input))
        return LLMResponse(
            text="".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens),
            finish_reason=response.stop_reason or "stop",
        )

    def _parse_sse_line(self, line: str) -> tuple[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        if line.startswith("event: "):
            return (line[7:], None)
        if line.startswith("data: "):
            return ("data", json.loads(line[5:]))
        return ("unknown", line)

    async def generate(self, messages, tools=None) -> LLMResponse:
        import httpx

        system = self._extract_system(messages)
        converted = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)

        body: dict = {"model": self._model, "max_tokens": self._max_tokens, "messages": converted, "stream": False}
        if system:
            body["system"] = system
        if converted_tools:
            body["tools"] = converted_tools

        last_error = None
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/messages",
                        json=body,
                        headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    )
                if resp.status_code == 200:
                    return self._parse_response(ResponseAdapter(resp.json()))
                if resp.status_code in (429, 529) or resp.status_code >= 500:
                    raise RetryableLLMError(f"Status {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise FatalLLMError(f"Auth failed: {resp.status_code}")
                raise FatalLLMError(f"API error: {resp.status_code}")
            except (RetryableLLMError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt == self._retry_config.max_retries:
                    raise FatalLLMError(f"All retries exhausted: {e}")
                delay = min(self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt), self._retry_config.max_delay)
                await asyncio.sleep(delay + random.uniform(0, delay * 0.5))
        raise FatalLLMError(f"All retries exhausted: {last_error}")

    async def generate_stream(self, messages, tools=None):
        async for chunk in _safe_retry_stream(
            lambda: self._generate_stream_once(messages, tools), self._retry_config,
        ):
            yield chunk

    async def _generate_stream_once(self, messages, tools=None):
        import httpx

        system = self._extract_system(messages)
        converted = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)

        body: dict = {"model": self._model, "max_tokens": self._max_tokens, "messages": converted, "stream": True}
        if system:
            body["system"] = system
        if converted_tools:
            body["tools"] = converted_tools

        for attempt in range(self._retry_config.max_retries + 1):
            emitted = False
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST", "https://api.anthropic.com/v1/messages",
                        json=body,
                        headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    ) as response:
                        if response.status_code != 200:
                            body_bytes = await response.aread()
                            if response.status_code in (429, 529) or response.status_code >= 500:
                                raise RetryableLLMError(f"Status {response.status_code}")
                            raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")
                        async for chunk in self._stream_chunks(response):
                            emitted = True
                            yield chunk
                        return
            except (RetryableLLMError, httpx.TimeoutException, httpx.ConnectError) as e:
                if emitted or attempt == self._retry_config.max_retries:
                    raise FatalLLMError(f"Stream failed after retries: {e}")
                delay = min(
                    self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt),
                    self._retry_config.max_delay,
                )
                await asyncio.sleep(delay + random.uniform(0, delay * 0.5))

    async def _stream_chunks(self, response):
        async for event in anthropic_events(response.aiter_lines(), self._parse_sse_line):
            tool_call = event.get("tool_call")
            yield LLMStreamChunk(
                type=event["type"],
                content=event.get("content"),
                tool_call=ToolCallRequest(**tool_call) if tool_call else None,
            )


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", retry_config: LLMRetryConfig | None = None, max_tokens: int = 16384):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._retry_config = retry_config or LLMRetryConfig()
        self._max_tokens = max_tokens

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        return messages

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice["message"]
        tool_calls = []
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_calls.append(ToolCallRequest(id=tc["id"], name=tc["function"]["name"], arguments=json.loads(tc["function"]["arguments"])))
        return LLMResponse(
            text=msg.get("content"),
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=data.get("usage", {}).get("prompt_tokens", 0), output_tokens=data.get("usage", {}).get("completion_tokens", 0)),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def generate(self, messages, tools=None) -> LLMResponse:
        import httpx
        body: dict = {"model": self._model, "messages": self._convert_messages(messages), "max_tokens": self._max_tokens, "stream": False}
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools

        last_error = None
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    )
                if resp.status_code == 200:
                    return self._parse_response(resp.json())
                if resp.status_code in (429, 529) or resp.status_code >= 500:
                    raise RetryableLLMError(f"Status {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise FatalLLMError(f"Auth failed: {resp.status_code}")
                raise FatalLLMError(f"API error: {resp.status_code}")
            except (RetryableLLMError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt == self._retry_config.max_retries:
                    raise FatalLLMError(f"All retries exhausted: {e}")
                delay = min(self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt), self._retry_config.max_delay)
                await asyncio.sleep(delay + random.uniform(0, delay * 0.5))
        raise FatalLLMError(f"All retries exhausted: {last_error}")

    async def generate_stream(self, messages, tools=None):
        async for chunk in _safe_retry_stream(
            lambda: self._generate_stream_once(messages, tools), self._retry_config,
        ):
            yield chunk

    async def _generate_stream_once(self, messages, tools=None):
        import httpx
        body: dict = {"model": self._model, "messages": self._convert_messages(messages), "max_tokens": self._max_tokens, "stream": True}
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools

        for attempt in range(self._retry_config.max_retries + 1):
            emitted = False
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST", f"{self._base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    ) as response:
                        if response.status_code != 200:
                            body_bytes = await response.aread()
                            if response.status_code in (429, 529) or response.status_code >= 500:
                                raise RetryableLLMError(f"Status {response.status_code}")
                            raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")
                        async for chunk in self._stream_chunks(response):
                            emitted = True
                            yield chunk
                        return
            except (RetryableLLMError, httpx.TimeoutException, httpx.ConnectError) as e:
                if emitted or attempt == self._retry_config.max_retries:
                    raise FatalLLMError(f"Stream failed after retries: {e}")
                delay = min(
                    self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt),
                    self._retry_config.max_delay,
                )
                await asyncio.sleep(delay + random.uniform(0, delay * 0.5))

    async def _stream_chunks(self, response):
        async for event in openai_events(response.aiter_lines()):
            tool_call = event.get("tool_call")
            yield LLMStreamChunk(
                type=event["type"],
                content=event.get("content"),
                tool_call=ToolCallRequest(**tool_call) if tool_call else None,
            )
