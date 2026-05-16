# tiny_harness/cli.py
import os
import sys
import asyncio
from argparse import ArgumentParser, Namespace


def parse_args() -> Namespace:
    parser = ArgumentParser(prog="tiny-harness", description="AI agent harness with tools and streaming CLI")
    parser.add_argument("prompt", nargs="?", default=None, help="Prompt for one-shot mode")
    parser.add_argument("--model", "-m", default="deepseek-chat", help="Model identifier")
    parser.add_argument("--workspace", "-w", default=os.getcwd(), help="Workspace directory")
    parser.add_argument("--provider", default="deepseek", help="LLM provider: anthropic, openai, deepseek")
    parser.add_argument("--api-base-url", default="https://api.deepseek.com/v1", help="Custom API base URL")
    parser.add_argument("--max-iterations", type=int, default=25, help="Max loop iterations")
    parser.add_argument("--skills", default="", help="Comma-separated skill names")
    parser.add_argument("--tui", action="store_true", help="Use rich TUI mode (requires 'rich' package)")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY", help="Env var for API key")
    return parser.parse_args()


def _get_api_key(args: Namespace) -> str:
    key = os.environ.get(args.api_key_env)
    if not key:
        print(f"Error: API key not found. Set {args.api_key_env} environment variable.", file=sys.stderr)
        sys.exit(1)
    return key


async def _run_one_shot(args: Namespace, agent):
    async for event in agent.run_stream(args.prompt):
        if event.type == "text_delta" and event.content:
            print(event.content, end="", flush=True)
        elif event.type == "tool_start":
            print(f"\n  ⚡ {event.tool_name}", end="", flush=True)
        elif event.type == "tool_end" and event.content:
            print(f"  ({event.content})", flush=True)
        elif event.type == "error" and event.message:
            print(f"\n  ⚠ {event.message}")
    print()


async def _run_session(args: Namespace, agent):
    print("tiny-harness session. Type /exit to quit, /help for commands.\n")

    while True:
        try:
            user_input = await _async_input("> ")
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input == "/exit" or user_input == "/quit":
            break
        if user_input == "/help":
            print("Commands: /exit, /help, /tools, /clear")
            continue
        if user_input == "/tools":
            tools = agent.tools.names()
            print(f"Tools ({len(tools)}): {', '.join(tools)}")
            continue
        if user_input == "/clear":
            agent.clear()
            print("Conversation cleared.")
            continue

        async for event in agent.run_stream(user_input):
            if event.type == "iteration":
                tokens = event.content or "?"
                print(f"\n[Iter {event.num}/{event.max} | Tokens: {tokens}]")
            elif event.type == "text_delta" and event.content:
                print(event.content, end="", flush=True)
            elif event.type == "tool_start":
                print(f"\n  ⚡ {event.tool_name}", end="", flush=True)
            elif event.type == "tool_end" and event.content:
                print(f"  ({event.content})", flush=True)
            elif event.type == "error" and event.message:
                print(f"\n  ⚠ {event.message}")
        print()


async def _async_input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


def main():
    args = parse_args()
    api_key = _get_api_key(args)

    from tiny_harness import Agent, Prompt, Config
    prompt = Prompt("You are a helpful AI assistant. Use tools when appropriate.")
    config = Config(model=args.model, api_key=api_key, workspace=args.workspace, provider=args.provider, api_base_url=args.api_base_url, max_iterations=args.max_iterations)
    agent = Agent(prompt=prompt, config=config)

    for skill_name in args.skills.split(","):
        skill_name = skill_name.strip()
        if skill_name:
            agent.load_skill(skill_name)

    if args.tui:
        from tiny_harness.tui import run_tui_session
        asyncio.run(run_tui_session(agent, args.model))
    elif args.prompt:
        asyncio.run(_run_one_shot(args, agent))
    else:
        asyncio.run(_run_session(args, agent))
