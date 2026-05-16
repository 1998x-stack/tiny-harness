# tiny_harness/tui.py
"""Rich TUI mode for tiny-harness — real-time streaming display with panels."""
import asyncio
import time
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.console import RenderableType
from rich.style import Style
from tiny_harness._core import Agent


HEADER_STYLE = "bold white on #1a1a2e"
TOOL_STYLE = Style(color="#e6b450")
ERROR_STYLE = Style(color="#e05555")
SUCCESS_STYLE = Style(color="#55b555")
TEXT_STYLE = Style(color="#c8d6e5")
USER_STYLE = Style(color="#5dade2", bold=True)
TOKEN_STYLE = Style(color="#888888", italic=True)
BORDER_STYLE = Style(color="#2d2d5e")


class TuiSession:
    """Rich TUI display for an agent session."""

    def __init__(self, agent: Agent, model: str):
        self.agent = agent
        self.model = model
        self.layout = self._build_layout()
        self.conversation_lines: list[RenderableType] = []
        self.iteration = 0
        self.max_iterations = agent._config.max_iterations
        self.tokens_used = 0
        self.start_time = time.time()

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="input", size=3),
        )
        layout["body"].split(
            Layout(name="conversation"),
        )
        return layout

    def _render_header(self) -> Panel:
        elapsed = time.time() - self.start_time
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style=HEADER_STYLE, width=30)
        table.add_column(style=HEADER_STYLE, justify="center", width=20)
        table.add_column(style=HEADER_STYLE, justify="right", width=25)
        table.add_row(
            f"  tiny-harness  │  {self.model}",
            f"Iter {self.iteration}/{self.max_iterations}",
            f"{self.tokens_used // 1000}K tokens  │  {elapsed:.0f}s  ",
        )
        return Panel(table, style=BORDER_STYLE, padding=0)

    def _render_conversation(self) -> Panel:
        if not self.conversation_lines:
            welcome = Text("Welcome to tiny-harness TUI mode.\nType your prompt below and press Enter.\n", style=TEXT_STYLE)
            return Panel(welcome, title="Conversation", border_style=BORDER_STYLE)

        from rich.console import Group
        return Panel(
            Group(*self.conversation_lines[-40:]),
            title="Conversation",
            border_style=BORDER_STYLE,
        )

    def _render_input(self, current_input: str) -> Panel:
        if current_input:
            text = Text(f"> {current_input}_", style=USER_STYLE)
        else:
            text = Text("> _", style=Style(color="#666666"))
        return Panel(text, border_style=BORDER_STYLE, padding=(0, 1))

    def add_user_message(self, content: str) -> None:
        self.conversation_lines.append(Text(f"\nYou: {content}", style=USER_STYLE))
        self.conversation_lines.append(Text(""))

    def add_text_delta(self, content: str) -> None:
        if self.conversation_lines and isinstance(self.conversation_lines[-1], Text) and self.conversation_lines[-1].style == TEXT_STYLE:
            self.conversation_lines[-1].append(content)
        else:
            self.conversation_lines.append(Text(content, style=TEXT_STYLE))

    def add_tool_start(self, tool_name: str, args_str: str) -> None:
        spinner = Text("  ⚡ ", style=TOOL_STYLE)
        spinner.append(f"{tool_name}", style=TOOL_STYLE)
        try:
            import json
            args = json.loads(args_str)
            short = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:2])
            spinner.append(f"  {short}", style=Style(color="#888888"))
        except Exception:
            pass
        self.conversation_lines.append(spinner)

    def add_tool_end(self, tool_name: str, result_summary: str) -> None:
        summary_text = Text("     ", style=TOOL_STYLE)
        summary_text.append(result_summary[:80], style=SUCCESS_STYLE)
        self.conversation_lines.append(summary_text)

    def add_error(self, message: str) -> None:
        self.conversation_lines.append(Text(f"  ⚠ {message}", style=ERROR_STYLE))

    def update_status(self, iteration: int, tokens: int) -> None:
        self.iteration = iteration
        self.tokens_used = tokens

    def render(self, user_input: str = "") -> None:
        self.layout["header"].update(self._render_header())
        self.layout["body"]["conversation"].update(self._render_conversation())
        self.layout["input"].update(self._render_input(user_input))


async def run_tui_session(agent: Agent, model: str):
    """Run an interactive TUI session."""
    if not _rich_available():
        print("Error: 'rich' library required for TUI mode. Install with: pip install rich")
        return

    tui = TuiSession(agent, model)
    user_input = ""

    with Live(tui.layout, refresh_per_second=10, screen=True) as live:
        tui.render()
        live.refresh()

        # Handle initial welcome
        await asyncio.sleep(0.1)

        while True:
            # Wait for user input (polling approach for non-blocking)
            prompt_shown = False
            while True:
                tui.render(user_input)
                live.refresh()
                if not prompt_shown:
                    live.console.print("")  # Keep cursor at input line
                    prompt_shown = True
                try:
                    char = await _get_char_async()
                except (KeyboardInterrupt, EOFError):
                    return

                if char is None:
                    await asyncio.sleep(0.05)
                    continue

                if char == "\n" or char == "\r":
                    if user_input.strip():
                        break
                elif char == "\x03":  # Ctrl+C
                    return
                elif char == "\x7f" or char == "\x08":  # Backspace
                    user_input = user_input[:-1]
                elif len(char) == 1 and ord(char) >= 32:
                    user_input += char

            prompt = user_input.strip()
            user_input = ""

            if not prompt:
                continue

            if prompt == "/exit" or prompt == "/quit":
                tui.conversation_lines.append(Text("\nSession ended.", style=TEXT_STYLE))
                tui.render()
                live.refresh()
                await asyncio.sleep(1)
                return

            if prompt == "/help":
                tui.conversation_lines.append(Text("\nCommands: /exit, /help, /tools, /clear", style=TEXT_STYLE))
                tui.render()
                live.refresh()
                continue

            if prompt == "/tools":
                names = agent.tools.names()
                tui.conversation_lines.append(Text(f"\nTools ({len(names)}): {', '.join(names)}", style=TEXT_STYLE))
                tui.render()
                live.refresh()
                continue

            if prompt == "/clear":
                agent.clear()
                tui.conversation_lines.clear()
                tui.conversation_lines.append(Text("Conversation cleared.", style=TEXT_STYLE))
                tui.iteration = 0
                tui.tokens_used = 0
                tui.start_time = time.time()
                tui.render()
                live.refresh()
                continue

            # Display user message
            tui.add_user_message(prompt)
            tui.render()
            live.refresh()

            # Run agent with streaming
            try:
                async for event in agent.run_stream(prompt):
                    if event.type == "iteration":
                        tui.update_status(event.num or 0, agent._messages.estimate_tokens())
                    elif event.type == "text_delta" and event.content:
                        tui.add_text_delta(event.content)
                    elif event.type == "tool_start":
                        tui.add_tool_start(event.tool_name or "?", event.content or "")
                    elif event.type == "tool_end" and event.content:
                        tui.add_tool_end(event.tool_name or "?", event.content)
                    elif event.type == "error":
                        tui.add_error(event.message or "unknown error")

                    tui.render()
                    live.refresh()
            except Exception as e:
                tui.add_error(str(e))
                tui.render()
                live.refresh()

            tui.conversation_lines.append(Text(""))


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


async def _get_char_async() -> str | None:
    """Non-blocking single character input for TUI."""
    import sys
    import tty
    import termios
    import select

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        r, _, _ = select.select([sys.stdin], [], [], 0.05)
        if r:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
