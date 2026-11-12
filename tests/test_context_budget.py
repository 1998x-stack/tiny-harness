"""Context budgets must be enforced before network calls without orphan tools."""
import json

import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._config import AgentConfig
from tiny_harness._events import EventBus
from tiny_harness._llm import LLMStreamChunk, ToolCallRequest
from tiny_harness._loop import AgentLoop
from tiny_harness._messages import MessageManager, TokenStatus


def test_pruning_removes_complete_old_turn_with_tool_calls():
    messages = MessageManager(Prompt("sys"), max_input_tokens=200)
    messages.add_user("previous question " * 30)
    messages.add_assistant("working", [ToolCallRequest("c1", "lookup", {"q": "x"})])
    messages.add_tool_result("c1", "x" * 5000)
    messages.add_assistant("previous response")
    messages.add_user("latest question")
    stats = messages.compact(target_tokens=70)
    assert stats["after"] <= 70
    history = messages.to_list()
    assert history[0]["role"] == "system"
    assert history[-1] == {"role": "user", "content": "latest question"}
    assert all(m.get("role") != "tool" for m in history)
    assert all(not m.get("tool_calls") for m in history)


def test_oversized_tool_result_is_compacted_without_orphaning_call():
    messages = MessageManager(Prompt("sys"), max_input_tokens=400)
    messages.add_user("do task")
    messages.add_assistant(None, [ToolCallRequest("c1", "read_file", {"path": "x"})])
    messages.add_tool_result("c1", "x" * 5000)
    stats = messages.compact(target_tokens=350)
    assert stats["shortened"] == 1
    assert stats["after"] <= 350
    assert [m["tool_call_id"] for m in messages.to_list() if m["role"] == "tool"] == ["c1"]


@pytest.mark.asyncio
async def test_agent_loop_compacts_before_provider_call(tmp_path):
    messages = MessageManager(Prompt("sys"), max_input_tokens=250)
    messages.add_user("old question")
    messages.add_assistant("old answer " * 200)
    events = EventBus()
    notices = []

    async def collect(event):
        if event.type == "context":
            notices.append(json.loads(event.content))
    events.subscribe(collect)

    class SpyProvider:
        calls = 0
        async def generate_stream(self, history, tools):
            self.calls += 1
            assert messages.estimate_tokens() <= messages.max_input_tokens
            assert history[-1]["content"] == "new question"
            yield LLMStreamChunk(type="text_delta", content="ok")

    class NoTools:
        def get_definitions(self):
            return []

    provider = SpyProvider()
    config = AgentConfig(model="fake", api_key="unused",
                         workspace=str(tmp_path), context_window=300, max_tokens=50)
    result = await AgentLoop(config, messages, provider, NoTools(), events).run("new question")
    assert result == "ok"
    assert provider.calls == 1
    assert notices


@pytest.mark.asyncio
async def test_too_large_latest_prompt_never_reaches_provider(tmp_path):
    messages = MessageManager(Prompt("sys"), max_input_tokens=70)

    class SpyProvider:
        calls = 0
        async def generate_stream(self, history, tools):
            self.calls += 1
            yield LLMStreamChunk(type="text_delta", content="should never appear")

    class NoTools:
        def get_definitions(self):
            return []

    provider = SpyProvider()
    config = AgentConfig(model="fake", api_key="unused",
                         workspace=str(tmp_path), context_window=90, max_tokens=20)
    answer = await AgentLoop(config, messages, provider, NoTools(), EventBus()).run("X" * 2000)
    assert "context_window" in answer
    assert provider.calls == 0
    assert messages.to_list()[-1]["role"] == "assistant"


def test_invalid_context_window_fails_before_provider(tmp_path):
    with pytest.raises(ValueError, match="context_window"):
        Agent(Prompt("sys"), Config(model="fake", api_key="unused",
             workspace=str(tmp_path), context_window=100, max_tokens=100))
