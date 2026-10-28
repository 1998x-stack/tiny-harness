"""The active system prompt must include skills loaded after Agent construction."""
import pytest
from tiny_harness import Agent, Config, Prompt
from tiny_harness._llm import LLMStreamChunk


def make_agent(prompt=None):
    return Agent(
        prompt=prompt or Prompt("base"),
        config=Config(model="fixture", api_key="unused", workspace="."),
    )


def test_loading_skill_refreshes_system_message():
    agent = make_agent()
    assert "File Operations" not in agent._messages.to_list()[0]["content"]
    agent.load_skill("files")
    assert "File Operations" in agent._messages.to_list()[0]["content"]
    agent.load_skill("shell")
    assert "Shell Commands" in agent._messages.to_list()[0]["content"]
    agent.clear()
    assert "Shell Commands" in agent._messages.to_list()[0]["content"]


@pytest.mark.asyncio
async def test_skill_loaded_between_runs_is_seen_by_provider():
    agent = make_agent()
    seen = []

    class CapturingProvider:
        async def generate_stream(self, messages, tools=None):
            seen.append(messages[0]["content"])
            yield LLMStreamChunk(type="text_delta", content="ok")

    agent._llm_provider = CapturingProvider()
    assert await agent.run("first") == "ok"
    agent.load_skill("search")
    assert await agent.run("second") == "ok"
    assert "Code Search" not in seen[0]
    assert "Code Search" in seen[1]


def test_token_count_uses_latest_prompt_sections():
    prompt = Prompt("base")
    agent = make_agent(prompt)
    before = agent.estimate_tokens()
    prompt.append("extra " * 500)
    assert agent.estimate_tokens() > before
