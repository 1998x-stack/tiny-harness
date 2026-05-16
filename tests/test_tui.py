# tests/test_tui.py
from tiny_harness import Agent, Prompt, Config
from tiny_harness.tui import TuiSession, _rich_available


def test_rich_available():
    assert _rich_available() is True


def test_tui_session_creation():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "claude-test")
    assert tui.model == "claude-test"
    assert tui.iteration == 0
    assert tui.tokens_used == 0
    assert tui.tool_calls_count == 0
    assert tui.errors_count == 0
    assert len(tui.conversation) == 0


def test_tui_add_user_grows_conversation():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    before = len(tui.conversation)
    tui.add_user("Hello world")
    assert len(tui.conversation) > before


def test_tui_add_tool_call():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    tui.add_tool_call("write_file", '{"path": "hello.py"}')
    assert tui.tool_calls_count == 1


def test_tui_add_tool_result():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    before = len(tui.conversation)
    tui.add_tool_result("file created")
    assert len(tui.conversation) > before


def test_tui_add_error():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    tui.add_error("something went wrong")
    assert tui.errors_count == 1


def test_tui_add_assistant_text():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    before = len(tui.conversation)
    tui.add_assistant_text("Hello **world**")
    assert len(tui.conversation) > before


def test_tui_update_status():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    tui.update_status(5, 4200)
    assert tui.iteration == 5
    assert tui.tokens_used == 4200


def test_tui_render_does_not_crash():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    tui.render("test input")
    tui.add_user("hello")
    tui.add_tool_call("echo", '{"msg": "hi"}')
    tui.add_tool_result("ok")
    tui.add_assistant_text("done")
    tui.add_error("oops")
    tui.update_status(2, 1500)
    tui.render("new input")


def test_tui_has_correct_layout():
    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    tui = TuiSession(agent, "test")
    assert tui.layout.get("header") is not None
    assert tui.layout.get("body") is not None
    assert tui.layout.get("input") is not None
