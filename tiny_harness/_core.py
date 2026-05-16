# tiny_harness/_core.py
import importlib.util
import asyncio
from pathlib import Path
from types import ModuleType
from collections.abc import AsyncIterator

from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._messages import MessageManager
from tiny_harness._llm import AnthropicProvider, OpenAIProvider
from tiny_harness._tools import ToolRegistry, ToolExecutor
from tiny_harness._guard import FilesystemGuard
from tiny_harness._events import EventBus, StreamEvent
from tiny_harness._loop import AgentLoop
from tiny_harness._persist import SessionStore


class Agent:
    def __init__(self, prompt: Prompt, config: AgentConfig, store: SessionStore | None = None):
        self._config = config
        self._prompt = prompt
        self._messages = MessageManager(prompt)
        self._llm_provider = self._create_provider(config)
        self._tool_registry = ToolRegistry()
        self._guard = FilesystemGuard(config.workspace)
        self._tool_executor = ToolExecutor(self._tool_registry, self._guard, config.timeout_ms, config.max_tool_result_chars)
        self._event_bus = EventBus()
        self._loaded_skills: list[str] = []
        self._running = False
        self._store = store
        self._session_id: str | None = None
        self._chat_id = 0

    def _create_provider(self, config: AgentConfig):
        match config.provider:
            case "anthropic":
                return AnthropicProvider(config.api_key, config.model, max_tokens=config.max_tokens)
            case "openai" | "deepseek":
                base_url = config.api_base_url or "https://api.openai.com/v1"
                return OpenAIProvider(config.api_key, config.model, base_url=base_url, max_tokens=config.max_tokens)
            case _:
                raise ValueError(f"Unknown provider: {config.provider}")

    @property
    def tools(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def events(self) -> EventBus:
        return self._event_bus

    def on(self, event_type: str, handler) -> None:
        async def filtered(event: StreamEvent):
            if event.type == event_type:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
        self._event_bus.subscribe(filtered)

    def load_skill(self, skill_ref: str) -> None:
        if skill_ref in self._loaded_skills:
            return
        module = self._resolve_skill(skill_ref)
        if not hasattr(module, "register"):
            raise RuntimeError(f"Skill '{skill_ref}' has no register() function")
        module.register(self)
        self._loaded_skills.append(skill_ref)

    def _resolve_skill(self, ref: str) -> ModuleType:
        try:
            return importlib.import_module(f"tiny_harness.skills.{ref}")
        except ImportError:
            pass
        try:
            return importlib.import_module(ref)
        except ImportError:
            pass
        path = Path(ref)
        if path.exists():
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        raise RuntimeError(f"Skill '{ref}' not found")

    async def run(self, prompt: str) -> str:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        self._save_turn("user", content=prompt)
        try:
            loop = AgentLoop(self._config, self._messages, self._llm_provider, self._tool_executor, self._event_bus)
            result = await loop.run(prompt)
            self._save_turn("assistant", content=result)
            return result
        finally:
            self._running = False

    async def run_stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        self._save_turn("user", content=prompt)
        queue: list[StreamEvent] = []

        async def collector(event: StreamEvent):
            queue.append(event)

        self._event_bus.subscribe(collector)
        result_text = ""
        try:
            loop = AgentLoop(self._config, self._messages, self._llm_provider, self._tool_executor, self._event_bus)
            task = asyncio.create_task(loop.run(prompt))
            last_yielded = 0
            while not task.done() or last_yielded < len(queue):
                while last_yielded < len(queue):
                    event = queue[last_yielded]
                    if event.type == "text_delta" and event.content:
                        result_text += event.content
                    yield event
                    last_yielded += 1
                if not task.done():
                    await asyncio.sleep(0.01)
            await task
            self._save_turn("assistant", content=result_text if result_text else None)
        finally:
            self._running = False

    def clear(self) -> None:
        self._messages.clear()

    def start_session(self, session_id: str | None = None) -> str:
        if self._session_id is not None:
            return self._session_id
        if self._store is None:
            self._store = SessionStore()
        self._session_id = session_id or self._store.new_session()
        return self._session_id

    def resume_session(self, session_id: str) -> int:
        """Reload a conversation from a saved session. Returns number of turns restored."""
        if self._store is None:
            raise RuntimeError("No SessionStore configured. Pass store= to Agent() or call start_session() first.")
        records = self._store.load_session(session_id)
        if not records:
            raise RuntimeError(f"Session '{session_id}' not found or empty.")
        self.clear()
        self._session_id = session_id
        self._chat_id = 0
        for rec in records:
            self._chat_id += 1
            role = rec["role"]
            content = rec.get("content")
            tool_calls = rec.get("tool_calls")
            tool_results = rec.get("tool_results")
            if role == "user":
                if content:
                    self._messages.add_user(content)
            elif role == "assistant":
                tc_list = None
                if tool_calls:
                    from tiny_harness._llm import ToolCallRequest
                    tc_list = [
                        ToolCallRequest(id=tc.get("id", f"call_{i}"), name=tc["name"], arguments=tc.get("arguments", {}))
                        for i, tc in enumerate(tool_calls)
                    ]
                self._messages.add_assistant(text=content, tool_calls=tc_list)
                if tool_results:
                    for tr in tool_results:
                        tr_id = tr.get("id", "")
                        tr_content = tr.get("content", "")
                        self._messages.add_tool_result(tr_id, tr_content)
        return len(records)

    def _save_turn(self, role: str, content: str | None = None,
                   tool_calls: list | None = None,
                   tool_results: list | None = None,
                   token_usage: dict | None = None) -> None:
        if self._store is None or self._session_id is None:
            return
        self._chat_id += 1
        self._store.save_turn(
            session_id=self._session_id,
            chat_id=self._chat_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            token_usage=token_usage,
            model=self._config.model,
        )

    def _dump_conversation(self) -> int:
        if self._store is None or self._session_id is None:
            return 0
        messages = self._messages.to_list()
        count = 0
        i = 1

        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")

            if role == "user":
                count += 1
                self._store.save_turn(
                    session_id=self._session_id,
                    chat_id=count,
                    role="user",
                    content=msg.get("content", ""),
                    model=self._config.model,
                )
                i += 1

            elif role == "assistant":
                raw_tool_calls = msg.get("tool_calls")
                tool_calls = None
                if raw_tool_calls:
                    tool_calls = [
                        {"name": tc.get("function", {}).get("name", "?"), "arguments": tc.get("function", {}).get("arguments", {})}
                        for tc in raw_tool_calls
                    ]
                tool_results = []
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    tr = messages[j]
                    tool_results.append({
                        "id": tr.get("tool_call_id", ""),
                        "content": tr.get("content", ""),
                    })
                    j += 1

                count += 1
                self._store.save_turn(
                    session_id=self._session_id,
                    chat_id=count,
                    role="assistant",
                    content=msg.get("content"),
                    tool_calls=tool_calls,
                    tool_results=tool_results if tool_results else None,
                    model=self._config.model,
                )
                i = j

            elif role == "tool":
                i += 1

            else:
                i += 1

        self._chat_id = count
        return count

    @property
    def max_iterations(self) -> int:
        return self._config.max_iterations

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def store(self) -> SessionStore | None:
        return self._store

    def estimate_tokens(self) -> int:
        return self._messages.estimate_tokens()
