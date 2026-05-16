#!/usr/bin/env python3
"""
Example: Agent uses multiple skills together — files + shell + search.
Usage: export DEEPSEEK_API_KEY="sk-..." && python examples/08_multi_skill.py
"""
import asyncio, os
from tiny_harness import Agent, Prompt, Config

async def main():
    agent = Agent(
        prompt=Prompt("You have files, shell, and search tools. Be thorough and verify your work."),
        config=Config(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"], workspace=".",
                       provider="deepseek", api_base_url="https://api.deepseek.com/v1", max_iterations=15, max_errors=20),
    )
    agent.load_skill("files")
    agent.load_skill("shell")
    agent.load_skill("search")

    result = await agent.run(
        "Create a new Python module at examples/agent-projects/utils.py with: "
        "1) A function to count lines of code in a file, "
        "2) A function to list all Python files in a directory. "
        "Then verify the module works by running it and searching for its functions."
    )
    print(f"Agent: {result}")

if __name__ == "__main__":
    asyncio.run(main())
