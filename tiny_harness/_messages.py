# tiny_harness/_messages.py
import json
from enum import Enum, auto
from tiny_harness._config import Prompt
from tiny_harness._llm import ToolCallRequest


class TokenStatus(Enum):
    OK = auto()
    NEAR_CAPACITY = auto()
    OVER_CAPACITY = auto()


class TokenBudget:
    def __init__(self, max_tokens: int = 200_000, warn_threshold: float = 0.8):
        self.max_tokens = max_tokens
        self.warn_threshold = warn_threshold

    def check(self, messages: list[dict]) -> TokenStatus:
        used = sum(len(json.dumps(m)) // 4 for m in messages)
        if used > self.max_tokens:
            return TokenStatus.OVER_CAPACITY
        if used > self.max_tokens * self.warn_threshold:
            return TokenStatus.NEAR_CAPACITY
        return TokenStatus.OK


class MessageManager:
    def __init__(self, prompt: Prompt):
        self.messages: list[dict] = [{"role": "system", "content": prompt.to_string()}]
        self._token_budget = TokenBudget()

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, text: str | None, tool_calls: list[ToolCallRequest] | None = None) -> None:
        msg: dict = {"role": "assistant"}
        if text:
            msg["content"] = text
        else:
            msg["content"] = None
        if tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    def add_system_notice(self, notice: str) -> None:
        self.messages.append({"role": "user", "content": f"[System Notice] {notice}"})

    def to_list(self) -> list[dict]:
        return self.messages

    def estimate_tokens(self) -> int:
        return sum(len(json.dumps(m)) // 4 for m in self.messages)

    def check_context(self) -> TokenStatus:
        return self._token_budget.check(self.messages)

    def clear(self) -> None:
        system = self.messages[0]
        self.messages = [system]
