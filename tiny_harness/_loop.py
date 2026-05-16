# tiny_harness/_loop.py
import json
from collections import deque
from tiny_harness._config import AgentConfig
from tiny_harness._messages import MessageManager, TokenStatus
from tiny_harness._events import EventBus, StreamEvent
from tiny_harness._tools import ToolExecutor, ToolResult
from tiny_harness._llm import ToolCallRequest


class ErrorBudget:
    def __init__(self, max_total: int = 10, max_consecutive: int = 3):
        self.max_total = max_total
        self.max_consecutive = max_consecutive
        self.total_errors = 0
        self.consecutive_errors = 0

    def record_error(self) -> bool:
        self.total_errors += 1
        self.consecutive_errors += 1
        return self.total_errors < self.max_total and self.consecutive_errors < self.max_consecutive

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def reset(self) -> None:
        self.total_errors = 0
        self.consecutive_errors = 0


class LoopDetector:
    def __init__(self, max_repeats: int = 3):
        self.max_repeats = max_repeats
        self._recent: deque[tuple[str, str]] = deque(maxlen=20)

    def check(self, tool_name: str, args: dict) -> bool:
        signature = (tool_name, json.dumps(args, sort_keys=True))
        self._recent.append(signature)
        count = sum(1 for s in self._recent if s == signature)
        return count < self.max_repeats

    def reset(self) -> None:
        self._recent.clear()


class AgentLoop:
    def __init__(self, config: AgentConfig, messages: MessageManager, llm, tools: ToolExecutor, events: EventBus):
        self._config = config
        self._messages = messages
        self._llm = llm
        self._tools = tools
        self._events = events

    async def run(self, user_prompt: str) -> str:
        self._messages.add_user(user_prompt)
        collected_text: list[str] = []
        error_budget = ErrorBudget(max_total=self._config.max_errors, max_consecutive=self._config.max_consecutive_errors)
        loop_detector = LoopDetector()

        for iteration in range(1, self._config.max_iterations + 1):
            token_estimate = self._messages.estimate_tokens()
            await self._events.emit(StreamEvent(type="iteration", num=iteration, max=self._config.max_iterations, content=f"{token_estimate // 1000}K"))

            tool_calls: list[ToolCallRequest] = []
            try:
                async for chunk in self._llm.generate_stream(self._messages.to_list(), None):
                    if chunk.type == "text_delta" and chunk.content:
                        collected_text.append(chunk.content)
                        await self._events.emit(StreamEvent(type="text_delta", content=chunk.content))
                    elif chunk.type == "tool_call_end" and chunk.tool_call:
                        tool_calls.append(chunk.tool_call)
            except Exception as e:
                await self._events.emit(StreamEvent(type="error", message=f"LLM error: {e}"))
                return f"Agent stopped due to LLM error: {e}"

            if not tool_calls:
                return "".join(collected_text)

            self._messages.add_assistant(text="".join(collected_text) if collected_text else None, tool_calls=tool_calls)
            collected_text = []

            for tc in tool_calls:
                if not loop_detector.check(tc.name, tc.arguments):
                    result = ToolResult.error(tc.id, f"You've called '{tc.name}' with the same arguments {loop_detector.max_repeats} times. Try a different approach.")
                else:
                    await self._events.emit(StreamEvent(type="tool_start", tool_name=tc.name, content=json.dumps(tc.arguments)))
                    result = await self._tools.execute(tc.name, tc.arguments, tc.id)
                    await self._events.emit(StreamEvent(type="tool_end", tool_name=tc.name, content=result.content[:100]))

                if result.success:
                    error_budget.record_success()
                else:
                    if not error_budget.record_error():
                        return await self._degraded_finish(collected_text)
                self._messages.add_tool_result(result.tool_call_id, result.content)

            status = self._messages.check_context()
            if status == TokenStatus.NEAR_CAPACITY:
                await self._events.emit(StreamEvent(type="error", message="Context near limit"))

        return await self._degraded_finish(collected_text)

    async def _degraded_finish(self, collected_text: list[str]) -> str:
        self._messages.add_system_notice("You've reached a safety limit. Please provide your best final answer based on what you know, without using any tools.")
        try:
            result = await self._llm.generate(self._messages.to_list(), tools=[])
            return result.text or "".join(collected_text)
        except Exception:
            return "".join(collected_text) or "Agent stopped."
