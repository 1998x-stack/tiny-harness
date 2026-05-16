# tiny-harness MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete tiny-harness MVP — a minimal Python package (~1,380 lines) that wraps an LLM into an AI agent with tools, conversation loop, streaming events, and a CLI session.

**Architecture:** Package `tiny_harness/` with 13 files organized by responsibility. Dependencies flow down: `cli.py` → `_core.py` → `_loop.py` → `_llm.py` + `_tools.py`. No cycles. Each module ≤300 lines. TDD: write failing test first, then implement, then commit.

**Tech Stack:** Python 3.11+, `httpx` (async HTTP), `pytest` + `pytest-asyncio` (testing). All other logic (SSE parsing, JSON Schema validator, CLI) is in-package.

**References:** `docs/superpowers/specs/2026-05-16-tiny-harness-mvp.md`, `CONTEXT.md`, `docs/adr/0001-0003`

---

## File Map

| File | Responsibility | ~Lines |
|---|---|---|
| `tiny_harness/__init__.py` | Public exports: Agent, Prompt, Config, ToolDef | 5 |
| `tiny_harness/_config.py` | AgentConfig, Prompt dataclasses | 60 |
| `tiny_harness/_events.py` | StreamEvent, EventBus | 40 |
| `tiny_harness/_guard.py` | FilesystemGuard — path resolution + boundary checks | 80 |
| `tiny_harness/_llm.py` | LLMProvider ABC, AnthropicProvider, response types, retry | 180 |
| `tiny_harness/_messages.py` | MessageManager, TokenBudget | 150 |
| `tiny_harness/_tools.py` | ToolDef, Tool, ToolRegistry, ToolExecutor, minimal validator | 180 |
| `tiny_harness/_loop.py` | AgentLoop, ErrorBudget, LoopDetector | 130 |
| `tiny_harness/_core.py` | Agent class — orchestrator | 150 |
| `tiny_harness/tools/__init__.py` | Empty init | 0 |
| `tiny_harness/tools/files.py` | 7 file tool handlers (read_file, write_file, etc.) | 220 |
| `tiny_harness/skills/__init__.py` | Empty init | 0 |
| `tiny_harness/skills/files.py` | register(agent) → file tools + prompt section | 60 |
| `tiny_harness/cli.py` | CLI entry point — session REPL + one-shot mode | 150 |
| **Total** | | **~1,405** |

---

## Phase 1: Config, Events, Path Guard (P1)

### Task 1: AgentConfig, Prompt dataclasses

**Files:**
- Create: `tiny_harness/_config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for AgentConfig**

```python
# tests/test_config.py
import pytest
from tiny_harness._config import AgentConfig, Prompt


def test_agentconfig_defaults():
    config = AgentConfig(model="claude-test", api_key="sk-test", workspace="/tmp")
    assert config.model == "claude-test"
    assert config.api_key == "sk-test"
    assert config.workspace == "/tmp"
    assert config.max_iterations == 25
    assert config.max_errors == 10
    assert config.max_consecutive_errors == 3
    assert config.timeout_ms == 30_000
    assert config.max_tool_result_chars == 50_000


def test_prompt_append_and_to_string():
    prompt = Prompt("You are a helpful assistant.")
    prompt.append("## Tools\nUse tools when needed.")
    prompt.append("## Rules\nBe concise.")
    result = prompt.to_string()
    assert "You are a helpful assistant." in result
    assert "## Tools" in result
    assert "## Rules" in result
    # Sections separated by double newline
    assert "\n\n" in result
```

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tiny_harness._config'`

- [ ] **Step 2: Create package directories and implement**

```bash
mkdir -p tiny_harness/tools tiny_harness/skills tests
touch tiny_harness/__init__.py tiny_harness/tools/__init__.py tiny_harness/skills/__init__.py
touch tests/__init__.py
```

```python
# tiny_harness/_config.py
from dataclasses import dataclass


@dataclass
class AgentConfig:
    model: str
    api_key: str
    workspace: str
    max_iterations: int = 25
    max_errors: int = 10
    max_consecutive_errors: int = 3
    timeout_ms: int = 30_000
    max_tool_result_chars: int = 50_000


class Prompt:
    def __init__(self, base: str):
        self._sections: list[str] = [base]

    def append(self, section: str) -> None:
        self._sections.append(section)

    def to_string(self) -> str:
        return "\n\n".join(self._sections)
```

Run: `pytest tests/test_config.py -v`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/__init__.py tiny_harness/tools/__init__.py tiny_harness/skills/__init__.py tests/__init__.py tiny_harness/_config.py tests/test_config.py
git commit -m "feat: add AgentConfig and Prompt dataclasses"
```

---

### Task 2: StreamEvent, EventBus

**Files:**
- Create: `tiny_harness/_events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_events.py
import pytest
from tiny_harness._events import StreamEvent, EventBus


def test_stream_event_creation():
    event = StreamEvent(type="text_delta", content="hello")
    assert event.type == "text_delta"
    assert event.content == "hello"
    assert event.tool_name is None

    tool_event = StreamEvent(type="tool_start", tool_name="read_file", duration_ms=12)
    assert tool_event.tool_name == "read_file"
    assert tool_event.duration_ms == 12


def test_stream_event_is_frozen():
    event = StreamEvent(type="text_delta", content="hello")
    with pytest.raises(Exception):
        event.content = "changed"


@pytest.mark.asyncio
async def test_eventbus_emit_and_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: StreamEvent):
        received.append(event)

    bus.subscribe(handler)
    event = StreamEvent(type="text_delta", content="test")
    await bus.emit(event)

    assert len(received) == 1
    assert received[0].content == "test"
```

Run: `pytest tests/test_events.py -v`
Expected: FAIL — module not found

- [ ] **Step 2: Implement**

```python
# tiny_harness/_events.py
from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    type: str
    content: str | None = None
    tool_name: str | None = None
    duration_ms: int | None = None
    num: int | None = None
    max: int | None = None
    message: str | None = None


class EventBus:
    def __init__(self):
        self._handlers: list[Callable[[StreamEvent], Awaitable[Any]]] = []

    def subscribe(self, handler: Callable[[StreamEvent], Awaitable[Any]]) -> None:
        self._handlers.append(handler)

    async def emit(self, event: StreamEvent) -> None:
        for handler in self._handlers:
            await handler(event)
```

Run: `pytest tests/test_events.py -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_events.py tests/test_events.py
git commit -m "feat: add StreamEvent and EventBus"
```

---

### Task 3: FilesystemGuard

**Files:**
- Create: `tiny_harness/_guard.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_guard.py
import os
import pytest
import tempfile
from tiny_harness._guard import FilesystemGuard, PathAccessError


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        # Create a file inside workspace
        test_file = os.path.join(tmp, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")
        yield tmp


def test_guard_allows_file_inside_workspace(workspace):
    guard = FilesystemGuard(workspace)
    test_file = os.path.join(workspace, "test.txt")
    result = guard.guard(test_file, "read")
    assert os.path.realpath(result) == os.path.realpath(test_file)


def test_guard_rejects_file_outside_workspace(workspace):
    guard = FilesystemGuard(workspace)
    outside = "/tmp/outside_file.txt"
    with pytest.raises(PathAccessError, match="outside allowed"):
        guard.guard(outside, "read")


def test_guard_resolves_relative_paths(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    guard = FilesystemGuard(workspace)
    result = guard.guard("test.txt", "read")
    assert os.path.realpath(result) == os.path.realpath(os.path.join(workspace, "test.txt"))


def test_guard_resolves_dot_dot_traversal(workspace):
    guard = FilesystemGuard(workspace)
    path = os.path.join(workspace, "..", "..", "etc", "passwd")
    with pytest.raises(PathAccessError):
        guard.guard(path, "read")


def test_guard_rejects_null_byte(workspace):
    guard = FilesystemGuard(workspace)
    with pytest.raises(PathAccessError, match="null byte"):
        guard.resolve("test.txt\x00extra")
```

Run: `pytest tests/test_guard.py -v`
Expected: FAIL — module not found

- [ ] **Step 2: Implement**

```python
# tiny_harness/_guard.py
import os


class PathAccessError(Exception):
    """Raised when a path is outside allowed workspace boundaries."""
    pass


class FilesystemGuard:
    def __init__(self, workspace: str):
        self._workspace = os.path.realpath(workspace)

    def resolve(self, path: str) -> str:
        if "\x00" in path:
            raise PathAccessError(f"Path contains null byte: {path!r}")
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(self._workspace, expanded)
        try:
            return os.path.realpath(expanded)
        except OSError as e:
            raise PathAccessError(f"Cannot resolve path: {e}")

    def guard(self, path: str, operation: str = "read") -> str:
        resolved = self.resolve(path)
        if not (resolved == self._workspace or resolved.startswith(self._workspace + os.sep)):
            raise PathAccessError(
                f"Access denied: '{path}' (resolved: '{resolved}') "
                f"is outside allowed workspace."
            )
        return resolved
```

Run: `pytest tests/test_guard.py -v`
Expected: 5 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_guard.py tests/test_guard.py
git commit -m "feat: add FilesystemGuard with workspace boundary enforcement"
```

---

## Phase 2: LLM Provider (P2)

### Task 4: LLMProvider types (LLMResponse, ToolCallRequest, TokenUsage, LLMStreamChunk)

**Files:**
- Create: `tiny_harness/_llm.py` (types only)
- Test: `tests/test_llm_types.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm_types.py
from tiny_harness._llm import (
    LLMResponse, ToolCallRequest, TokenUsage, LLMStreamChunk
)


def test_llm_response_final_when_no_tool_calls():
    response = LLMResponse(
        text="Hello!",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop"
    )
    assert response.is_final() is True


def test_llm_response_not_final_when_has_tool_calls():
    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    response = LLMResponse(
        text=None,
        tool_calls=[tc],
        usage=TokenUsage(input_tokens=20, output_tokens=15),
        finish_reason="tool_calls"
    )
    assert response.is_final() is False


def test_tool_call_request_from_dict():
    tc = ToolCallRequest(id="tc1", name="search", arguments={"query": "TODO"})
    assert tc.id == "tc1"
    assert tc.name == "search"
    assert tc.arguments["query"] == "TODO"


def test_llm_stream_chunk_text_delta():
    chunk = LLMStreamChunk(type="text_delta", content="Hello")
    assert chunk.type == "text_delta"
    assert chunk.content == "Hello"
    assert chunk.tool_call is None


def test_token_usage_defaults():
    usage = TokenUsage(input_tokens=10, output_tokens=5)
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
```

Run: `pytest tests/test_llm_types.py -v`
Expected: FAIL — module not found

- [ ] **Step 2: Implement types only**

```python
# tiny_harness/_llm.py
from dataclasses import dataclass, field
from collections.abc import AsyncIterator
from abc import ABC, abstractmethod


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
```

Run: `pytest tests/test_llm_types.py -v`
Expected: 5 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_llm.py tests/test_llm_types.py
git commit -m "feat: add LLMProvider ABC and response types"
```

---

### Task 5: AnthropicProvider with streaming, parsing, retry

**Files:**
- Modify: `tiny_harness/_llm.py` (add AnthropicProvider)
- Test: `tests/test_llm_provider.py`

- [ ] **Step 1: Write unit tests for AnthropicProvider message conversion**

```python
# tests/test_llm_provider.py
import pytest
from tiny_harness._llm import AnthropicProvider


def test_convert_messages_extracts_system():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
    result = provider._convert_messages(messages)
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"


def test_extract_system_returns_system_content():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    system = provider._extract_system(messages)
    assert system == "You are helpful."


def test_extract_system_returns_empty_when_no_system():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    messages = [{"role": "user", "content": "Hello"}]
    system = provider._extract_system(messages)
    assert system == ""


def test_convert_tools_to_anthropic_format():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    tools = [
        {"name": "read_file", "description": "Read a file", "input_schema": {"type": "object", "properties": {}}}
    ]
    result = provider._convert_tools(tools)
    assert len(result) == 1
    assert result[0]["name"] == "read_file"
    assert result[0]["description"] == "Read a file"
    assert "input_schema" in result[0]
```

Run: `pytest tests/test_llm_provider.py -v`
Expected: FAIL — AnthropicProvider not defined

- [ ] **Step 2: Add AnthropicProvider class (conversion methods only)**

```python
# Add to tiny_harness/_llm.py (after the types and ABC)

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

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
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in tools
        ]

    async def generate(self, messages, tools=None) -> LLMResponse:
        raise NotImplementedError

    async def generate_stream(self, messages, tools=None):
        raise NotImplementedError
```

Run: `pytest tests/test_llm_provider.py -v`
Expected: 4 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_llm.py tests/test_llm_provider.py
git commit -m "feat: add AnthropicProvider with message/tool conversion"
```

- [ ] **Step 4: Write test for Anthropic content block parsing**

```python
# Add to tests/test_llm_provider.py

def test_parse_response_with_text_and_tool_calls():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    # Simulate Anthropic response object with content blocks
    class FakeBlock:
        def __init__(self, block_type, text="", name="", input_data=None, block_id=""):
            self.type = block_type
            self.text = text
            self.name = name
            self.input = input_data or {}
            self.id = block_id

    class FakeUsage:
        input_tokens = 100
        output_tokens = 50

    class FakeResponse:
        content = [
            FakeBlock("text", text="Let me read that file."),
            FakeBlock("tool_use", name="read_file", input_data={"path": "/tmp/x"}, block_id="toolu_001"),
        ]
        usage = FakeUsage()
        model = "claude-test"
        stop_reason = "tool_use"

    result = provider._parse_response(FakeResponse())
    assert result.text == "Let me read that file."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "/tmp/x"}
    assert result.tool_calls[0].id == "toolu_001"
    assert result.usage.input_tokens == 100
    assert result.is_final() is False


def test_parse_response_with_text_only():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    class FakeBlock:
        def __init__(self, block_type, text=""):
            self.type = block_type
            self.text = text
    class FakeUsage:
        input_tokens = 20
        output_tokens = 10
    class FakeResponse:
        content = [FakeBlock("text", text="Hello, world!")]
        usage = FakeUsage()
        model = "claude-test"
        stop_reason = "end_turn"

    result = provider._parse_response(FakeResponse())
    assert result.text == "Hello, world!"
    assert len(result.tool_calls) == 0
    assert result.is_final() is True
```

- [ ] **Step 5: Implement `_parse_response`**

```python
# Add _parse_response method to AnthropicProvider
def _parse_response(self, response) -> LLMResponse:
    text_parts = []
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallRequest(
                id=block.id,
                name=block.name,
                arguments=block.input,
            ))

    return LLMResponse(
        text="".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        usage=TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        ),
        finish_reason=response.stop_reason or "stop",
    )
```

Run: `pytest tests/test_llm_provider.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add tiny_harness/_llm.py tests/test_llm_provider.py
git commit -m "feat: add Anthropic response parsing (text + tool_use blocks)"
```

- [ ] **Step 7: Write test for SSE stream parsing**

```python
# Add to tests/test_llm_provider.py
import json

def test_parse_sse_event_message_start():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    line = "event: message_start"
    data = json.dumps({"message": {"usage": {"input_tokens": 10}}})
    # SSE parsing is tested structurally; actual HTTP streaming in integration tests
    assert provider._parse_sse_line("event: message_start") == ("message_start", None)
    assert provider._parse_sse_line(f"data: {data}") == ("data", json.loads(data))


def test_parse_sse_content_block_start_tool_use():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    data = json.dumps({
        "index": 0,
        "content_block": {"type": "tool_use", "id": "toolu_001", "name": "read_file"}
    })
    event_type, parsed = provider._parse_sse_line(f"data: {data}")
    assert event_type == "data"
    assert parsed["content_block"]["name"] == "read_file"
```

- [ ] **Step 8: Implement SSE parsing helpers**

```python
# Add to AnthropicProvider
def _parse_sse_line(self, line: str) -> tuple[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("event: "):
        return ("event", line[7:])
    if line.startswith("data: "):
        return ("data", json.loads(line[5:]))
    return ("unknown", line)
```

Run: `pytest tests/test_llm_provider.py -v`
Expected: 8 PASS

- [ ] **Step 9: Commit**

```bash
git add tiny_harness/_llm.py tests/test_llm_provider.py
git commit -m "feat: add SSE line parsing helpers"
```

- [ ] **Step 10: Write test for retry config**

```python
# Add to tests/test_llm_provider.py
from tiny_harness._llm import LLMRetryConfig

def test_retry_config_defaults():
    config = LLMRetryConfig()
    assert config.max_retries == 3
    assert config.base_delay == 1.0
    assert config.max_delay == 60.0
    assert config.backoff_factor == 2.0
```

- [ ] **Step 11: Add LLMRetryConfig and AnthropicProvider.generate with httpx (full implementation)**

```python
# Add to tiny_harness/_llm.py

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


# Full AnthropicProvider implementation with generate, generate_stream, retry
class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, retry_config: LLMRetryConfig | None = None):
        self._api_key = api_key
        self._model = model
        self._retry_config = retry_config or LLMRetryConfig()

    # ... (previous methods: _convert_messages, _extract_system, _convert_tools, _parse_response, _parse_sse_line)

    async def generate(self, messages, tools=None) -> LLMResponse:
        import httpx, asyncio, random, time

        system = self._extract_system(messages)
        converted = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)

        body = {
            "model": self._model,
            "max_tokens": 16384,
            "messages": converted,
            "stream": False,
        }
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
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                if resp.status_code == 200:
                    # Build a response-like object for _parse_response
                    data = resp.json()
                    return self._parse_response(_ResponseAdapter(data))

                if resp.status_code in (429, 529) or resp.status_code >= 500:
                    raise RetryableLLMError(f"Status {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise FatalLLMError(f"Auth failed: {resp.status_code}")
                raise FatalLLMError(f"API error: {resp.status_code}")

            except (RetryableLLMError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt == self._retry_config.max_retries:
                    raise FatalLLMError(f"All retries exhausted: {e}")
                delay = min(
                    self._retry_config.base_delay * (self._retry_config.backoff_factor ** attempt),
                    self._retry_config.max_delay,
                )
                jitter = random.uniform(0, delay * 0.5)
                await asyncio.sleep(delay + jitter)

        raise FatalLLMError(f"All retries exhausted: {last_error}")

    async def generate_stream(self, messages, tools=None):
        # Full SSE streaming implementation using httpx
        import httpx

        system = self._extract_system(messages)
        converted = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools)

        body = {
            "model": self._model,
            "max_tokens": 16384,
            "messages": converted,
            "stream": True,
        }
        if system:
            body["system"] = system
        if converted_tools:
            body["tools"] = converted_tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=body,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise FatalLLMError(f"Stream failed: {response.status_code} {body}")

                current_event = None
                current_data = {}

                async for line in response.aiter_lines():
                    parsed = self._parse_sse_line(line)
                    if parsed is None:
                        continue
                    event_type, value = parsed

                    if event_type == "event":
                        current_event = value
                    elif event_type == "data":
                        if current_event == "message_start":
                            yield LLMStreamChunk(type="usage", content=json.dumps({
                                "input": value.get("message", {}).get("usage", {}).get("input_tokens", 0)
                            }))
                        elif current_event == "content_block_start":
                            block = value.get("content_block", {})
                            if block.get("type") == "tool_use":
                                yield LLMStreamChunk(
                                    type="tool_call_start",
                                    content=json.dumps({"id": block["id"], "name": block["name"]})
                                )
                        elif current_event == "content_block_delta":
                            delta = value.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield LLMStreamChunk(type="text_delta", content=delta.get("text", ""))
                            elif delta.get("type") == "input_json_delta":
                                yield LLMStreamChunk(
                                    type="tool_call_delta",
                                    content=delta.get("partial_json", "")
                                )
                        elif current_event == "content_block_stop":
                            yield LLMStreamChunk(type="tool_call_end")

                    current_event = None
                    current_data = {}


class _ResponseAdapter:
    """Adapts httpx JSON response to match Anthropic SDK response object shape."""
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
```

Run: `pytest tests/test_llm_provider.py tests/test_llm_types.py -v`
Expected: 9 PASS

- [ ] **Step 12: Commit**

```bash
git add tiny_harness/_llm.py tests/test_llm_provider.py
git commit -m "feat: add AnthropicProvider full implementation with SSE streaming and retry"
```

---

## Phase 3: Message Manager (P3)

### Task 6: MessageManager with token counting

**Files:**
- Create: `tiny_harness/_messages.py`
- Test: `tests/test_messages.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_messages.py
import pytest
from tiny_harness._config import Prompt
from tiny_harness._messages import MessageManager, TokenStatus


@pytest.fixture
def prompt():
    return Prompt("You are a helpful assistant.")


def test_initial_messages_have_system(prompt):
    mgr = MessageManager(prompt)
    msgs = mgr.to_list()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
    assert "You are a helpful assistant." in msgs[0]["content"]


def test_add_user_message(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Hello")
    msgs = mgr.to_list()
    assert len(msgs) == 2
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "Hello"


def test_add_assistant_with_text(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Hi")
    mgr.add_assistant(text="Hello!", tool_calls=None)
    msgs = mgr.to_list()
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["content"] == "Hello!"


def test_add_assistant_with_tool_calls(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Read file")
    from tiny_harness._llm import ToolCallRequest
    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    mgr.add_assistant(text=None, tool_calls=[tc])
    msgs = mgr.to_list()
    assert msgs[2]["role"] == "assistant"
    assert "tool_calls" in msgs[2]
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "read_file"


def test_add_tool_result(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Read file")
    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    mgr.add_assistant(text=None, tool_calls=[tc])
    mgr.add_tool_result(tool_call_id="tc1", content="file content here")
    msgs = mgr.to_list()
    assert msgs[3]["role"] == "tool"
    assert msgs[3]["tool_call_id"] == "tc1"
    assert msgs[3]["content"] == "file content here"


def test_add_system_notice(prompt):
    mgr = MessageManager(prompt)
    mgr.add_system_notice("You have 3 iterations left.")
    msgs = mgr.to_list()
    assert msgs[1]["role"] == "user"
    assert "[System Notice]" in msgs[1]["content"]


def test_estimate_tokens_is_positive(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Hello world, this is a test message with some content.")
    tokens = mgr.estimate_tokens()
    assert tokens > 0


def test_check_context_ok(prompt):
    mgr = MessageManager(prompt)
    status = mgr.check_context()
    assert status == TokenStatus.OK


def test_clear_resets_conversation_keeps_system(prompt):
    mgr = MessageManager(prompt)
    mgr.add_user("Hello")
    mgr.add_assistant(text="Hi!", tool_calls=None)
    mgr.clear()
    msgs = mgr.to_list()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
```

- [ ] **Step 2: Implement MessageManager and TokenStatus**

```python
# tiny_harness/_messages.py
import json
from enum import Enum, auto
from tiny_harness._config import Prompt
from tiny_harness._llm import ToolCallRequest


class TokenStatus(Enum):
    OK = auto()
    NEAR_CAPACITY = auto()
    OVER_CAPACITY = auto()


class TokenBudget:
    def __init__(self, max_tokens: int = 200_000, warn_threshold: float = 0.8):
        self.max_tokens = max_tokens
        self.warn_threshold = warn_threshold

    def check(self, messages: list[dict]) -> TokenStatus:
        used = sum(len(json.dumps(m)) // 4 for m in messages)
        if used > self.max_tokens:
            return TokenStatus.OVER_CAPACITY
        if used > self.max_tokens * self.warn_threshold:
            return TokenStatus.NEAR_CAPACITY
        return TokenStatus.OK


class MessageManager:
    def __init__(self, prompt: Prompt):
        self.messages: list[dict] = [
            {"role": "system", "content": prompt.to_string()}
        ]
        self._token_budget = TokenBudget()

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, text: str | None, tool_calls: list[ToolCallRequest] | None = None) -> None:
        msg: dict = {"role": "assistant"}
        if text:
            msg["content"] = text
        else:
            msg["content"] = None
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def add_system_notice(self, notice: str) -> None:
        self.messages.append({
            "role": "user",
            "content": f"[System Notice] {notice}",
        })

    def to_list(self) -> list[dict]:
        return self.messages

    def estimate_tokens(self) -> int:
        return sum(len(json.dumps(m)) // 4 for m in self.messages)

    def check_context(self) -> TokenStatus:
        return self._token_budget.check(self.messages)

    def clear(self) -> None:
        system = self.messages[0]
        self.messages = [system]
```

Run: `pytest tests/test_messages.py -v`
Expected: 9 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_messages.py tests/test_messages.py
git commit -m "feat: add MessageManager with token counting and context checks"
```

---

## Phase 4: Tool System (P4)

### Task 7: ToolDef, Tool, ToolRegistry

**Files:**
- Create: `tiny_harness/_tools.py` (types + registry)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests for registry**

```python
# tests/test_tools.py
import pytest
from tiny_harness._tools import ToolDef, Tool, ToolRegistry


@pytest.fixture
def sample_tool():
    return Tool(
        definition=ToolDef(
            name="read_file",
            description="Read a file from disk.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        handler=lambda path: f"content of {path}",
    )


def test_register_and_get_tool(sample_tool):
    registry = ToolRegistry()
    registry.register(sample_tool)
    retrieved = registry.get("read_file")
    assert retrieved is sample_tool


def test_get_nonexistent_tool():
    registry = ToolRegistry()
    assert registry.get("nonexistent") is None


def test_register_from_def():
    registry = ToolRegistry()
    tool_def = ToolDef(
        name="greet",
        description="Say hello",
        parameters={"type": "object", "properties": {}},
    )
    async def greet(args):
        return "Hello!"

    registry.register_from_def(tool_def, greet)
    tool = registry.get("greet")
    assert tool.definition.name == "greet"
    assert tool.definition.description == "Say hello"


def test_get_definitions(sample_tool):
    registry = ToolRegistry()
    registry.register(sample_tool)
    defs = registry.get_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "read_file"
    assert "description" in defs[0]
    assert "input_schema" in defs[0]


def test_names(sample_tool):
    registry = ToolRegistry()
    registry.register(sample_tool)
    assert "read_file" in registry.names()
```

- [ ] **Step 2: Implement ToolDef, Tool, ToolRegistry**

```python
# tiny_harness/_tools.py
from dataclasses import dataclass, field
from collections.abc import Callable


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    risk_level: str = "read_only"


@dataclass
class Tool:
    definition: ToolDef
    handler: Callable


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def register_from_def(self, def_: ToolDef, handler: Callable) -> None:
        self.register(Tool(definition=def_, handler=handler))

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        return [
            {
                "name": t.definition.name,
                "description": t.definition.description,
                "input_schema": t.definition.parameters,
            }
            for t in self._tools.values()
        ]

    def names(self) -> list[str]:
        return list(self._tools.keys())
```

Run: `pytest tests/test_tools.py -v`
Expected: 5 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_tools.py tests/test_tools.py
git commit -m "feat: add ToolDef, Tool, and ToolRegistry"
```

---

### Task 8: ToolExecutor with minimal schema validator

**Files:**
- Modify: `tiny_harness/_tools.py` (add ToolExecutor + validator)
- Modify: `tests/test_tools.py` (add executor tests)

- [ ] **Step 1: Write failing tests for ToolExecutor**

```python
# Add to tests/test_tools.py
import asyncio
from tiny_harness._tools import ToolExecutor, ToolResult
from tiny_harness._guard import FilesystemGuard


@pytest.fixture
def executor():
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef(name="echo", description="Echo input", parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }),
        lambda message: message,
    )
    registry.register_from_def(
        ToolDef(name="failing", description="Always fails", parameters={
            "type": "object", "properties": {}
        }),
        lambda: (_ for _ in ()).throw(RuntimeError("always fails")),
    )
    guard = FilesystemGuard("/tmp")
    return ToolExecutor(registry, guard, timeout_ms=5000, max_output_chars=10000)


@pytest.mark.asyncio
async def test_execute_returns_success_result(executor):
    result = await executor.execute("echo", {"message": "hello"}, "tc1")
    assert result.success is True
    assert result.tool_call_id == "tc1"
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_execute_tool_not_found(executor):
    result = await executor.execute("nonexistent", {}, "tc1")
    assert result.success is False
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_execute_schema_validation_fails(executor):
    result = await executor.execute("echo", {}, "tc1")  # missing required 'message'
    assert result.success is False
    assert "message" in result.content.lower()


@pytest.mark.asyncio
async def test_execute_handler_exception_becomes_error_result(executor):
    result = await executor.execute("failing", {}, "tc1")
    assert result.success is False
    assert "always fails" in result.content
```

- [ ] **Step 2: Implement ToolExecutor and Result**

```python
# Add to tiny_harness/_tools.py
import json
import asyncio
from difflib import get_close_matches


@dataclass
class ToolResult:
    success: bool
    tool_call_id: str
    content: str

    @classmethod
    def ok(cls, call_id: str, content: str) -> "ToolResult":
        return cls(success=True, tool_call_id=call_id, content=content)

    @classmethod
    def error(cls, call_id: str, message: str) -> "ToolResult":
        return cls(success=False, tool_call_id=call_id, content=message)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, guard: FilesystemGuard | None,
                 timeout_ms: int = 30_000, max_output_chars: int = 50_000):
        self._registry = registry
        self._guard = guard
        self._timeout_ms = timeout_ms
        self._max_output_chars = max_output_chars

    async def execute(self, name: str, args: dict, call_id: str) -> ToolResult:
        # Stage 1: Lookup
        tool = self._registry.get(name)
        if tool is None:
            suggestions = get_close_matches(name, self._registry.names(), n=3, cutoff=0.6)
            msg = f"Tool '{name}' not found."
            if suggestions:
                msg += f" Did you mean: {', '.join(suggestions)}?"
            return ToolResult.error(call_id, msg)

        # Stage 2: Validate schema
        errors = validate_schema(tool.definition.parameters, args)
        if errors:
            return ToolResult.error(call_id, f"Invalid arguments for '{name}':\n" + "\n".join(f"  - {e}" for e in errors))

        # Stage 3: Guard (if applicable)
        if self._guard and tool.definition.risk_level != "safe":
            path = args.get("path") or args.get("source") or args.get("destination")
            if path:
                try:
                    operation = "delete" if tool.definition.risk_level == "destructive" else "write" if tool.definition.risk_level == "mutation" else "read"
                    self._guard.guard(path, operation)
                except Exception as e:
                    return ToolResult.error(call_id, str(e))

        # Stage 4: Execute with timeout
        try:
            if asyncio.iscoroutinefunction(tool.handler):
                raw = await asyncio.wait_for(
                    tool.handler(**args),
                    timeout=self._timeout_ms / 1000,
                )
            else:
                raw = tool.handler(**args)
        except asyncio.TimeoutError:
            return ToolResult.error(call_id, f"Tool '{name}' timed out after {self._timeout_ms/1000}s")
        except Exception as e:
            return ToolResult.error(call_id, f"Tool '{name}' failed: {e}")

        # Stage 5: Format
        formatted = self._format(raw)
        return ToolResult.ok(call_id, formatted)

    def _format(self, raw) -> str:
        if raw is None:
            return "Success."
        if isinstance(raw, str):
            result = raw
        elif isinstance(raw, (dict, list)):
            result = json.dumps(raw, indent=2)
        else:
            result = str(raw)
        if len(result) > self._max_output_chars:
            result = result[:self._max_output_chars] + (
                f"\n\n[... truncated at {self._max_output_chars} characters]"
            )
        return result


def validate_schema(schema: dict, args: dict) -> list[str]:
    errors = []
    schema_type = schema.get("type")
    if schema_type != "object":
        return errors

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for field in required:
        if field not in args:
            errors.append(f"'{field}' is required but was not provided")

    for key, value in args.items():
        if key in properties:
            prop = properties[key]
            expected_type = prop.get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"'{key}' should be a string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"'{key}' should be an integer, got {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                errors.append(f"'{key}' should be a number, got {type(value).__name__}")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"'{key}' should be a boolean, got {type(value).__name__}")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"'{key}' should be an array, got {type(value).__name__}")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"'{key}' should be an object, got {type(value).__name__}")
            if "enum" in prop and value not in prop["enum"]:
                errors.append(f"'{key}' must be one of {prop['enum']}, got {value!r}")

    return errors
```

Run: `pytest tests/test_tools.py -v`
Expected: 9 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_tools.py tests/test_tools.py
git commit -m "feat: add ToolExecutor with minimal schema validator and ToolResult"
```

---

## Phase 5: Agent Loop (P5)

### Task 9: ErrorBudget, LoopDetector, AgentLoop

**Files:**
- Create: `tiny_harness/_loop.py`
- Test: `tests/test_loop.py`

- [ ] **Step 1: Write failing tests for ErrorBudget**

```python
# tests/test_loop.py
import pytest
from tiny_harness._loop import ErrorBudget, LoopDetector


def test_error_budget_records_errors():
    budget = ErrorBudget(max_total=10, max_consecutive=3)
    assert budget.record_error() is True
    assert budget.record_error() is True


def test_error_budget_exhausted_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    assert budget.record_error() is True
    assert budget.record_error() is False  # 2 consecutive = exhausted


def test_error_budget_exhausted_total():
    budget = ErrorBudget(max_total=2, max_consecutive=10)
    assert budget.record_error() is True
    assert budget.record_error() is False  # 2 total = exhausted


def test_error_budget_success_resets_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    budget.record_error()
    budget.record_success()
    assert budget.record_error() is True
    assert budget.record_error() is False  # 2 in a row again


def test_loop_detector_rejects_repeated_calls():
    detector = LoopDetector(max_repeats=2)
    args = {"path": "/tmp/x"}
    assert detector.check("read_file", args) is True
    assert detector.check("read_file", args) is False  # same call twice


def test_loop_detector_allows_different_args():
    detector = LoopDetector(max_repeats=2)
    assert detector.check("read_file", {"path": "/tmp/a"}) is True
    assert detector.check("read_file", {"path": "/tmp/b"}) is True
```

- [ ] **Step 2: Implement ErrorBudget and LoopDetector**

```python
# tiny_harness/_loop.py
import json
from collections import deque


class ErrorBudget:
    def __init__(self, max_total: int = 10, max_consecutive: int = 3):
        self.max_total = max_total
        self.max_consecutive = max_consecutive
        self.total_errors = 0
        self.consecutive_errors = 0

    def record_error(self) -> bool:
        self.total_errors += 1
        self.consecutive_errors += 1
        return self.total_errors < self.max_total and self.consecutive_errors < self.max_consecutive

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def reset(self) -> None:
        self.total_errors = 0
        self.consecutive_errors = 0


class LoopDetector:
    def __init__(self, max_repeats: int = 3):
        self.max_repeats = max_repeats
        self._recent: deque[tuple[str, str]] = deque(maxlen=20)

    def check(self, tool_name: str, args: dict) -> bool:
        signature = (tool_name, json.dumps(args, sort_keys=True))
        self._recent.append(signature)
        count = sum(1 for s in self._recent if s == signature)
        return count < self.max_repeats

    def reset(self) -> None:
        self._recent.clear()
```

Run: `pytest tests/test_loop.py -v`
Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_loop.py tests/test_loop.py
git commit -m "feat: add ErrorBudget and LoopDetector"
```

---

### Task 10: AgentLoop state machine

**Files:**
- Modify: `tiny_harness/_loop.py` (add AgentLoop)
- Modify: `tests/test_loop.py` (add AgentLoop tests)

- [ ] **Step 1: Write test for AgentLoop with mocked LLM**

```python
# Add to tests/test_loop.py
import asyncio
import pytest
from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._messages import MessageManager
from tiny_harness._events import EventBus
from tiny_harness._tools import ToolDef, ToolRegistry, ToolExecutor, ToolResult
from tiny_harness._loop import AgentLoop


class FakeLLMProvider:
    """Returns pre-programmed responses for deterministic loop testing."""
    def __init__(self, responses: list):
        self.responses = responses
        self.idx = 0
        self.call_count = 0

    async def generate_stream(self, messages, tools=None):
        self.call_count += 1
        response = self.responses[min(self.idx, len(self.responses) - 1)]
        self.idx += 1

        # Yield text chunks
        if response[0]:
            for chunk in response[0]:
                from tiny_harness._llm import LLMStreamChunk
                yield LLMStreamChunk(type="text_delta", content=chunk)

        # Yield tool calls if any
        for tc in response[1]:
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="tool_call_end", tool_call=tc)

    async def generate(self, messages, tools=None):
        self.call_count += 1
        from tiny_harness._llm import LLMResponse, TokenUsage
        return LLMResponse(
            text="done",
            tool_calls=[],
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            finish_reason="stop"
        )


class FakeToolExecutor:
    def __init__(self, results: list[ToolResult]):
        self.results = results
        self.idx = 0
    async def execute(self, name, args, call_id):
        result = self.results[min(self.idx, len(self.results) - 1)]
        self.idx += 1
        return result


@pytest.mark.asyncio
async def test_loop_returns_final_answer():
    from tiny_harness._llm import ToolCallRequest
    config = AgentConfig(model="test", api_key="k", workspace="/tmp")
    prompt = Prompt("Be helpful.")
    messages = MessageManager(prompt)
    events = EventBus()

    # Response: text only, no tools → final answer
    fake_llm = FakeLLMProvider(responses=[
        (["Hello, world!"], []),  # (text_chunks, tool_calls)
    ])
    fake_tools = FakeToolExecutor(results=[])

    loop = AgentLoop(config, messages, fake_llm, fake_tools, events)
    result = await loop.run("Hi")
    assert "Hello, world!" in result
    assert fake_llm.call_count == 1


@pytest.mark.asyncio
async def test_loop_executes_tool_and_continues():
    from tiny_harness._llm import ToolCallRequest
    config = AgentConfig(model="test", api_key="k", workspace="/tmp")
    prompt = Prompt("Be helpful.")
    messages = MessageManager(prompt)
    events = EventBus()

    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    fake_llm = FakeLLMProvider(responses=[
        (["Let me read that."], [tc]),          # call tool
        (["File content is: hello"], []),       # final answer after tool result
    ])
    fake_tools = FakeToolExecutor(results=[
        ToolResult.ok("tc1", "content: hello"),
    ])

    loop = AgentLoop(config, messages, fake_llm, fake_tools, events)
    result = await loop.run("Read /tmp/x")
    assert "File content is: hello" in result
    assert fake_llm.call_count == 2
```

- [ ] **Step 2: Implement AgentLoop**

```python
# Add to tiny_harness/_loop.py
import json
from tiny_harness._config import AgentConfig
from tiny_harness._messages import MessageManager, TokenStatus
from tiny_harness._events import EventBus, StreamEvent
from tiny_harness._llm import LLMProvider, ToolCallRequest
from tiny_harness._tools import ToolExecutor, ToolResult


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        messages: MessageManager,
        llm: LLMProvider,
        tools: ToolExecutor,
        events: EventBus,
    ):
        self._config = config
        self._messages = messages
        self._llm = llm
        self._tools = tools
        self._events = events

    async def run(self, user_prompt: str) -> str:
        self._messages.add_user(user_prompt)
        collected_text: list[str] = []
        error_budget = ErrorBudget(
            max_total=self._config.max_errors,
            max_consecutive=self._config.max_consecutive_errors,
        )
        loop_detector = LoopDetector()

        for iteration in range(1, self._config.max_iterations + 1):
            # Emit iteration event
            token_estimate = self._messages.estimate_tokens()
            await self._events.emit(StreamEvent(
                type="iteration",
                num=iteration,
                max=self._config.max_iterations,
                content=f"{token_estimate // 1000}K",
            ))

            # Stream LLM response
            tool_calls: list[ToolCallRequest] = []
            try:
                async for chunk in self._llm.generate_stream(
                    self._messages.to_list(),
                    None,
                ):
                    if chunk.type == "text_delta" and chunk.content:
                        collected_text.append(chunk.content)
                        await self._events.emit(StreamEvent(
                            type="text_delta",
                            content=chunk.content,
                        ))
                    elif chunk.type == "tool_call_end" and chunk.tool_call:
                        tool_calls.append(chunk.tool_call)
                    elif chunk.type == "tool_call_delta":
                        pass  # Non-Anthropic providers may use this; we buffer
            except Exception as e:
                # Fatal LLM error — terminate
                await self._events.emit(StreamEvent(
                    type="error",
                    message=f"LLM error: {e}",
                ))
                return f"Agent stopped due to LLM error: {e}"

            # No tool calls = final answer
            if not tool_calls:
                return "".join(collected_text)

            # Add assistant message
            self._messages.add_assistant(
                text="".join(collected_text) if collected_text else None,
                tool_calls=tool_calls,
            )
            collected_text = []

            # Execute tools
            for tc in tool_calls:
                # Loop detection
                if not loop_detector.check(tc.name, tc.arguments):
                    result = ToolResult.error(
                        tc.id,
                        f"You've called '{tc.name}' with the same arguments "
                        f"{loop_detector.max_repeats} times. Try a different approach."
                    )
                else:
                    await self._events.emit(StreamEvent(
                        type="tool_start",
                        tool_name=tc.name,
                        content=json.dumps(tc.arguments),
                    ))
                    result = await self._tools.execute(tc.name, tc.arguments, tc.id)
                    await self._events.emit(StreamEvent(
                        type="tool_end",
                        tool_name=tc.name,
                        content=result.content[:100],
                    ))

                # Error budget
                if result.success:
                    error_budget.record_success()
                else:
                    if not error_budget.record_error():
                        return await self._degraded_finish(collected_text)

                self._messages.add_tool_result(result.tool_call_id, result.content)

            # Context warning
            status = self._messages.check_context()
            if status == TokenStatus.NEAR_CAPACITY:
                await self._events.emit(StreamEvent(
                    type="error",
                    message="Context near limit",
                ))

        # Max iterations reached
        return await self._degraded_finish(collected_text)

    async def _degraded_finish(self, collected_text: list[str]) -> str:
        self._messages.add_system_notice(
            "You've reached a safety limit. Please provide your best final answer "
            "based on what you know, without using any tools."
        )
        try:
            result = await self._llm.generate(
                self._messages.to_list(),
                tools=[],
            )
            return result.text or "".join(collected_text)
        except Exception:
            return "".join(collected_text) or "Agent stopped."
```

Run: `pytest tests/test_loop.py -v`
Expected: 8 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/_loop.py tests/test_loop.py
git commit -m "feat: add AgentLoop state machine with error budget and loop detection"
```

---

## Phase 6: Agent Core (P6)

### Task 11: Agent class + __init__.py

**Files:**
- Create: `tiny_harness/_core.py`
- Modify: `tiny_harness/__init__.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests for Agent**

```python
# tests/test_agent.py
import pytest
from tiny_harness import Agent, Prompt, Config, ToolDef


def test_agent_creation():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    assert agent is not None


def test_agent_tools_registry():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    assert len(agent.tools.names()) == 0


def test_agent_register_tool():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    def_ = ToolDef(name="echo", description="Echo", parameters={"type": "object", "properties": {}})
    agent.tools.register_from_def(def_, lambda: "echo")
    assert "echo" in agent.tools.names()


def test_agent_events():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    received = []
    async def handler(event):
        received.append(event)
    agent.events.subscribe(handler)
    assert agent.events is not None
```

- [ ] **Step 2: Create AgentConfig alias**

```python
# Add to tiny_harness/_config.py (at bottom, after existing classes)
# Re-export alias for user convenience
from tiny_harness._config import AgentConfig
```

Actually, let me use the correct approach — create a `Config` alias.

```python
# tiny_harness/__init__.py
from tiny_harness._config import AgentConfig as Config, Prompt
from tiny_harness._tools import ToolDef

__all__ = ["Agent", "Prompt", "Config", "ToolDef"]

# Agent imported at bottom to avoid circular import
```

- [ ] **Step 3: Implement Agent class**

```python
# tiny_harness/_core.py
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from collections.abc import AsyncIterator

from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._messages import MessageManager
from tiny_harness._llm import AnthropicProvider
from tiny_harness._tools import ToolRegistry, ToolExecutor
from tiny_harness._guard import FilesystemGuard
from tiny_harness._events import EventBus, StreamEvent
from tiny_harness._loop import AgentLoop


class Agent:
    def __init__(self, prompt: Prompt, config: AgentConfig):
        self._config = config
        self._prompt = prompt
        self._messages = MessageManager(prompt)
        self._llm_provider = AnthropicProvider(config.api_key, config.model)
        self._tool_registry = ToolRegistry()
        self._guard = FilesystemGuard(config.workspace)
        self._tool_executor = ToolExecutor(
            self._tool_registry,
            self._guard,
            config.timeout_ms,
            config.max_tool_result_chars,
        )
        self._event_bus = EventBus()
        self._loaded_skills: list[str] = []
        self._running = False

    @property
    def tools(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def events(self) -> EventBus:
        return self._event_bus

    def on(self, event_type: str, handler) -> None:
        async def filtered(event: StreamEvent):
            if event.type == event_type:
                await handler(event)
        self._event_bus.subscribe(filtered)

    def load_skill(self, skill_ref: str) -> None:
        if skill_ref in self._loaded_skills:
            return

        module = self._resolve_skill(skill_ref)
        if not hasattr(module, "register"):
            raise RuntimeError(f"Skill '{skill_ref}' has no register() function")

        module.register(self)
        self._loaded_skills.append(skill_ref)

    def _resolve_skill(self, ref: str) -> ModuleType:
        # Try "files" → tiny_harness.skills.files
        try:
            return importlib.import_module(f"tiny_harness.skills.{ref}")
        except ImportError:
            pass

        # Try direct import
        try:
            return importlib.import_module(ref)
        except ImportError:
            pass

        # Try file path
        path = Path(ref)
        if path.exists():
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        raise RuntimeError(f"Skill '{ref}' not found")

    async def run(self, prompt: str) -> str:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        try:
            loop = AgentLoop(
                self._config,
                self._messages,
                self._llm_provider,
                self._tool_executor,
                self._event_bus,
            )
            return await loop.run(prompt)
        finally:
            self._running = False

    async def run_stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        try:
            queue: list[StreamEvent] = []
            import asyncio
            done = asyncio.Event()

            async def collector(event: StreamEvent):
                queue.append(event)

            self._event_bus.subscribe(collector)
            try:
                loop = AgentLoop(
                    self._config,
                    self._messages,
                    self._llm_provider,
                    self._tool_executor,
                    self._event_bus,
                )
                task = asyncio.create_task(loop.run(prompt))
                last_yielded = 0
                while not task.done() or last_yielded < len(queue):
                    while last_yielded < len(queue):
                        yield queue[last_yielded]
                        last_yielded += 1
                    if not task.done():
                        await asyncio.sleep(0.01)
                await task  # re-raise exceptions
            finally:
                # Remove collector (simple approach: create new bus next time)
                pass
        finally:
            self._running = False

    def clear(self) -> None:
        self._messages.clear()
```

- [ ] **Step 4: Update __init__.py with Agent import**

```python
# tiny_harness/__init__.py
from tiny_harness._config import AgentConfig as Config, Prompt
from tiny_harness._tools import ToolDef
from tiny_harness._core import Agent

__all__ = ["Agent", "Prompt", "Config", "ToolDef"]
```

Run: `pytest tests/test_agent.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add tiny_harness/__init__.py tiny_harness/_core.py tests/test_agent.py
git commit -m "feat: add Agent class with skill loading, run/run_stream, clear"
```

---

## Phase 7: File Tools + Skills (P7)

### Task 12: File tool handlers (7 tools)

**Files:**
- Create: `tiny_harness/tools/files.py`
- Test: `tests/test_file_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_file_tools.py
import os
import tempfile
import pytest
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file,
)


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_write_and_read_file(tmpdir):
    path = os.path.join(tmpdir, "test.txt")
    result = write_file({"path": path, "content": "hello world"})
    assert "Created" in result or "Updated" in result
    content = read_file({"path": path})
    assert "hello world" in content


def test_list_directory(tmpdir):
    write_file({"path": os.path.join(tmpdir, "a.txt"), "content": "a"})
    write_file({"path": os.path.join(tmpdir, "b.txt"), "content": "b"})
    result = list_directory({"path": tmpdir})
    assert "a.txt" in result
    assert "b.txt" in result


def test_find_files(tmpdir):
    write_file({"path": os.path.join(tmpdir, "hello.py"), "content": "print('hi')"})
    write_file({"path": os.path.join(tmpdir, "readme.md"), "content": "# hi"})
    result = find_files({"pattern": "*.py", "path": tmpdir})
    assert "hello.py" in result


def test_delete_file(tmpdir):
    path = os.path.join(tmpdir, "to_delete.txt")
    write_file({"path": path, "content": "delete me"})
    result = delete_file({"path": path})
    assert "Deleted" in result or "deleted" in result.lower()
    assert not os.path.exists(path)


def test_create_directory(tmpdir):
    new_dir = os.path.join(tmpdir, "new_dir", "sub")
    result = create_directory({"path": new_dir})
    assert "Created" in result
    assert os.path.isdir(new_dir)


def test_move_file(tmpdir):
    src = os.path.join(tmpdir, "src.txt")
    dst = os.path.join(tmpdir, "dst.txt")
    write_file({"path": src, "content": "move me"})
    result = move_file({"source": src, "destination": dst})
    assert "Moved" in result or "moved" in result.lower()
    assert not os.path.exists(src)
    assert os.path.exists(dst)
```

- [ ] **Step 2: Implement all 7 file tool handlers**

```python
# tiny_harness/tools/files.py
import os
import glob
import shutil


def read_file(args: dict) -> str:
    path = args["path"]
    offset = args.get("offset", 1)
    limit = args.get("limit")
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."
    if os.path.isdir(path):
        return f"Error: '{path}' is a directory."
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    selected = lines[offset - 1 : (offset - 1 + limit) if limit else None]
    result = "".join(selected)
    header = f"[{path}] Lines {offset}-{offset + len(selected) - 1} of {total}\n"
    output = header + result
    if len(output) > 50_000:
        output = output[:50_000] + "\n\n[... truncated at 50,000 characters]"
    return output


def write_file(args: dict) -> str:
    path = args["path"]
    content = args["content"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    size = len(content.encode("utf-8"))
    action = "Updated" if existed else "Created"
    lines = content.count("\n") + 1
    return f"{action} '{path}' ({lines} lines, {_format_size(size)})"


def list_directory(args: dict) -> str:
    path = args.get("path", ".")
    pattern = args.get("pattern")
    recursive = args.get("recursive", False)
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory."
    entries = []
    if recursive:
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                full = os.path.join(root, name)
                if not pattern or _glob_match(name, pattern):
                    entries.append(_format_entry(full, os.path.relpath(full, path)))
    else:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if not pattern or _glob_match(name, pattern):
                entries.append(_format_entry(full, name))
    if not entries:
        return f"Directory '{path}' is empty."
    return f"[{path}] {len(entries)} items:\n" + "\n".join(entries)


def find_files(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    max_results = args.get("max_results", 200)
    matches = []
    search_path = os.path.join(path, pattern)
    for i, match in enumerate(glob.glob(search_path, recursive=True)):
        if i >= max_results:
            break
        matches.append(os.path.relpath(match, path))
    if not matches:
        return f"No files matching '{pattern}' found in '{path}'."
    return f"Found {len(matches)} files matching '{pattern}':\n" + "\n".join(f"  {m}" for m in matches)


def delete_file(args: dict) -> str:
    path = args["path"]
    if not os.path.exists(path):
        return f"Error: File '{path}' not found."
    os.remove(path)
    return f"Deleted '{path}'."


def create_directory(args: dict) -> str:
    path = args["path"]
    existed = os.path.isdir(path)
    os.makedirs(path, exist_ok=True)
    action = "Already exists" if existed else "Created"
    return f"{action} directory '{path}'."


def move_file(args: dict) -> str:
    src = args["source"]
    dst = args["destination"]
    if not os.path.exists(src):
        return f"Error: Source '{src}' not found."
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.move(src, dst)
    return f"Moved '{src}' → '{dst}'."


def _format_entry(full_path: str, name: str) -> str:
    is_dir = os.path.isdir(full_path)
    prefix = "D" if is_dir else "F"
    size = "" if is_dir else _format_size(os.path.getsize(full_path))
    return f"  [{prefix}] {name}{'  ' + size if size else ''}"


def _format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}" if unit != "B" else f"{size_bytes}B"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def _glob_match(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern)
```

Run: `pytest tests/test_file_tools.py -v`
Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/tools/files.py tests/test_file_tools.py
git commit -m "feat: add 7 file tool handlers (read, write, list, find, delete, mkdir, move)"
```

---

### Task 13: Skills (files skill)

**Files:**
- Create: `tiny_harness/skills/files.py`
- Test: `tests/test_skill_files.py`

- [ ] **Step 1: Write test for skill loading**

```python
# tests/test_skill_files.py
import os
import tempfile
import pytest
from tiny_harness import Agent, Prompt, Config


def test_load_files_skill_registers_tools():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.load_skill("files")
    names = agent.tools.names()
    assert "read_file" in names
    assert "write_file" in names
    assert "list_directory" in names
    assert "find_files" in names


def test_load_files_skill_appends_prompt():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    original = agent._prompt.to_string()
    agent.load_skill("files")
    updated = agent._prompt.to_string()
    assert len(updated) > len(original)
    assert "File Operations" in updated or "filesystem" in updated.lower()
```

- [ ] **Step 2: Implement files skill**

```python
# tiny_harness/skills/files.py
from tiny_harness.tools.files import (
    read_file, write_file, list_directory, find_files,
    delete_file, create_directory, move_file,
)
from tiny_harness._tools import ToolDef


FILES_PROMPT_SECTION = """
## File Operations

You have filesystem access through these tools:
- read_file(path, offset?, limit?): Read file contents. Use for examining files.
- write_file(path, content): Create or overwrite a file. Auto-creates parent dirs.
- list_directory(path?, pattern?, recursive?): List directory contents.
- find_files(pattern, path?): Find files by glob pattern.
- delete_file(path): Permanently delete a file. WARNING: irreversible.
- create_directory(path): Create a directory and any needed parents.
- move_file(source, destination): Move or rename a file/directory.

Guidelines:
1. Always verify writes by reading the file back
2. Use specific paths — don't guess file locations
3. For large files, use offset/limit to read sections
4. Never delete files without strong justification
5. Use find_files to discover files before reading them
"""


def register(agent) -> None:
    agent.tools.register_from_def(
        ToolDef(
            name="read_file",
            description="Read file contents from the filesystem. Use offset/limit for large files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "offset": {"type": "integer", "description": "Line number to start from (1-indexed). Default: 1."},
                    "limit": {"type": "integer", "description": "Max lines to read. Omit to read all."},
                },
                "required": ["path"],
            },
            risk_level="read_only",
        ),
        read_file,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="write_file",
            description="Create or overwrite a file. Auto-creates parent directories.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            risk_level="mutation",
        ),
        write_file,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path. Default: current directory."},
                    "pattern": {"type": "string", "description": "Glob pattern to filter (e.g. '*.py')."},
                    "recursive": {"type": "boolean", "description": "List recursively. Default: false."},
                },
            },
            risk_level="read_only",
        ),
        list_directory,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="find_files",
            description="Find files matching a glob pattern.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')."},
                    "path": {"type": "string", "description": "Search directory. Default: current directory."},
                    "max_results": {"type": "integer", "description": "Max results. Default: 200."},
                },
                "required": ["pattern"],
            },
            risk_level="read_only",
        ),
        find_files,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="delete_file",
            description="Permanently delete a file. WARNING: irreversible.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to delete."},
                },
                "required": ["path"],
            },
            risk_level="destructive",
        ),
        delete_file,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="create_directory",
            description="Create a directory and any needed parent directories.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the directory to create."},
                },
                "required": ["path"],
            },
            risk_level="mutation",
        ),
        create_directory,
    )

    agent.tools.register_from_def(
        ToolDef(
            name="move_file",
            description="Move or rename a file or directory.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Current path."},
                    "destination": {"type": "string", "description": "New path."},
                },
                "required": ["source", "destination"],
            },
            risk_level="mutation",
        ),
        move_file,
    )

    agent._prompt.append(FILES_PROMPT_SECTION)
```

Run: `pytest tests/test_skill_files.py -v`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tiny_harness/skills/files.py tests/test_skill_files.py
git commit -m "feat: add files skill with 7 tools and prompt augmentation"
```

---

## Phase 8: CLI (P8)

### Task 14: CLI entry point

**Files:**
- Create: `tiny_harness/cli.py`
- Create: `tiny_harness/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write test for CLI one-shot mode**

```python
# tests/test_cli.py
import sys
import pytest
from unittest.mock import patch, AsyncMock
from tiny_harness.cli import parse_args, main


def test_parse_args_one_shot():
    with patch.object(sys, 'argv', ['tiny-harness', 'Hello']):
        args = parse_args()
        assert args.prompt == 'Hello'
        assert args.session is False


def test_parse_args_no_prompt_session():
    with patch.object(sys, 'argv', ['tiny-harness']):
        args = parse_args()
        assert args.prompt is None
        # With no prompt and no --session, session mode is default
        # The CLI should enter session mode when no prompt given


def test_parse_args_with_options():
    with patch.object(sys, 'argv', [
        'tiny-harness', 'Hello',
        '--model', 'claude-opus',
        '--workspace', '/tmp/project',
        '--max-iterations', '10',
        '--skills', 'files',
    ]):
        args = parse_args()
        assert args.prompt == 'Hello'
        assert args.model == 'claude-opus'
        assert args.workspace == '/tmp/project'
        assert args.max_iterations == 10
        assert args.skills == ['files']
```

- [ ] **Step 2: Implement parse_args and main skeleton**

```python
# tiny_harness/cli.py
"""tiny-harness CLI — session REPL and one-shot mode."""
import os
import sys
import json
import asyncio
from argparse import ArgumentParser, Namespace


def parse_args() -> Namespace:
    parser = ArgumentParser(
        prog="tiny-harness",
        description="AI agent harness with tools and streaming CLI",
    )
    parser.add_argument("prompt", nargs="?", default=None, help="Prompt for one-shot mode")
    parser.add_argument("--model", "-m", default="claude-sonnet-4-20250514", help="Model identifier")
    parser.add_argument("--workspace", "-w", default=os.getcwd(), help="Workspace directory")
    parser.add_argument("--max-iterations", type=int, default=25, help="Max loop iterations")
    parser.add_argument("--skills", default="", help="Comma-separated skill names (e.g. 'files')")
    parser.add_argument("--api-key-env", default="ANTHROPIC_API_KEY", help="Env var for API key")
    return parser.parse_args()


def _get_api_key(args: Namespace) -> str:
    key = os.environ.get(args.api_key_env)
    if not key:
        print(f"Error: API key not found. Set {args.api_key_env} environment variable.")
        sys.exit(1)
    return key


async def _run_one_shot(args: Namespace, agent):
    """Stream output for a single prompt, then exit."""
    async for event in agent.run_stream(args.prompt):
        if event.type == "iteration":
            pass  # Skip iteration metadata in one-shot
        elif event.type == "text_delta" and event.content:
            print(event.content, end="", flush=True)
        elif event.type == "tool_start":
            print(f"\n  ⚡ {event.tool_name}", end="", flush=True)
        elif event.type == "tool_end" and event.content:
            print(f"  ({event.content})", flush=True)
        elif event.type == "error" and event.message:
            print(f"\n  ⚠ {event.message}")
    print()


async def _run_session(args: Namespace, agent):
    """Interactive REPL session."""
    print("╔══════════════════════════════════════════╗")
    print(f"║              tiny-harness                 ║")
    print(f"║         model: {args.model[:25]:<25} ║")
    print(f"║         workspace: {args.workspace[:21]:<21} ║")
    print(f"║         type /help for commands           ║")
    print("╚══════════════════════════════════════════╝")
    print()

    while True:
        try:
            user_input = await _async_input("> ")
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input == "/exit" or user_input == "/quit":
            break
        if user_input == "/help":
            print("Commands: /exit, /help, /tools, /clear, /stats, /save FILE")
            continue
        if user_input == "/tools":
            tools = agent.tools.names()
            print(f"Tools ({len(tools)}): {', '.join(tools)}")
            continue
        if user_input == "/clear":
            agent.clear()
            print("Conversation cleared.")
            continue
        if user_input.startswith("/save"):
            parts = user_input.split(maxsplit=1)
            filepath = parts[1] if len(parts) > 1 else "conversation.json"
            with open(filepath, "w") as f:
                json.dump(agent._messages.to_list(), f, indent=2)
            print(f"Saved to {filepath}")
            continue

        async for event in agent.run_stream(user_input):
            if event.type == "iteration":
                tokens = event.content or "?"
                print(f"\n[Iter {event.num}/{event.max} | Tokens: {tokens}]")
            elif event.type == "text_delta" and event.content:
                print(event.content, end="", flush=True)
            elif event.type == "tool_start":
                print(f"\n  ⚡ {event.tool_name}", end="", flush=True)
            elif event.type == "tool_end" and event.content:
                print(f"  ({event.content})", flush=True)
            elif event.type == "error" and event.message:
                print(f"\n  ⚠ {event.message}")
        print()


async def _async_input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


def main():
    args = parse_args()
    api_key = _get_api_key(args)

    from tiny_harness import Agent, Prompt, Config
    prompt = Prompt("You are a helpful AI assistant. Use tools when appropriate.")
    config = Config(
        model=args.model,
        api_key=api_key,
        workspace=args.workspace,
        max_iterations=args.max_iterations,
    )
    agent = Agent(prompt=prompt, config=config)

    # Load skills
    for skill_name in args.skills.split(","):
        skill_name = skill_name.strip()
        if skill_name:
            agent.load_skill(skill_name)

    if args.prompt:
        asyncio.run(_run_one_shot(args, agent))
    else:
        asyncio.run(_run_session(args, agent))
```

- [ ] **Step 3: Create __main__.py**

```python
# tiny_harness/__main__.py
from tiny_harness.cli import main
main()
```

- [ ] **Step 4: Run CLI tests**

```bash
pytest tests/test_cli.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tiny_harness/cli.py tiny_harness/__main__.py tests/test_cli.py
git commit -m "feat: add CLI with session REPL and one-shot mode"
```

---

## Final Integration Test

### Task 15: End-to-end integration test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
import os
import pytest
from tiny_harness import Agent, Prompt, Config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_simple_prompt_no_tools():
    """Integration test: real API call with a simple prompt."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    prompt = Prompt("You are a helpful assistant. Be concise.")
    config = Config(
        model="claude-sonnet-4-20250514",
        api_key=api_key,
        workspace=os.getcwd(),
    )
    agent = Agent(prompt=prompt, config=config)

    result = await agent.run("What is 2+2?")
    assert "4" in result
```

Run: `ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest tests/test_integration.py -v -m integration`
Expected: PASS (or SKIP if no key)

- [ ] **Step 2: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration test"
```

---

## Setup Files

### Task 16: pyproject.toml

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "tiny-harness"
version = "0.1.0"
description = "Minimal AI agent harness — wrap an LLM with tools and a streaming CLI"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
tiny-harness = "tiny_harness.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: integration tests requiring API key",
]
```

- [ ] **Step 2: Install and verify**

```bash
pip install -e ".[dev]"
pytest tests/ -v --ignore=tests/test_integration.py
```
Expected: All unit tests pass

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with dependencies and scripts"
```

---

## Summary

| Phase | Tasks | Files Created |
|---|---|---|
| P1 | 1-3 | `_config.py`, `_events.py`, `_guard.py` |
| P2 | 4-5 | `_llm.py` |
| P3 | 6 | `_messages.py` |
| P4 | 7-8 | `_tools.py` |
| P5 | 9-10 | `_loop.py` |
| P6 | 11 | `_core.py`, `__init__.py` |
| P7 | 12-13 | `tools/files.py`, `skills/files.py` |
| P8 | 14 | `cli.py`, `__main__.py` |
| Integration | 15 | `test_integration.py` |
| Setup | 16 | `pyproject.toml` |

**Total**: 16 tasks, ~1,405 lines of implementation, ~500 lines of tests.
