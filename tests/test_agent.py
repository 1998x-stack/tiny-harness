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
    agent.tools.register_from_def(def_, lambda args: "echo")
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


def test_agent_clear():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.clear()


def test_agent_config_fields():
    config = Config(model="gpt-4o", api_key="k", workspace="/tmp", provider="openai", api_base_url="https://api.openai.com/v1", max_iterations=10)
    assert config.provider == "openai"
    assert config.api_base_url == "https://api.openai.com/v1"
    assert config.max_iterations == 10


def test_agent_config_defaults():
    config = Config(model="m", api_key="k", workspace=".")
    assert config.provider == "deepseek"
    assert config.api_base_url is None
    assert config.max_iterations == 25
    assert config.max_errors == 10


def test_agent_config_unknown_provider():
    prompt = Prompt("test")
    config = Config(model="m", api_key="k", workspace=".", provider="unknown")
    with pytest.raises(ValueError, match="Unknown provider"):
        Agent(prompt=prompt, config=config)


@pytest.mark.asyncio
async def test_agent_run_stream_yields_events():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="Hello")
            yield LLMStreamChunk(type="text_delta", content=" world")

    agent = Agent(prompt=prompt, config=config)
    agent._llm_provider = FakeLLM()

    events = []
    async for event in agent.run_stream("Hi"):
        if event.type == "text_delta":
            events.append(event.content)

    assert "Hello" in "".join(events)


@pytest.mark.asyncio
async def test_agent_concurrent_run_raises():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent._running = True  # simulate running state
    with pytest.raises(RuntimeError, match="already running"):
        await agent.run("Hi")


@pytest.mark.asyncio
async def test_agent_run_stream_concurrent_raises():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent._running = True
    with pytest.raises(RuntimeError, match="already running"):
        async for _ in agent.run_stream("Hi"):
            pass


def test_agent_on_subscribes_to_event_type():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    received = []

    async def handler(event):
        received.append(event.type)

    agent.on("text_delta", handler)
    assert len(agent.events._handlers) == 1


@pytest.mark.asyncio
async def test_agent_session_accumulates_conversation():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")

    call_count = [0]
    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            call_count[0] += 1
            from tiny_harness._llm import LLMStreamChunk
            msg_count = len([m for m in messages if m["role"] == "user"])
            yield LLMStreamChunk(type="text_delta", content=f"msg_count={msg_count}")

    agent = Agent(prompt=prompt, config=config)
    agent._llm_provider = FakeLLM()

    result1 = await agent.run("First prompt")
    assert "msg_count=1" in result1

    result2 = await agent.run("Second prompt")
    assert "msg_count=2" in result2  # user msgs: "First prompt" + "Second prompt"
    assert call_count[0] == 2


def test_agent_clear_resets_conversation():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent._messages.add_user("Hello")
    agent._messages.add_assistant(text="Hi", tool_calls=None)
    assert len(agent._messages.to_list()) == 3
    agent.clear()
    assert len(agent._messages.to_list()) == 1  # only system remains
