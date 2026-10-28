# tiny_harness/_events.py
import logging
from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from typing import Any


@dataclass(frozen=True)
class StreamEvent:
    type: str
    content: str | None = None
    tool_name: str | None = None
    duration_ms: int | None = None
    num: int | None = None
    max: int | None = None
    message: str | None = None


class EventBus:
    def __init__(self):
        self._handlers: list[Callable[[StreamEvent], Awaitable[Any]]] = []

    def subscribe(self, handler: Callable[[StreamEvent], Awaitable[Any]]) -> None:
        self._handlers.append(handler)

    async def emit(self, event: StreamEvent) -> None:
        for handler in tuple(self._handlers):
            try:
                await handler(event)
            except Exception:
                logging.getLogger(__name__).exception("Event subscriber failed for %s", event.type)
