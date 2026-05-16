# tests/test_integration.py
import os
import pytest
from tiny_harness import Agent, Prompt, Config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_simple_prompt_no_tools():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    prompt = Prompt("You are a helpful assistant. Be concise.")
    config = Config(model="claude-sonnet-4-20250514", api_key=api_key, workspace=os.getcwd())
    agent = Agent(prompt=prompt, config=config)
    result = await agent.run("What is 2+2?")
    assert "4" in result
