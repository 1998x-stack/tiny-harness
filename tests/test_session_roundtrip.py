"""Session snapshots are idempotent and restore complete tool-call transcripts."""
import json
import os

import pytest

from tiny_harness import Agent, Config, Prompt, ToolDef
from tiny_harness._llm import LLMStreamChunk, ToolCallRequest
from tiny_harness._persist import SessionStore


def _agent(store):
    return Agent(
        Prompt("system"), Config(model="fixture", api_key="unused", workspace="."),
        store=store,
    )


def test_save_twice_does_not_duplicate_records(tmp_path):
    store = SessionStore(str(tmp_path))
    agent = _agent(store)
    agent._messages.add_user("inspect")
    agent._messages.add_assistant(
        text="checking",
        tool_calls=[ToolCallRequest(id="c1", name="echo", arguments={"message": "x"})],
    )
    agent._messages.add_tool_result("c1", "long result " * 50)
    agent._messages.add_assistant("complete")
    agent.start_session()
    assert agent._dump_conversation() == 3
    once = store.load_session(agent.session_id)
    assert agent._dump_conversation() == 3
    twice = store.load_session(agent.session_id)
    assert once == twice
    assert twice[1]["tool_calls"][0]["id"] == "c1"
    assert twice[1]["tool_calls"][0]["arguments"] == {"message": "x"}
    assert twice[1]["tool_results"][0]["id"] == "c1"
    assert twice[1]["tool_results"][0]["content"] == "long result " * 50

    resumed = _agent(store)
    assert resumed.resume_session(agent.session_id) == 3
    assert resumed._messages.to_list() == agent._messages.to_list()


@pytest.mark.asyncio
async def test_run_with_tools_snapshots_entire_history(tmp_path):
    store = SessionStore(str(tmp_path))
    agent = _agent(store)
    agent.start_session()
    agent.tools.register_from_def(
        ToolDef("echo", "echo", {"type": "object", "properties": {
            "message": {"type": "string"},
        }, "required": ["message"]}, risk_level="read_only"),
        lambda args: args["message"] + "-result",
    )

    class ScriptedProvider:
        def __init__(self):
            self.calls = 0
        async def generate_stream(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                yield LLMStreamChunk(
                    type="tool_call_end",
                    tool_call=ToolCallRequest(id="call-001", name="echo", arguments={"message": "test"}),
                )
            else:
                yield LLMStreamChunk(type="text_delta", content="final")

    agent._llm_provider = ScriptedProvider()
    assert await agent.run("start") == "final"
    records = store.load_session(agent.session_id)
    assert [r["role"] for r in records] == ["user", "assistant", "assistant"]
    assert records[1]["tool_calls"][0]["id"] == "call-001"
    assert records[1]["tool_results"][0]["content"] == "test-result"

    clone = _agent(store)
    clone.resume_session(agent.session_id)
    assert clone._messages.to_list() == agent._messages.to_list()


def test_loading_truncated_last_line_does_not_break_history(tmp_path):
    store = SessionStore(str(tmp_path))
    sid = store.new_session()
    store.save_turn(sid, 1, "user", "safe")
    with open(store._session_path(sid), "a", encoding="utf-8") as stream:
        stream.write('{"broken": ')
    records = store.load_session(sid)
    assert len(records) == 1
    assert store.list_sessions()[0]["session_id"] == sid


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_session_files_are_private(tmp_path):
    store = SessionStore(str(tmp_path))
    sid = store.new_session()
    store.save_turn(sid, 1, "user", "hello")
    assert os.stat(store._session_path(sid)).st_mode & 0o077 == 0
