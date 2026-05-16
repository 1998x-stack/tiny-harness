# tests/test_llm_provider.py
import json
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
