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
