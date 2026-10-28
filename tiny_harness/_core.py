# tiny_harness/_core.py
import importlib.util
import asyncio
import json
from datetime import datetime, timezone
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
from tiny_harness._hitl import ApprovalGate, ApprovalHandler


class Agent:
    def __init__(self, prompt: Prompt, config: AgentConfig, store: SessionStore | None = None):
        self._config = config
        self._prompt = prompt
        if config.shell_sandbox not in ("off", "bubblewrap"):
            raise ValueError(f"Invalid shell_sandbox: {config.shell_sandbox!r}")
        if config.context_window <= config.max_tokens:
            raise ValueError("context_window must exceed max_tokens (reserved output budget)")
        self._messages = MessageManager(
            prompt, max_input_tokens=config.context_window - config.max_tokens,
        )
        self._llm_provider = self._create_provider(config)
        self._tool_registry = ToolRegistry()
        self._guard = FilesystemGuard(config.workspace)
        self._event_bus = EventBus()
        self._approval_gate = ApprovalGate(
            timeout_ms=config.approval_timeout_ms,
            require_approval_for=set(config.require_approval_for) if config.require_approval_for else None,
        ) if not config.no_hitl else None
        self._tool_executor = ToolExecutor(
            self._tool_registry, self._guard, config.timeout_ms, config.max_tool_result_chars,
            approval_gate=self._approval_gate,
            event_bus=self._event_bus,
            allow_unsafe_shell=config.allow_unsafe_shell,
        )
        self._loaded_skills: list[str] = []
        self._running = False
        self._store = store
        self._session_id: str | None = None
        self._chat_id = 0

    def _create_provider(self, config: AgentConfig):
        match config.provider:
            case "anthropic":
                return AnthropicProvider(config.api_key, config.model, max_tokens=config.max_tokens, base_url=config.api_base_url or "https://api.anthropic.com/v1")
            case "openai" | "deepseek":
                defaults = {
                    "openai": "https://api.openai.com/v1",
                    "deepseek": "https://api.deepseek.com/v1",
                }
                base_url = config.api_base_url or defaults[config.provider]
                return OpenAIProvider(config.api_key, config.model, base_url=base_url, max_tokens=config.max_tokens)
            case _:
                raise ValueError(f"Unknown provider: {config.provider}")

    @property
    def tools(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def events(self) -> EventBus:
        return self._event_bus

    @property
    def approval_gate(self) -> ApprovalGate | None:
        return self._approval_gate

    def set_approval_handler(self, handler: ApprovalHandler) -> None:
        if self._approval_gate is not None:
            self._approval_gate.handler = handler

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
        if (self._config.no_hitl and not self._config.allow_unsafe_shell
                and skill_ref in ("shell", "tiny_harness.skills.shell")):
            raise ValueError(
                "Shell skill without HITL requires allow_unsafe_shell=True. "
                "Shell commands are not OS-sandboxed."
            )
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
            result = await loop.run(prompt)
            self._dump_conversation()
            return result
        finally:
            self._running = False

    async def run_stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        if self._running:
            raise RuntimeError("Agent is already running a task")
        self._running = True
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

        async def collector(event: StreamEvent):
            queue.put_nowait(event)

        unsubscribe = self._event_bus.subscribe(collector)
        task: asyncio.Task[str] | None = None
        try:
            loop = AgentLoop(self._config, self._messages, self._llm_provider, self._tool_executor, self._event_bus)
            task = asyncio.create_task(loop.run(prompt))
            while True:
                if not queue.empty():
                    yield queue.get_nowait()
                    continue
                if task.done():
                    break

                waiting = asyncio.create_task(queue.get())
                try:
                    done, _ = await asyncio.wait((waiting, task), return_when=asyncio.FIRST_COMPLETED)
                    if waiting in done:
                        yield waiting.result()
                finally:
                    if not waiting.done():
                        waiting.cancel()
                        try:
                            await waiting
                        except asyncio.CancelledError:
                            pass

            final_text = await task
            # Match run(): store the final answer, not intermediate tool-turn text.
            self._dump_conversation()
        finally:
            unsubscribe()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._running = False

    def clear(self) -> None:
        self._messages.clear()
        if self._approval_gate is not None:
            self._approval_gate.session.clear()

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
                    tc_list = []
                    for i, tc in enumerate(tool_calls):
                        arguments = tc.get("arguments", {})
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        tc_list.append(ToolCallRequest(
                            id=tc.get("id") or f"call_{i}",
                            name=tc["name"],
                            arguments=arguments,
                        ))
                self._messages.add_assistant(text=content, tool_calls=tc_list)
                if tool_results:
                    for index, tr in enumerate(tool_results):
                        tr_id = tr.get("id") or tr.get("tool_call_id") or (
                            tc_list[index].id if tc_list and index < len(tc_list) else ""
                        )
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
        records: list[dict] = []
        index = 1
        while index < len(messages):
            msg = messages[index]
            role = msg.get("role")
            record = {
                "schema_version": 1,
                "session_id": self._session_id,
                "chat_id": len(records) + 1,
                "role": role,
                "model": self._config.model,
            }
            if role == "user":
                record["content"] = msg.get("content", "")
                records.append(record)
                index += 1
            elif role == "assistant":
                if msg.get("content") is not None:
                    record["content"] = msg["content"]
                raw_calls = msg.get("tool_calls") or []
                if raw_calls:
                    record["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "arguments": json.loads(tc["function"]["arguments"])
                            if isinstance(tc["function"]["arguments"], str)
                            else tc["function"]["arguments"],
                        }
                        for tc in raw_calls
                    ]
                results = []
                index += 1
                while index < len(messages) and messages[index].get("role") == "tool":
                    tool = messages[index]
                    results.append({
                        "id": tool["tool_call_id"],
                        "content": tool.get("content", ""),
                    })
                    index += 1
                if results:
                    record["tool_results"] = results
                records.append(record)
            else:
                index += 1

        previous = self._store.load_session(self._session_id)
        for offset, record in enumerate(records):
            if offset < len(previous) and previous[offset].get("timestamp"):
                record["timestamp"] = previous[offset]["timestamp"]
            else:
                record["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._store.replace_turns(self._session_id, records)
        self._chat_id = len(records)
        return self._chat_id

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
