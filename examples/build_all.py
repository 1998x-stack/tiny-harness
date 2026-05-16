#!/usr/bin/env python3
"""Let tiny-harness build ALL games in sequence.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/build_all.py
"""

import asyncio, os, sys
from tiny_harness import Agent, Prompt, Config


PROJECTS = [
    {
        "name": "Ping Pong",
        "file": "examples/agent-projects/pingpong.py",
        "prompt": """Create a terminal ping pong game at examples/agent-projects/pingpong.py.
Two-player (W/S vs Up/Down), 4-char paddles, ball bouncing, first to 5 wins.
Use curses. Single self-contained file. Q to quit, R to restart after game over."""},
    {
        "name": "Snake",
        "file": "examples/agent-projects/snake.py",
        "prompt": """Create a terminal Snake game at examples/agent-projects/snake.py.
Use curses, arrow key control, food grows snake, wall/hit-self = game over.
Score display, speed increases. Single self-contained file."""},
    {
        "name": "CartPole",
        "file": "examples/agent-projects/cartpole.py",
        "prompt": """Create a CartPole RL environment at examples/agent-projects/cartpole.py.
Pure Python, Gym-style API (reset/step/render). Physics: cart on track, hinged pole.
State: [x, x_dot, theta, theta_dot]. Actions: push left/right.
Reward: +1 per step. Episode ends: |theta| > 12° or |x| > 2.4 or steps > 500.
Terminal render(). Single self-contained file with demo main()."""},
    {
        "name": "Tic-Tac-Toe",
        "file": "examples/agent-projects/tictactoe.py",
        "prompt": """Create a terminal Tic-Tac-Toe game at examples/agent-projects/tictactoe.py.
Two-player (X and O), 3x3 grid, terminal display with numbered cells.
Detect wins (rows/cols/diagonals) and draws. Input validation.
Single self-contained file. Show the board after each move."""},
]


async def build_project(agent: Agent, project: dict, idx: int, total: int):
    print(f"\n{'='*60}")
    print(f"[{idx}/{total}] Building: {project['name']}")
    print(f"{'='*60}")

    result = await agent.run(project["prompt"])
    print(f"\nAgent response:\n{result[:300]}...")

    if os.path.exists(project["file"]):
        size = os.path.getsize(project["file"])
        lines = len(open(project["file"]).readlines())
        print(f"\n✅ {project['name']}: {project['file']} ({lines} lines, {size} bytes)")
    else:
        print(f"\n⚠ {project['name']}: file not created")

    agent.clear()


async def main():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("Set DEEPSEEK_API_KEY environment variable.")
        sys.exit(1)

    agent = Agent(
        prompt=Prompt("""You are a game developer and RL engineer.
Create complete, runnable Python code. Use file tools (write_file) to create the files.
Write ALL code — no placeholders, no TODOs, no '...'. Every file must be self-contained and runnable.
Be thorough: include __main__ guards, proper imports, error handling."""),
        config=Config(
            model="deepseek-chat", api_key=key, workspace=".",
            provider="deepseek", api_base_url="https://api.deepseek.com/v1",
        ),
    )
    agent.load_skill("files")

    total = len(PROJECTS)
    for i, project in enumerate(PROJECTS, 1):
        await build_project(agent, project, i, total)

    print(f"\n{'='*60}")
    print("All projects built!")
    print(f"{'='*60}")
    for p in PROJECTS:
        status = "✅" if os.path.exists(p["file"]) else "❌"
        print(f"  {status} {p['name']}: python {p['file']}")


if __name__ == "__main__":
    asyncio.run(main())
