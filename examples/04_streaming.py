#!/usr/bin/env python3
"""Example 4: Streaming events.

Stream the agent's output in real-time with event types.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/04_streaming.py
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

    # Subscribe to events
    agent.on("iteration", lambda e: print(f"\n[Iter {e.num}/{e.max}]"))
    agent.on("tool_start", lambda e: print(f"  ⚡ {e.tool_name}"))
    agent.on("error", lambda e: print(f"  ⚠ {e.message}"))

    print("Streaming response:")
    async for event in agent.run_stream("Write a haiku about programming."):
        if event.type == "text_delta" and event.content:
            print(event.content, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())
