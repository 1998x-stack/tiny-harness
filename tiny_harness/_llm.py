# tiny_harness/_llm.py
from dataclasses import dataclass
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
        """Translate the harness' OpenAI-style transcript to Anthropic blocks."""
        wire: list[dict] = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                continue
            if role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg["tool_call_id"],
                    "content": str(msg.get("content") or ""),
                }
                # Multiple tool results from one assistant turn share a user message.
                if (wire and wire[-1]["role"] == "user"
                        and isinstance(wire[-1]["content"], list)
                        and all(x.get("type") == "tool_result" for x in wire[-1]["content"])):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
                continue
            if role == "assistant":
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls:
                    wire.append({"role": "assistant", "content": msg.get("content") or ""})
                    continue
                blocks: list[dict] = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for tc in tool_calls:
                    function = tc["function"]
                    arguments = function.get("arguments") or "{}"
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": function["name"],
                        "input": arguments,
                    })
                wire.append({"role": "assistant", "content": blocks})
                continue
            if role == "user":
                wire.append({"role": "user", "content": msg.get("content") or ""})
        return wire

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

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._base_url}/messages",
                json=body,
                headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    if response.status_code in (429, 529) or response.status_code >= 500:
                        raise RetryableLLMError(
                            f"Stream HTTP {response.status_code}",
                            retry_after=_retry_after_seconds(response.headers.get("retry-after")),
                        )
                    body_bytes = await response.aread()
                    raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")

                # The 'event:' and 'data:' lines are separate SSE fields.
                # Parse only data payloads, which carry their own 'type'.
                tool_blocks: dict[int, dict] = {}
                saw_message_stop = False
                stop_reason: str | None = None
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    event_type = data.get("type")

                    if event_type == "message_start":
                        usage = data.get("message", {}).get("usage", {})
                        yield LLMStreamChunk(type="usage", content=json.dumps({
                            "input": usage.get("input_tokens", 0),
                        }))
                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            index = data["index"]
                            tool_blocks[index] = {
                                "id": block["id"],
                                "name": block["name"],
                                "input": block.get("input", {}),
                                "fragments": [],
                            }
                            yield LLMStreamChunk(
                                type="tool_call_start",
                                content=json.dumps({"id": block["id"], "name": block["name"]}),
                            )
                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield LLMStreamChunk(type="text_delta", content=delta.get("text", ""))
                        elif delta.get("type") == "input_json_delta":
                            index = data["index"]
                            if index not in tool_blocks:
                                raise FatalLLMError("Received tool input fragment without tool_use start")
                            fragment = delta.get("partial_json", "")
                            tool_blocks[index]["fragments"].append(fragment)
                            yield LLMStreamChunk(type="tool_call_delta", content=fragment)
                    elif event_type == "content_block_stop":
                        index = data["index"]
                        if index in tool_blocks:
                            block = tool_blocks.pop(index)
                            raw = "".join(block["fragments"])
                            try:
                                args = json.loads(raw) if raw else block["input"]
                            except json.JSONDecodeError as exc:
                                raise FatalLLMError(f"Invalid streamed tool arguments: {exc}") from exc
                            if not isinstance(args, dict):
                                raise FatalLLMError("Streamed tool arguments must be a JSON object")
                            yield LLMStreamChunk(
                                type="tool_call_end",
                                tool_call=ToolCallRequest(id=block["id"], name=block["name"], arguments=args),
                            )
                    elif event_type == "message_delta":
                        stop_reason = data.get("delta", {}).get("stop_reason") or stop_reason
                        if data.get("usage") is not None:
                            yield LLMStreamChunk(
                                type="usage", content=json.dumps(data["usage"]),
                            )
                        if stop_reason in ("max_tokens", "pause_turn"):
                            # Tool blocks may already have been yielded, but
                            # AgentLoop must never execute them on incomplete output.
                            raise FatalLLMError(
                                f"Anthropic stream stopped without completion: {stop_reason}"
                            )
                    elif event_type == "message_stop":
                        saw_message_stop = True
                    elif event_type == "error":
                        raise FatalLLMError(f"Anthropic stream error: {data.get('error', {}).get('type', 'unknown')}")
                if tool_blocks:
                    raise FatalLLMError("Anthropic stream ended with incomplete tool calls")
                if not saw_message_stop:
                    raise FatalLLMError("Anthropic stream ended without message_stop")
                if stop_reason is not None:
                    yield LLMStreamChunk(type="finish", content=stop_reason)


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

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    if response.status_code in (429, 529) or response.status_code >= 500:
                        raise RetryableLLMError(
                            f"Stream HTTP {response.status_code}",
                            retry_after=_retry_after_seconds(response.headers.get("retry-after")),
                        )
                    body_bytes = await response.aread()
                    raise FatalLLMError(f"Stream failed: {response.status_code} {body_bytes}")

                tool_buffers: dict[int, dict] = {}
                finished = False

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError as exc:
                        raise FatalLLMError("Invalid SSE JSON response") from exc

                    # OpenAI usage-only stream chunk has choices: [].
                    choices = data.get("choices") or []
                    if not choices:
                        if data.get("usage") is not None:
                            yield LLMStreamChunk(type="usage", content=json.dumps(data["usage"]))
                        continue

                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield LLMStreamChunk(type="text_delta", content=delta["content"])

                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        if idx not in tool_buffers:
                            tool_buffers[idx] = {"id": "", "name": "", "arguments": ""}
                        buf = tool_buffers[idx]
                        if tc.get("id"):
                            buf["id"] = tc["id"]
                        func = tc.get("function") or {}
                        if func.get("name"):
                            buf["name"] += func["name"]
                            yield LLMStreamChunk(
                                type="tool_call_start",
                                content=json.dumps({"id": buf["id"], "name": buf["name"]}),
                            )
                        if func.get("arguments") is not None:
                            buf["arguments"] += func["arguments"]

                    finish = choice.get("finish_reason")
                    if finish is not None:
                        finished = True
                        if finish in ("length", "content_filter"):
                            # Partial tool JSON or a truncated answer is not a final result.
                            raise FatalLLMError(f"Stream ended without a complete answer: {finish}")
                        if finish in ("tool_calls", "stop"):
                            for idx in sorted(tool_buffers):
                                buf = tool_buffers[idx]
                                if not buf["name"]:
                                    raise FatalLLMError("Streamed tool call has no function name")
                                try:
                                    arguments = json.loads(buf["arguments"]) if buf["arguments"].strip() else {}
                                except json.JSONDecodeError as exc:
                                    raise FatalLLMError(f"Invalid streamed tool arguments: {exc}") from exc
                                if not isinstance(arguments, dict):
                                    raise FatalLLMError("Streamed tool arguments must be a JSON object")
                                yield LLMStreamChunk(
                                    type="tool_call_end",
                                    tool_call=ToolCallRequest(
                                        id=buf["id"] or f"call_{idx}",
                                        name=buf["name"],
                                        arguments=arguments,
                                    ),
                                )
                            tool_buffers.clear()
                        yield LLMStreamChunk(type="finish", content=finish)
                if tool_buffers or not finished:
                    raise FatalLLMError("Stream ended before a complete finish reason")
