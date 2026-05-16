# tests/test_config.py
import pytest
from tiny_harness._config import AgentConfig, Prompt


def test_agentconfig_defaults():
    config = AgentConfig(model="claude-test", api_key="sk-test", workspace="/tmp")
    assert config.model == "claude-test"
    assert config.api_key == "sk-test"
    assert config.workspace == "/tmp"
    assert config.max_iterations == 25
    assert config.max_errors == 10
    assert config.max_consecutive_errors == 3
    assert config.timeout_ms == 30_000
    assert config.max_tool_result_chars == 50_000


def test_prompt_append_and_to_string():
    prompt = Prompt("You are a helpful assistant.")
    prompt.append("## Tools\nUse tools when needed.")
    prompt.append("## Rules\nBe concise.")
    result = prompt.to_string()
    assert "You are a helpful assistant." in result
    assert "## Tools" in result
    assert "## Rules" in result
    assert "\n\n" in result
