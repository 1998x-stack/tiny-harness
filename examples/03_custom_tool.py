#!/usr/bin/env python3
"""Example 3: Custom tool registration.

Register a custom tool and let the agent use it.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/03_custom_tool.py
"""

import asyncio
import os
import json
from tiny_harness import Agent, Prompt, Config, ToolDef


async def main():
    agent = Agent(
        prompt=Prompt("You have a calculator tool. Use it for math questions."),
        config=Config(
            model="deepseek-v4-flash",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".",
            provider="deepseek",
            api_base_url="https://api.deepseek.com/v1",
        ),
    )

    # Register a custom calculator tool
    agent.tools.register_from_def(
        ToolDef(
            name="calculate",
            description="Evaluate a mathematical expression and return the result.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate (e.g. '2+3*4')",
                    }
                },
                "required": ["expression"],
            },
        ),
        handler=lambda expression: str(eval(expression)),
    )

    result = await agent.run("What is 15 * 7 + 23?")
    print(f"Agent: {result}")


if __name__ == "__main__":
    asyncio.run(main())
