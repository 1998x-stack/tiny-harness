#!/usr/bin/env python3
"""Example 1: Basic chat with tiny-harness.

The simplest possible usage — create an agent, ask a question, get an answer.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/01_basic_chat.py
"""

import asyncio
import os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("You are a helpful assistant. Be concise."),
        config=Config(
            model="deepseek-v4-flash",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".",
            provider="deepseek",
            api_base_url="https://api.deepseek.com/v1",
        ),
    )

    result = await agent.run("Explain what an AI agent is in one sentence.")
    print(f"Agent: {result}")


if __name__ == "__main__":
    asyncio.run(main())
