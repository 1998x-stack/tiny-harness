# tiny_harness/tui.py
"""Rich TUI mode — color-coded terminal UI with streaming output."""

import asyncio
import time


async def run_tui_session(agent, model: str):
    if not _rich_available():
        print("Error: 'rich' library required. Install with: pip install rich")
        return

    import rich.console
    import rich.style
    import rich.markdown

    console = rich.console.Console()
    md = rich.markdown.Markdown

    c = {
        "user": rich.style.Style(color="#58a6ff", bold=True),
        "agent": rich.style.Style(color="#c9d1d9"),
        "tool": rich.style.Style(color="#d29922"),
        "err": rich.style.Style(color="#f85149"),
        "ok": rich.style.Style(color="#3fb950"),
        "dim": rich.style.Style(color="#8b949e", italic=True),
        "bold": rich.style.Style(bold=True),
    }

    start_time = time.time()
    iteration = 0
    max_iter = agent.max_iterations

    console.print(f"  tiny-harness  |  {model}  |  max {max_iter} iter", style=c["bold"])
    console.print("  type /help for commands", style=c["dim"])
    console.print()

    while True:
        try:
            user_input = await asyncio.to_thread(input, "> ")
        except (KeyboardInterrupt, EOFError):
            console.print("Session ended.", style=c["dim"])
            return

        prompt = user_input.strip()
        if not prompt:
            continue

        if prompt == "/exit" or prompt == "/quit":
            console.print("Session ended.", style=c["dim"])
            return

        if prompt == "/help":
            console.print()
            console.print("  /exit     end session", style=c["dim"])
            console.print("  /help     show commands", style=c["dim"])
            console.print("  /tools    list available tools", style=c["dim"])
            console.print("  /clear    reset conversation", style=c["dim"])
            console.print("  /save     save session to disk", style=c["dim"])
            console.print("  /history  list saved sessions", style=c["dim"])
            console.print()
            continue

        if prompt == "/tools":
            console.print()
            names = agent.tools.names()
            for name in sorted(names):
                tool = agent.tools.get(name)
                desc = tool.definition.description if tool and tool.definition else ""
                console.print(f"  {name}", style=c["tool"], end="")
                if desc:
                    console.print(f"  {desc[:60]}", style=c["dim"])
                else:
                    console.print()
            console.print()
            continue

        if prompt == "/clear":
            agent.clear()
            iteration = 0
            start_time = time.time()
            console.print("Conversation cleared.", style=c["dim"])
            console.print()
            continue

        if prompt == "/save":
            agent.start_session()
            turns = agent._dump_conversation()
            sid = agent.session_id
            console.print(f"  Saved: {sid}  ({turns} turns)", style=c["ok"])
            console.print()
            continue

        if prompt == "/history":
            if agent.store:
                sessions = agent.store.list_sessions()
                if sessions:
                    console.print(f"  {len(sessions)} session(s):", style=c["dim"])
                    for s in sessions[:10]:
                        console.print(f"    {s['session_id']}  {s['turns']} turns  {s['model']}  {s['updated'][:19]}", style=c["dim"])
                else:
                    console.print("  No saved sessions.", style=c["dim"])
            else:
                console.print("  No sessions yet. Use /save first.", style=c["dim"])
            console.print()
            continue

        # ── Run agent ─────────────────────────────────────────────────────
        console.print("You:", style=c["user"])
        console.print(f"  {prompt}", style=c["agent"])
        console.print()

        agent_text = ""
        try:
            async for event in agent.run_stream(prompt):
                if event.type == "iteration":
                    iteration = event.num or 0
                    elapsed = int(time.time() - start_time)
                    tokens = agent.estimate_tokens()
                    tok_str = f"{tokens}" if tokens < 1000 else f"{tokens // 1000}K"
                    if agent_text.strip():
                        console.print(md(agent_text.strip(), code_theme="github-dark"))
                        agent_text = ""
                    console.print(f"  [iter {iteration}/{max_iter}  {tok_str} tok  {elapsed}s]", style=c["dim"])

                elif event.type == "text_delta" and event.content:
                    agent_text += event.content

                elif event.type == "tool_start":
                    if agent_text.strip():
                        console.print(md(agent_text.strip(), code_theme="github-dark"))
                        agent_text = ""
                    args = ""
                    if event.content:
                        try:
                            import json
                            a = json.loads(event.content)
                            args = " ".join(f"{k}={str(v)[:40]}" for k, v in list(a.items())[:3])
                        except Exception:
                            pass
                    console.print(f"  ⚡ {event.tool_name}  {args}", style=c["tool"])

                elif event.type == "tool_end" and event.content:
                    result = event.content[:200].replace("\n", " ").strip()
                    console.print(f"     {result}", style=c["ok"])

                elif event.type == "error":
                    console.print(f"  ⚠ {event.message}", style=c["err"])

            if agent_text.strip():
                console.print(md(agent_text.strip(), code_theme="github-dark"))

        except Exception as e:
            console.print(f"  ⚠ {e}", style=c["err"])

        console.print()
        agent_text = ""


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False
