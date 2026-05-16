#!/usr/bin/env python3
"""Example 2: File operations with the files skill.

The agent reads and writes files in the workspace.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/02_file_tools.py
"""

import asyncio
import os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("You are a helpful coding assistant. Use tools when needed."),
        config=Config(
            model="deepseek-v4-flash",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".",
            provider="deepseek",
            api_base_url="https://api.deepseek.com/v1",
        ),
    )

    agent.load_skill("files")

    result = await agent.run(
        "Create a file called examples/output/hello.txt containing the text "
        "'Hello from tiny-harness!'"
    )
    print(f"Agent: {result}")


if __name__ == "__main__":
    asyncio.run(main())
