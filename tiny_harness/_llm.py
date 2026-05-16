# tiny_harness/_llm.py
from dataclasses import dataclass, field
from collections.abc import AsyncIterator
from abc import ABC, abstractmethod
from typing import Any
import json
import asyncio
import random


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
    pass


class FatalLLMError(Exception):
    pass


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, retry_config: LLMRetryConfig | None = None):
        self._api_key = api_key
        self._model = model
        self._retry_config = retry_config or LLMRetryConfig()

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        return [m for m in messages if m["role"] != "system"]

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

        body: dict = {"model": self._model, "max_tokens": 16384, "messages": converted, "stream": False}
        if system:
            body["system"] = system
        if converted_tools:
            body["tools"] = converted_tools

        last_error = None
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        json=body,
                        headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    )
                if resp.status_code == 200:
                    return self._parse_response(_ResponseAdapter(resp.json()))
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
        import httpx

        system = self._extract_system(messages)
        converted = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)

        body: dict = {"model": self._model, "max_tokens": 16384, "messages": converted, "stream": True}
        if system:
            body["system"] = system
        if converted_tools:
            body["tools"] = converted_tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", "https://api.anthropic.com/v1/messages",
                json=body,
                headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    body_bytes = await response.aread()
                    raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")
                async for line in response.aiter_lines():
                    parsed = self._parse_sse_line(line)
                    if parsed is None:
                        continue
                    event_type, value = parsed
                    if event_type == "message_start":
                        yield LLMStreamChunk(type="usage", content=json.dumps({"input": value.get("message", {}).get("usage", {}).get("input_tokens", 0)}))
                    elif event_type == "content_block_start":
                        block = value.get("content_block", {})
                        if block.get("type") == "tool_use":
                            yield LLMStreamChunk(type="tool_call_start", content=json.dumps({"id": block["id"], "name": block["name"]}))
                    elif event_type == "content_block_delta":
                        delta = value.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield LLMStreamChunk(type="text_delta", content=delta.get("text", ""))
                        elif delta.get("type") == "input_json_delta":
                            yield LLMStreamChunk(type="tool_call_delta", content=delta.get("partial_json", ""))
                    elif event_type == "content_block_stop":
                        yield LLMStreamChunk(type="tool_call_end")


class _ResponseAdapter:
    def __init__(self, data: dict):
        self.content = [_BlockAdapter(b) for b in data.get("content", [])]
        self.usage = _UsageAdapter(data.get("usage", {}))
        self.model = data.get("model", "")
        self.stop_reason = data.get("stop_reason", "stop")


class _BlockAdapter:
    def __init__(self, data: dict):
        self.type = data.get("type", "")
        self.text = data.get("text", "")
        self.name = data.get("name", "")
        self.input = data.get("input", {})
        self.id = data.get("id", "")


class _UsageAdapter:
    def __init__(self, data: dict):
        self.input_tokens = data.get("input_tokens", 0)
        self.output_tokens = data.get("output_tokens", 0)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", retry_config: LLMRetryConfig | None = None):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._retry_config = retry_config or LLMRetryConfig()

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
        body: dict = {"model": self._model, "messages": self._convert_messages(messages), "stream": False}
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
        import httpx
        body: dict = {"model": self._model, "messages": self._convert_messages(messages), "stream": True}
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            body["tools"] = converted_tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    body_bytes = await response.aread()
                    raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        yield LLMStreamChunk(type="text_delta", content=delta["content"])
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            func = tc.get("function", {})
                            if "name" in func:
                                yield LLMStreamChunk(type="tool_call_start", content=json.dumps({"id": tc.get("id", ""), "name": func["name"]}))
                            if "arguments" in func:
                                yield LLMStreamChunk(type="tool_call_delta", content=func["arguments"])
