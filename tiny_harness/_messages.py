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
    def __init__(self, prompt: Prompt, max_input_tokens: int = 200_000):
        if max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be positive")
        # Keep the Prompt, not just a snapshot: skills can be loaded later.
        self._prompt = prompt
        self.messages: list[dict] = [{"role": "system", "content": prompt.to_string()}]
        self._token_budget = TokenBudget(max_tokens=max_input_tokens)

    @property
    def max_input_tokens(self) -> int:
        return self._token_budget.max_tokens

    def compact(self, target_tokens: int | None = None) -> dict[str, int]:
        """Bound context without breaking assistant/tool-call groupings.

        First condense oversized tool outputs, then discard complete oldest
        dialogue turns (from one user message up to the next user message).
        Never remove the current/latest user turn or the system prompt.
        """
        self._sync_system_prompt()
        target = target_tokens if target_tokens is not None else self.max_input_tokens
        target = min(max(1, target), self.max_input_tokens)
        before = self.estimate_tokens()
        shortened = removed = 0
        if before <= target:
            return {"before": before, "after": before, "shortened": 0, "removed": 0}

        for message in self.messages[1:]:
            if self.estimate_tokens() <= target:
                break
            if message.get("role") != "tool":
                continue
            content = message.get("content")
            if not isinstance(content, str) or len(content) <= 1200:
                continue
            message["content"] = (
                content[:450] + "\n[... older tool result compacted ...]\n" + content[-450:]
            )
            shortened += 1

        while self.estimate_tokens() > target:
            # Find the next user turn: the initial completed turn is everything
            # before it. Never split an assistant tool_calls/result pair.
            next_user = next(
                (i for i in range(2, len(self.messages))
                 if self.messages[i].get("role") == "user"),
                None,
            )
            if next_user is None:
                break
            del self.messages[1:next_user]
            removed += 1

        return {
            "before": before, "after": self.estimate_tokens(),
            "shortened": shortened, "removed": removed,
        }

    def _sync_system_prompt(self) -> None:
        self.messages[0]["content"] = self._prompt.to_string()

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
        self._sync_system_prompt()
        return self.messages

    def estimate_tokens(self) -> int:
        self._sync_system_prompt()
        return sum(len(json.dumps(m)) // 4 for m in self.messages)

    def check_context(self) -> TokenStatus:
        self._sync_system_prompt()
        return self._token_budget.check(self.messages)

    def clear(self) -> None:
        self.messages = [{"role": "system", "content": self._prompt.to_string()}]
