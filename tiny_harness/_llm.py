# tiny_harness/_llm.py
from dataclasses import dataclass
from collections.abc import AsyncIterator
from abc import ABC, abstractmethod


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCallRequest]
    usage: TokenUsage
    finish_reason: str

    def is_final(self) -> bool:
        return len(self.tool_calls) == 0


@dataclass
class LLMStreamChunk:
    type: str
    content: str | None = None
    tool_call: ToolCallRequest | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def generate_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[LLMStreamChunk]:
        ...
