"""Event and child-task ownership in streaming Agent.run_stream."""
import asyncio
import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._llm import LLMStreamChunk


def new_agent():
    return Agent(Prompt("system"), Config(model="fixture", api_key="unused", workspace="."))


class InstantProvider:
    async def generate_stream(self, messages, tools=None):
        yield LLMStreamChunk(type="text_delta", content="done")


@pytest.mark.asyncio
async def test_stream_unsubscribes_collectors_after_each_run():
    agent = new_agent()
    agent._llm_provider = InstantProvider()
    initial = len(agent.events._handlers)
    for _ in range(5):
        async for _ in agent.run_stream("go"):
            pass
        assert len(agent.events._handlers) == initial


@pytest.mark.asyncio
async def test_stream_aclose_cancels_child_before_reuse():
    agent = new_agent()
    cancelled = asyncio.Event()

    class BlockingProvider:
        async def generate_stream(self, messages, tools=None):
            try:
                yield LLMStreamChunk(type="text_delta", content="started")
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    agent._llm_provider = BlockingProvider()
    stream = agent.run_stream("first")
    async for event in stream:
        if event.type == "text_delta":
            break
    await stream.aclose()
    assert cancelled.is_set()
    assert not agent._running
    assert not agent.events._handlers
    agent._llm_provider = InstantProvider()
    assert await agent.run("second") == "done"


@pytest.mark.asyncio
async def test_stream_saves_same_final_answer_as_run(tmp_path):
    from tiny_harness._persist import SessionStore
    store = SessionStore(str(tmp_path))
    agent = Agent(
        Prompt("system"), Config(model="fixture", api_key="unused", workspace="."),
        store=store,
    )
    agent.start_session()
    agent._llm_provider = InstantProvider()
    events = []
    async for event in agent.run_stream("hi"):
        events.append(event)
    assert any(event.type == "text_delta" for event in events)
    records = store.load_session(agent.session_id)
    assert records[-1]["role"] == "assistant"
    assert records[-1]["content"] == "done"
