# tests/test_tui.py
"""Tests for the Rich TUI module."""
from tiny_harness import Agent, Prompt, Config
from tiny_harness.tui import TuiSession, _rich_available


def test_rich_available():
    result = _rich_available()
    assert result is True  # rich should be installed for this test suite


def test_tui_session_creation():
    prompt = Prompt("You are helpful.")
    config = Config(model="test", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "claude-test")
    assert tui.model == "claude-test"
    assert tui.iteration == 0
    assert tui.tokens_used == 0
    assert len(tui.conversation_lines) == 0


def test_tui_add_user_message():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.add_user_message("Hello world")
    assert any("Hello world" in str(line) for line in tui.conversation_lines)


def test_tui_add_text_delta():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.add_text_delta("Hello")
    tui.add_text_delta(" world")
    full = "".join(str(line) for line in tui.conversation_lines)
    assert "Hello" in full
    assert "world" in full


def test_tui_add_tool_start():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.add_tool_start("write_file", '{"path": "hello.py", "content": "print(1)"}')
    full = "".join(str(line) for line in tui.conversation_lines)
    assert "write_file" in full


def test_tui_add_error():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.add_error("something went wrong")
    full = "".join(str(line) for line in tui.conversation_lines)
    assert "something went wrong" in full


def test_tui_update_status():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.update_status(5, 4200)
    assert tui.iteration == 5
    assert tui.tokens_used == 4200


def test_tui_render_does_not_crash():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    tui = TuiSession(agent, "test")
    tui.render("test input")
    tui.add_user_message("hello")
    tui.add_text_delta("world")
    tui.add_tool_start("echo", '{"msg": "hi"}')
    tui.add_tool_end("echo", "ok")
    tui.update_status(2, 1500)
    tui.render("new input")
