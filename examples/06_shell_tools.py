#!/usr/bin/env python3
"""
Example: Agent uses shell commands to explore and modify the project.
Usage: export DEEPSEEK_API_KEY="sk-..." && python examples/06_shell_tools.py
"""
import asyncio, os
from tiny_harness import Agent, Prompt, Config

async def main():
    agent = Agent(
        prompt=Prompt("You have shell and file tools. Use them to explore and work with code."),
        config=Config(model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"], workspace=".",
                       provider="deepseek", api_base_url="https://api.deepseek.com/v1", max_iterations=10, max_errors=20),
    )
    agent.load_skill("files")
    agent.load_skill("shell")

    result = await agent.run(
        "Use shell commands to: 1) Check git status, 2) Count Python files in the project, "
        "3) Show the last 3 git commits. Summarize what you find."
    )
    print(f"Agent: {result}")

if __name__ == "__main__":
    asyncio.run(main())
