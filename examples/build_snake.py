#!/usr/bin/env python3
"""Let tiny-harness build a Snake game.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/build_snake.py
"""

import asyncio
import os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("""You are a game developer. Create complete, runnable Python games.
Use file tools to write game files. Write all code — no placeholders, no TODOs."""),
        config=Config(
            model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".", provider="deepseek", api_base_url="https://api.deepseek.com/v1",
        ),
    )
    agent.load_skill("files")

    result = await agent.run("""
Create a terminal Snake game at examples/agent-projects/snake.py.

Requirements:
- Use the curses library (standard Python)
- Arrow keys to control the snake
- Food appears randomly, snake grows when eating
- Game over if snake hits itself or the wall
- Score display
- Speed increases as snake grows
- Press Q to quit, R to restart
- Single self-contained Python file

Make it complete and runnable with `python snake.py`.
""")
    print(f"Agent: {result}")

    path = "examples/agent-projects/snake.py"
    if os.path.exists(path):
        print(f"\n✅ Created: {path} ({os.path.getsize(path)} bytes)")
        print("   Run with: python examples/agent-projects/snake.py")
    else:
        print("\n❌ Not created. Check agent output.")


if __name__ == "__main__":
    asyncio.run(main())
