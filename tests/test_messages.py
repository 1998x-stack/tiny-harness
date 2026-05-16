# tests/test_messages.py
import json
from tiny_harness._config import Prompt
from tiny_harness._messages import MessageManager, TokenStatus
from tiny_harness._llm import ToolCallRequest


def test_initial_messages_have_system():
    prompt = Prompt("You are a helpful assistant.")
    mgr = MessageManager(prompt)
    msgs = mgr.to_list()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
    assert "You are a helpful assistant." in msgs[0]["content"]


def test_add_user_message():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Hello")
    msgs = mgr.to_list()
    assert len(msgs) == 2
    assert msgs[1]["role"] == "user"


def test_add_assistant_with_text():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Hi")
    mgr.add_assistant(text="Hello!", tool_calls=None)
    msgs = mgr.to_list()
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["content"] == "Hello!"


def test_add_assistant_with_tool_calls():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Read file")
    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    mgr.add_assistant(text=None, tool_calls=[tc])
    msgs = mgr.to_list()
    assert msgs[2]["role"] == "assistant"
    assert "tool_calls" in msgs[2]


def test_add_tool_result():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Read file")
    tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})
    mgr.add_assistant(text=None, tool_calls=[tc])
    mgr.add_tool_result(tool_call_id="tc1", content="file content here")
    msgs = mgr.to_list()
    assert msgs[3]["role"] == "tool"
    assert msgs[3]["tool_call_id"] == "tc1"


def test_add_system_notice():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_system_notice("You have 3 iterations left.")
    msgs = mgr.to_list()
    assert "[System Notice]" in msgs[1]["content"]


def test_estimate_tokens_is_positive():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Hello world, this is a test message.")
    tokens = mgr.estimate_tokens()
    assert tokens > 0


def test_check_context_ok():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    assert mgr.check_context() == TokenStatus.OK


def test_clear_resets_conversation_keeps_system():
    prompt = Prompt("You are helpful.")
    mgr = MessageManager(prompt)
    mgr.add_user("Hello")
    mgr.clear()
    msgs = mgr.to_list()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
