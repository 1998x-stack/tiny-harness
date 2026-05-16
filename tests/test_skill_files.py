# tests/test_skill_files.py
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
