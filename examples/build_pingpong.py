#!/usr/bin/env python3
"""Let tiny-harness build a terminal ping pong game.

The agent uses file tools to create the game in examples/agent-projects/.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/build_pingpong.py
"""

import asyncio
import os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("""You are a game developer. Create complete, runnable Python games.
Use the file tools to write the game files. Be thorough — write all code, no placeholders.
Games should be terminal-based and run with `python <file>.py`."""),
        config=Config(
            model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".", provider="deepseek", api_base_url="https://api.deepseek.com/v1",
        ),
    )
    agent.load_skill("files")

    result = await agent.run("""
Create a terminal ping pong game at examples/agent-projects/pingpong.py.

Requirements:
- Two-player: Player 1 uses W/S keys, Player 2 uses Up/Down arrows
- Paddles are 4 characters tall
- Ball bounces off walls and paddles
- First to 5 points wins
- Use the curses library (standard Python library)
- Display scores at top
- Show winner message when game ends
- Press Q to quit, R to restart after game over
- Ball velocity changes slightly based on where it hits the paddle
- Center line down the middle of the court

Make it a single self-contained Python file that runs with `python pingpong.py`.
Include proper __main__ guard and curses.wrapper().
""")
    print(f"Agent: {result}")

    path = "examples/agent-projects/pingpong.py"
    if os.path.exists(path):
        print(f"\n✅ Game created: {path} ({os.path.getsize(path)} bytes)")
        print("   Run with: python examples/agent-projects/pingpong.py")
    else:
        print("\n❌ Game not created. Check agent output above.")


if __name__ == "__main__":
    asyncio.run(main())
