#!/usr/bin/env python3
"""
Example: Agent searches codebase to answer questions.
Usage: export DEEPSEEK_API_KEY="sk-..." && python examples/07_search_tools.py
"""
import asyncio
import os
from tiny_harness import Agent, Prompt, Config

async def main():
    agent = Agent(
        prompt=Prompt("You have search and file tools. Use them to analyze code."),
        config=Config(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"], workspace=".",
                       provider="deepseek", api_base_url="https://api.deepseek.com/v1", max_iterations=10, max_errors=20),
    )
    agent.load_skill("files")
    agent.load_skill("search")

    result = await agent.run(
        "Search the tiny_harness/ directory for: 1) All class definitions, "
        "2) All async def functions, 3) TODO comments. Report what you find."
    )
    print(f"Agent: {result}")

if __name__ == "__main__":
    asyncio.run(main())
