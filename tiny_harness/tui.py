# tiny_harness/tui.py
"""Rich TUI mode — full-featured terminal UI with markdown rendering, scrollable conversation."""
import asyncio
import time

from rich.console import RenderableType
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.markdown import Markdown
from rich.style import Style

from tiny_harness._core import Agent

# ── Theme ────────────────────────────────────────────────────────────────────
HEADER_BG = "#0d1117"
BORDER_C = "#30363d"
USER_C = "#58a6ff"
AGENT_C = "#c9d1d9"
TOOL_C = "#d29922"
ERROR_C = "#f85149"
SUCCESS_C = "#3fb950"
DIM_C = "#8b949e"
BG = "#0d1117"

HEADER_STYLE = Style(color="#f0f6fc", bgcolor=HEADER_BG, bold=True)
BORDER_STYLE = Style(color=BORDER_C)
USER_STYLE = Style(color=USER_C, bold=True)
AGENT_STYLE = Style(color=AGENT_C)
TOOL_STYLE = Style(color=TOOL_C)
ERROR_STYLE = Style(color=ERROR_C)
SUCCESS_STYLE = Style(color=SUCCESS_C)
DIM_STYLE = Style(color=DIM_C, italic=True)


class TuiSession:
    def __init__(self, agent: Agent, model: str):
        self.agent = agent
        self.model = model
        self.conversation: list[RenderableType] = []
        self.iteration = 0
        self.max_iterations = agent._config.max_iterations
        self.tokens_used = 0
        self.tool_calls_count = 0
        self.errors_count = 0
        self.start_time = time.time()
        self._build_layout()

    def _build_layout(self):
        self.layout = Layout()
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="input", size=3),
        )

    def _header(self) -> Panel:
        elapsed = time.time() - self.start_time
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style=Style(color=USER_C, bold=True), width=16)
        grid.add_column(style=Style(color=AGENT_C), width=24)
        grid.add_column(style=Style(color=DIM_C), justify="right", width=18)
        grid.add_column(style=Style(color=TOOL_C), justify="right", width=12)
        grid.add_column(style=Style(color=DIM_C), justify="right", width=10)

        grid.add_row(
            " tiny-harness",
            f" {self.model}",
            f"Iter {self.iteration}/{self.max_iterations}",
            f"{self.tool_calls_count} calls",
            f"{elapsed:.0f}s",
        )
        return Panel(grid, style=BORDER_STYLE, padding=(0, 1))

    def _conversation(self, user_input: str = "") -> Panel:
        parts: list[RenderableType] = []

        if not self.conversation and not user_input:
            welcome = Markdown(
                "# tiny-harness\n\n"
                "Type your prompt below and press **Enter**.\n\n"
                "Commands: `/help` `/tools` `/clear` `/save` `/exit`"
            )
            return Panel(welcome, border_style=BORDER_STYLE, padding=(1, 2))

        parts.extend(self.conversation[-50:])

        if user_input:
            parts.append(Text(""))
            parts.append(Panel(
                Text(f"> {user_input}", style=USER_STYLE),
                border_style=Style(color=USER_C),
                padding=(0, 1),
            ))

        from rich.console import Group
        return Panel(
            Group(*parts),
            border_style=BORDER_STYLE,
            padding=(1, 1),
        )

    def _input_line(self) -> Panel:
        return Panel(
            Text("> ", style=DIM_STYLE),
            border_style=Style(color=SUCCESS_C),
            padding=(0, 1),
            title="Prompt",
            title_align="left",
        )

    def render(self, user_input: str = "") -> None:
        self.layout["header"].update(self._header())
        self.layout["body"].update(self._conversation(user_input))
        self.layout["input"].update(self._input_line())

    # ── Message builders ───────────────────────────────────────────────────

    def add_user(self, content: str) -> None:
        self.conversation.append(Text(""))
        self.conversation.append(Panel(
            Markdown(content),
            border_style=Style(color=USER_C),
            title="You",
            title_align="left",
            padding=(0, 1),
        ))

    def add_assistant_text(self, text: str) -> None:
        self.conversation.append(Text(""))
        self.conversation.append(Panel(
            Markdown(text, code_theme="github-dark"),
            border_style=Style(color=BORDER_C),
            title="Agent",
            title_align="left",
            padding=(0, 1),
        ))

    def add_tool_call(self, tool_name: str, args_str: str, duration_ms: int | None = None) -> None:
        content = Text()
        content.append("⚡ ", style=TOOL_STYLE)
        content.append(tool_name, style=Style(color=TOOL_C, bold=True))

        try:
            import json
            args = json.loads(args_str)
            short = " ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])
            content.append(f"  {short}", style=DIM_STYLE)
        except Exception:
            pass

        if duration_ms is not None:
            content.append(f"  ({duration_ms}ms)", style=DIM_STYLE)

        self.conversation.append(content)
        self.tool_calls_count += 1

    def add_tool_result(self, result: str) -> None:
        self.conversation.append(Text(f"     {result[:120]}", style=SUCCESS_STYLE))

    def add_error(self, message: str) -> None:
        self.conversation.append(Panel(
            Text(message, style=ERROR_STYLE),
            border_style=Style(color=ERROR_C),
            padding=(0, 1),
        ))
        self.errors_count += 1

    def update_status(self, iteration: int, tokens: int) -> None:
        self.iteration = iteration
        self.tokens_used = tokens


async def run_tui_session(agent: Agent, model: str):
    if not _rich_available():
        print("Error: 'rich' library required. Install with: pip install rich")
        return

    tui = TuiSession(agent, model)
    screen = True

    with Live(tui.layout, refresh_per_second=15, screen=screen) as live:
        tui.render()
        live.refresh()

        while True:
            try:
                user_input = await asyncio.to_thread(input, "> ")
            except (KeyboardInterrupt, EOFError):
                tui.conversation.append(Text("\nSession ended.", style=DIM_STYLE))
                tui.render()
                live.refresh()
                await asyncio.sleep(1)
                return

            prompt = user_input.strip()
            if not prompt:
                continue

            if prompt == "/exit" or prompt == "/quit":
                tui.conversation.append(Text("\nSession ended.", style=DIM_STYLE))
                tui.render()
                live.refresh()
                await asyncio.sleep(1)
                return

            if prompt == "/help":
                tui.conversation.append(Markdown(
                    "**Commands:** `/exit` `/help` `/tools` `/clear` `/save` `/history`"
                ))
                tui.render()
                live.refresh()
                continue

            if prompt == "/tools":
                names = agent.tools.names()
                tui.conversation.append(Panel(
                    Text(f"**{len(names)} tools:** {', '.join(names)}"),
                    border_style=BORDER_STYLE,
                ))
                tui.render()
                live.refresh()
                continue

            if prompt == "/clear":
                agent.clear()
                tui.conversation.clear()
                tui.conversation.append(Text("Conversation cleared.", style=DIM_STYLE))
                tui.iteration = 0
                tui.tokens_used = 0
                tui.tool_calls_count = 0
                tui.errors_count = 0
                tui.start_time = time.time()
                tui.render()
                live.refresh()
                continue

            if prompt == "/save":
                agent.start_session()
                sid = agent.session_id
                tui.conversation.append(Panel(
                    Text(f"Session saved: {sid} → ~/.tiny-harness/sessions/{sid}.jsonl", style=SUCCESS_STYLE),
                    border_style=Style(color=SUCCESS_C),
                ))
                tui.render()
                live.refresh()
                continue

            # Show user message
            tui.conversation.append(Text(""))
            tui.conversation.append(Panel(
                Markdown(prompt),
                border_style=Style(color=USER_C),
                title="You",
                title_align="left",
                padding=(0, 1),
            ))

            # Collect agent response
            agent_text = ""

            try:
                async for event in agent.run_stream(prompt):
                    if event.type == "iteration":
                        tui.update_status(event.num or 0, agent._messages.estimate_tokens())
                    elif event.type == "text_delta" and event.content:
                        agent_text += event.content
                    elif event.type == "tool_start":
                        tui.add_tool_call(event.tool_name or "?", event.content or "")
                    elif event.type == "tool_end" and event.content:
                        tui.add_tool_result(event.content)
                    elif event.type == "error":
                        tui.add_error(event.message or "unknown error")

                    tui.render()
                    live.refresh()

                if agent_text.strip():
                    tui.conversation.append(Text(""))
                    tui.conversation.append(Panel(
                        Markdown(agent_text.strip(), code_theme="github-dark"),
                        border_style=Style(color=BORDER_C),
                        title="Agent",
                        title_align="left",
                        padding=(0, 1),
                    ))

            except Exception as e:
                tui.add_error(str(e))

            tui.conversation.append(Text(""))
            tui.render()
            live.refresh()


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False
