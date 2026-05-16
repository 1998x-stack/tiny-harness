#!/usr/bin/env python3
"""Let tiny-harness build a CartPole RL environment.

Usage:
    export DEEPSEEK_API_KEY="sk-..."
    python examples/build_cartpole.py
"""

import asyncio, os
from tiny_harness import Agent, Prompt, Config


async def main():
    agent = Agent(
        prompt=Prompt("""You are an RL engineer. Create complete, runnable Python code.
Use file tools to write files. Write all code — no placeholders."""),
        config=Config(
            model="deepseek-chat", api_key=os.environ["DEEPSEEK_API_KEY"],
            workspace=".", provider="deepseek", api_base_url="https://api.deepseek.com/v1",
        ),
    )
    agent.load_skill("files")

    result = await agent.run("""
Create a CartPole reinforcement learning environment at examples/agent-projects/cartpole.py.

Requirements:
- Pure Python implementation (no gym dependency, no numpy required if possible)
- Classic cart-pole physics: cart on track, pole hinged on top
- State space: [cart_position, cart_velocity, pole_angle, pole_angular_velocity]
- Action space: push left (0) or push right (1)
- Reward: +1 for every timestep the pole stays upright
- Episode ends when: |pole_angle| > 12 degrees OR |cart_position| > 2.4 OR steps > 500
- OpenAI Gym-style API: env = CartPoleEnv(); obs = env.reset(); obs, reward, done, info = env.step(action)
- Include render() method that prints the cart-pole to terminal
- Single self-contained Python file

Make it complete and runnable. Include a demo main() that runs random actions and renders.
""")
    print(f"Agent: {result}")

    path = "examples/agent-projects/cartpole.py"
    if os.path.exists(path):
        print(f"\n✅ Created: {path} ({os.path.getsize(path)} bytes)")
        print("   Run with: python examples/agent-projects/cartpole.py")
    else:
        print(f"\n❌ Not created. Check agent output.")


if __name__ == "__main__":
    asyncio.run(main())
