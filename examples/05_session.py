#!/usr/bin/env python3
"""Example 5: Session with multiple prompts.

The agent maintains conversation context across prompts within a session.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/05_session.py
"""

import asyncio
import os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("You are a helpful assistant. Be concise. Remember what we discuss."),
        config=Config(
            model="deepseek-v4-flash",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".",
            provider="deepseek",
            api_base_url="https://api.deepseek.com/v1",
        ),
    )

    # Prompt 1
    result = await agent.run("My name is Alice and I like Python.")
    print(f"Agent: {result}\n")

    # Prompt 2 — agent remembers from prompt 1
    result = await agent.run("What's my name and what language do I like?")
    print(f"Agent: {result}\n")

    # Prompt 3
    result = await agent.run("Suggest a Python project for me.")
    print(f"Agent: {result}")


if __name__ == "__main__":
    asyncio.run(main())
