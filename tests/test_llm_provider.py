# tests/test_llm_provider.py
import json
import pytest
from tiny_harness._llm import AnthropicProvider, LLMRetryConfig, OpenAIProvider


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


def test_anthropic_converts_tool_messages_to_content_blocks():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "read"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"x.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": "contents"},
    ]

    converted = provider._convert_messages(messages)

    assert converted[1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "x.txt"}},
        ],
    }
    assert converted[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "contents"}],
    }


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
    tools = [{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object", "properties": {}}}]
    result = provider._convert_tools(tools)
    assert len(result) == 1
    assert result[0]["name"] == "read_file"


def test_parse_response_with_text_and_tool_calls():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")

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


def test_parse_sse_line_event():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    result = provider._parse_sse_line("event: message_start")
    assert result == ("message_start", None)


def test_parse_sse_line_data():
    provider = AnthropicProvider(api_key="test-key", model="claude-test")
    data_str = json.dumps({"message": {"usage": {"input_tokens": 10}}})
    result = provider._parse_sse_line(f"data: {data_str}")
    assert result[0] == "data"
    assert result[1]["message"]["usage"]["input_tokens"] == 10


def test_retry_config_defaults():
    config = LLMRetryConfig()
    assert config.max_retries == 3
    assert config.base_delay == 1.0
    assert config.max_delay == 60.0


@pytest.mark.asyncio
async def test_anthropic_stream_pairs_event_and_data_lines(monkeypatch):
    import httpx

    lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}',
        "",
    ]

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            for line in lines:
                yield line

    class AsyncContext:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *exc):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return AsyncContext(FakeResponse())

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    provider = AnthropicProvider(api_key="test", model="claude-test")

    chunks = [chunk async for chunk in provider.generate_stream([{"role": "user", "content": "hi"}])]

    assert [(c.type, c.content) for c in chunks] == [
        ("usage", '{"input": 3}'),
        ("text_delta", "hello"),
    ]


@pytest.mark.asyncio
async def test_anthropic_stream_emits_complete_tool_call(monkeypatch):
    import httpx

    lines = [
        "event: content_block_start",
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"read_file"}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":"}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\"x.txt\\"}"}}',
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":1}',
    ]

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            for line in lines:
                yield line

    class AsyncContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *exc):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return AsyncContext()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    provider = AnthropicProvider(api_key="test", model="claude-test")

    chunks = [chunk async for chunk in provider.generate_stream([{"role": "user", "content": "read"}])]
    completed = [chunk.tool_call for chunk in chunks if chunk.type == "tool_call_end"]

    assert len(completed) == 1
    assert completed[0].id == "toolu_1"
    assert completed[0].name == "read_file"
    assert completed[0].arguments == {"path": "x.txt"}


@pytest.mark.asyncio
async def test_anthropic_stream_retries_transient_status(monkeypatch):
    import httpx

    statuses = [429, 200]

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        async def aread(self):
            return b"busy"

        async def aiter_lines(self):
            yield "event: content_block_delta"
            yield 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}'

    class AsyncContext:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *exc):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return AsyncContext(FakeResponse(statuses.pop(0)))

    async def no_sleep(delay):
        pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr("tiny_harness._llm.asyncio.sleep", no_sleep)
    provider = AnthropicProvider(
        api_key="test",
        model="claude-test",
        retry_config=LLMRetryConfig(max_retries=1, base_delay=0),
    )

    chunks = [chunk async for chunk in provider.generate_stream([{"role": "user", "content": "hi"}])]

    assert [chunk.content for chunk in chunks if chunk.type == "text_delta"] == ["ok"]
    assert statuses == []


def test_openai_provider_convert_messages_passthrough():
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    result = provider._convert_messages(msgs)
    assert result == msgs


def test_openai_provider_convert_tools():
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    tools = [{"name": "read_file", "description": "Read", "input_schema": {"type": "object", "properties": {}}}]
    result = provider._convert_tools(tools)
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "read_file"


def test_openai_provider_parse_response():
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    data = {
        "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    result = provider._parse_response(data)
    assert result.text == "Hello!"
    assert result.is_final() is True


def test_openai_provider_parse_response_with_tool_calls():
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    data = {
        "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "tc1", "function": {"name": "read_file", "arguments": '{"path": "/tmp/x"}'}}
        ]}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    result = provider._parse_response(data)
    assert result.is_final() is False
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"


def test_openai_provider_convert_tools_none():
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o")
    assert provider._convert_tools(None) is None


@pytest.mark.asyncio
async def test_openai_stream_retries_transient_status(monkeypatch):
    import httpx

    statuses = [503, 200]

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        async def aread(self):
            return b"busy"

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'
            yield "data: [DONE]"

    class AsyncContext:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *exc):
            return False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *args, **kwargs):
            return AsyncContext(FakeResponse(statuses.pop(0)))

    async def no_sleep(delay):
        pass

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr("tiny_harness._llm.asyncio.sleep", no_sleep)
    provider = OpenAIProvider(
        api_key="test",
        model="gpt-test",
        retry_config=LLMRetryConfig(max_retries=1, base_delay=0),
    )

    chunks = [chunk async for chunk in provider.generate_stream([{"role": "user", "content": "hi"}])]

    assert [chunk.content for chunk in chunks if chunk.type == "text_delta"] == ["ok"]
    assert statuses == []
