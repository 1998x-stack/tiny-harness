# tests/test_events.py
import pytest
from tiny_harness._events import StreamEvent, EventBus


def test_stream_event_creation():
    event = StreamEvent(type="text_delta", content="hello")
    assert event.type == "text_delta"
    assert event.content == "hello"
    assert event.tool_name is None

    tool_event = StreamEvent(type="tool_start", tool_name="read_file", duration_ms=12)
    assert tool_event.tool_name == "read_file"
    assert tool_event.duration_ms == 12


def test_stream_event_is_frozen():
    event = StreamEvent(type="text_delta", content="hello")
    with pytest.raises(Exception):
        event.content = "changed"


@pytest.mark.asyncio
async def test_eventbus_emit_and_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: StreamEvent):
        received.append(event)

    bus.subscribe(handler)
    event = StreamEvent(type="text_delta", content="test")
    await bus.emit(event)

    assert len(received) == 1
    assert received[0].content == "test"
