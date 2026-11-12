"""Guard against sending an API key to the wrong default provider endpoint."""
from argparse import Namespace
from unittest.mock import patch

from tiny_harness import Agent, Config, Prompt
from tiny_harness.cli import _get_api_key


def test_python_api_provider_default_endpoints():
    for provider, endpoint in [
        ("openai", "https://api.openai.com/v1"),
        ("deepseek", "https://api.deepseek.com/v1"),
    ]:
        agent = Agent(prompt=Prompt("sys"), config=Config(
            model="test", api_key="secret", workspace=".", provider=provider
        ))
        assert agent._llm_provider._base_url == endpoint


def test_explicit_custom_gateway_is_preserved():
    agent = Agent(prompt=Prompt("sys"), config=Config(
        model="test", api_key="secret", workspace=".",
        provider="openai", api_base_url="http://localhost:8080/v1"
    ))
    assert agent._llm_provider._base_url == "http://localhost:8080/v1"


def test_default_environment_variables_follow_selected_provider():
    for provider, env in [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
    ]:
        args = Namespace(provider=provider, api_key_env=None)
        with patch.dict("os.environ", {env: provider + "-key"}, clear=True):
            assert _get_api_key(args) == provider + "-key"


def test_config_does_not_reveal_api_key_in_repr():
    config = Config(model="test", api_key="secret-that-must-not-leak", workspace=".")
    assert "secret-that-must-not-leak" not in repr(config)
