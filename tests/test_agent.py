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


def test_agent_deepseek_default_endpoint():
    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="deepseek-chat", api_key="k", workspace="/tmp"),
    )

    assert agent._llm_provider._base_url == "https://api.deepseek.com/v1"


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
async def test_agent_run_stream_releases_internal_subscriber():
    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="ok")

    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="test", api_key="k", workspace="/tmp"),
    )
    agent._llm_provider = FakeLLM()

    for prompt in ("one", "two"):
        async for _ in agent.run_stream(prompt):
            pass

    assert len(agent.events._handlers) == 0


@pytest.mark.asyncio
async def test_closing_agent_stream_cancels_background_run():
    import asyncio

    class SlowLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            await asyncio.sleep(0.05)
            yield LLMStreamChunk(type="text_delta", content="late")

    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="test", api_key="k", workspace="/tmp"),
    )
    agent._llm_provider = SlowLLM()
    stream = agent.run_stream("stop")

    first = await anext(stream)
    assert first.type == "iteration"
    await stream.aclose()
    await asyncio.sleep(0.1)

    assert agent._running is False
    assert [m for m in agent._messages.to_list() if m["role"] == "assistant"] == []


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


def test_agent_max_iterations_property():
    config = Config(model="test", api_key="k", workspace="/tmp", max_iterations=42)
    agent = Agent(prompt=Prompt("test"), config=config)
    assert agent.max_iterations == 42


def test_agent_estimate_tokens():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._messages.add_user("Hello world")
    tokens = agent.estimate_tokens()
    assert tokens > 0
    assert isinstance(tokens, int)


def test_agent_start_session_idempotent():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    sid1 = agent.start_session()
    assert sid1 is not None
    sid2 = agent.start_session()
    assert sid2 == sid1


def test_agent_save_turn_without_session_is_noop():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._save_turn("user", content="hello")


def test_agent_dump_conversation_writes_user_messages():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._messages.add_user("Hello")
    agent._messages.add_user("World")
    agent.start_session()
    turns = agent._dump_conversation()
    assert turns == 2
    records = agent.store.load_session(agent.session_id)
    assert len(records) == 2
    assert records[0]["role"] == "user"
    assert records[0]["content"] == "Hello"
    assert records[1]["content"] == "World"


def test_agent_dump_conversation_is_idempotent(tmp_path):
    from tiny_harness._persist import SessionStore

    store = SessionStore(base_dir=str(tmp_path))
    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="t", api_key="k", workspace="/tmp"),
        store=store,
    )
    agent._messages.add_user("Hello")
    agent.start_session()

    agent._dump_conversation()
    agent._dump_conversation()

    assert len(store.load_session(agent.session_id)) == 1


def test_agent_save_session_exposes_persistence_interface(tmp_path):
    from tiny_harness._persist import SessionStore

    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="t", api_key="k", workspace="/tmp"),
        store=SessionStore(base_dir=str(tmp_path)),
    )
    agent._messages.add_user("Hello")

    session_id, turns = agent.save_session()

    assert turns == 1
    assert agent.store.load_session(session_id)[0]["content"] == "Hello"


def test_agent_dump_conversation_with_tool_calls():
    from tiny_harness._llm import ToolCallRequest
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._messages.add_user("read file")
    tc = ToolCallRequest(id="call_1", name="read_file", arguments={"path": "test.py"})
    agent._messages.add_assistant(text="Let me read that", tool_calls=[tc])
    agent._messages.add_tool_result("call_1", "print('hello')")
    agent._messages.add_assistant(text=None, tool_calls=None)
    agent._messages.add_user("thanks")
    agent.start_session()
    turns = agent._dump_conversation()
    assert turns == 4
    records = agent.store.load_session(agent.session_id)
    assert records[0]["role"] == "user"
    assert records[1]["role"] == "assistant"
    assert records[1]["tool_calls"][0]["name"] == "read_file"
    assert len(records[1]["tool_results"]) == 1
    assert records[1]["tool_results"][0]["content"] == "print('hello')"
    assert records[3]["role"] == "user"
    assert records[3]["content"] == "thanks"


@pytest.mark.asyncio
async def test_agent_run_persists_via_dump():
    import tempfile

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="Hello from agent")

    with tempfile.TemporaryDirectory() as d:
        from tiny_harness._persist import SessionStore
        store = SessionStore(base_dir=d)
        agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"), store=store)
        agent._llm_provider = FakeLLM()

        result = await agent.run("Hi there")
        assert "Hello from agent" in result

        agent.start_session()
        turns = agent._dump_conversation()
        assert turns == 2

        records = store.load_session(agent.session_id)
        assert records[0]["role"] == "user"
        assert records[0]["content"] == "Hi there"
        assert records[1]["role"] == "assistant"
        assert "Hello from agent" in records[1]["content"]


@pytest.mark.asyncio
async def test_agent_run_stream_persists_via_dump():
    import tempfile

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="Streaming response")

    with tempfile.TemporaryDirectory() as d:
        from tiny_harness._persist import SessionStore
        store = SessionStore(base_dir=d)
        agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"), store=store)
        agent._llm_provider = FakeLLM()

        async for _ in agent.run_stream("stream prompt"):
            pass

        agent.start_session()
        turns = agent._dump_conversation()
        assert turns == 2

        records = store.load_session(agent.session_id)
        assert records[0]["role"] == "user"
        assert records[0]["content"] == "stream prompt"
        assert records[1]["role"] == "assistant"
        assert "Streaming response" in records[1]["content"]


@pytest.mark.asyncio
async def test_agent_save_and_resume_full_cycle():
    import tempfile

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="Answer")

    with tempfile.TemporaryDirectory() as d:
        from tiny_harness._persist import SessionStore
        store = SessionStore(base_dir=d)
        agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"), store=store)
        agent._llm_provider = FakeLLM()

        await agent.run("First question")
        agent.start_session()
        sid = agent.session_id
        agent._dump_conversation()

        agent2 = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"), store=store)
        restored = agent2.resume_session(sid)
        assert restored > 0
        msgs = agent2._messages.to_list()
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert any("First question" in m.get("content", "") for m in user_msgs)


def test_agent_session_round_trips_tool_call_protocol(tmp_path):
    import json
    from tiny_harness._llm import ToolCallRequest
    from tiny_harness._persist import SessionStore

    store = SessionStore(base_dir=str(tmp_path))
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=Prompt("test"), config=config, store=store)
    agent._messages.add_user("read")
    agent._messages.add_assistant(
        "checking",
        [ToolCallRequest(id="call_original", name="read_file", arguments={"path": "x.txt"})],
    )
    full_result = "x" * 500
    agent._messages.add_tool_result("call_original", full_result)
    agent.start_session()
    session_id = agent.session_id
    agent._dump_conversation()

    restored = Agent(prompt=Prompt("test"), config=config, store=store)
    restored.resume_session(session_id)
    messages = restored._messages.to_list()
    assistant = next(m for m in messages if m["role"] == "assistant")
    tool_result = next(m for m in messages if m["role"] == "tool")

    assert assistant["tool_calls"][0]["id"] == "call_original"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "x.txt"}
    assert tool_result == {
        "role": "tool",
        "tool_call_id": "call_original",
        "content": full_result,
    }


@pytest.mark.asyncio
async def test_active_session_persists_complete_tool_turn(tmp_path):
    from tiny_harness._llm import LLMStreamChunk, ToolCallRequest
    from tiny_harness._persist import SessionStore

    class ToolLLM:
        def __init__(self):
            self.calls = 0

        async def generate_stream(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                yield LLMStreamChunk(
                    type="tool_call_end",
                    tool_call=ToolCallRequest(id="call_1", name="echo", arguments={"message": "hi"}),
                )
            else:
                yield LLMStreamChunk(type="text_delta", content="done")

    store = SessionStore(base_dir=str(tmp_path))
    agent = Agent(
        prompt=Prompt("test"),
        config=Config(model="t", api_key="k", workspace=str(tmp_path), no_hitl=True),
        store=store,
    )
    agent._llm_provider = ToolLLM()
    agent.tools.register_tool(
        name="echo",
        description="Echo",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        handler=lambda args: args["message"],
    )
    agent.start_session()

    await agent.run("use echo")

    records = store.load_session(agent.session_id)
    tool_turn = next(record for record in records if record.get("tool_calls"))
    assert tool_turn["tool_calls"][0]["id"] == "call_1"
    assert tool_turn["tool_results"][0] == {"id": "call_1", "content": "hi"}
