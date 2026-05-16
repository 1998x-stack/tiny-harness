# tests/test_skill_files.py
import pytest
from tiny_harness import Agent, Prompt, Config


def test_load_files_skill_registers_tools():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.load_skill("files")
    names = agent.tools.names()
    assert "read_file" in names
    assert "write_file" in names
    assert "list_directory" in names
    assert "find_files" in names


def test_load_files_skill_appends_prompt():
    prompt = Prompt("You are helpful.")
    config = Config(model="claude-test", api_key="sk-test", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    original = agent._prompt.to_string()
    agent.load_skill("files")
    updated = agent._prompt.to_string()
    assert len(updated) > len(original)


def test_load_skill_not_found():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    with pytest.raises(RuntimeError, match="not found"):
        agent.load_skill("nonexistent_skill_xyz")


def test_load_skill_duplicate_does_not_reregister():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.load_skill("files")
    count_before = len(agent.tools.names())
    agent.load_skill("files")
    assert len(agent.tools.names()) == count_before


def test_load_skill_prompt_accumulates():
    prompt = Prompt("base.")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.load_skill("files")
    full = agent._prompt.to_string()
    assert "base." in full
    assert "File Operations" in full


def test_skill_registers_all_seven_tools():
    prompt = Prompt("test")
    config = Config(model="t", api_key="k", workspace="/tmp")
    agent = Agent(prompt=prompt, config=config)
    agent.load_skill("files")
    expected_tools = {"read_file", "write_file", "list_directory", "find_files", "delete_file", "create_directory", "move_file"}
    assert expected_tools.issubset(set(agent.tools.names()))
