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


class Agent:
    def __init__(self, prompt: Prompt, config: AgentConfig):
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

    def _create_provider(self, config: AgentConfig):
        match config.provider:
            case "anthropic":
                return AnthropicProvider(config.api_key, config.model)
            case "openai" | "deepseek":
                base_url = config.api_base_url or "https://api.openai.com/v1"
                return OpenAIProvider(config.api_key, config.model, base_url=base_url)
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
                await handler(event)
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
        try:
            loop = AgentLoop(self._config, self._messages, self._llm_provider, self._tool_executor, self._event_bus)
            return await loop.run(prompt)
        finally:
            self._running = False

    async def run_stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        queue: list[StreamEvent] = []

        async def collector(event: StreamEvent):
            queue.append(event)

        self._event_bus.subscribe(collector)
        try:
            loop = AgentLoop(self._config, self._messages, self._llm_provider, self._tool_executor, self._event_bus)
            task = asyncio.create_task(loop.run(prompt))
            last_yielded = 0
            while not task.done() or last_yielded < len(queue):
                while last_yielded < len(queue):
                    yield queue[last_yielded]
                    last_yielded += 1
                if not task.done():
                    await asyncio.sleep(0.01)
            await task
        finally:
            self._running = False

    def clear(self) -> None:
        self._messages.clear()
