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
    agent.tools.register_from_def(def_, lambda: "echo")
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
