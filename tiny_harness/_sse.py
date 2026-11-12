import json
from collections.abc import AsyncIterator, Callable
from typing import Any


async def anthropic_events(
    lines: AsyncIterator[str],
    parse_line: Callable[[str], tuple[str, Any] | None],
) -> AsyncIterator[dict]:
    current_event: str | None = None
    tool_buffers: dict[int, dict[str, str]] = {}
    async for line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        event_type, value = parsed
        if value is None:
            current_event = event_type
            continue
        event_type = current_event or value.get("type", event_type)
        current_event = None
        if event_type == "message_start":
            usage = value.get("message", {}).get("usage", {}).get("input_tokens", 0)
            yield {"type": "usage", "content": json.dumps({"input": usage})}
        elif event_type == "content_block_start":
            index = value.get("index", 0)
            block = value.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_buffers[index] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": "",
                }
                yield {
                    "type": "tool_call_start",
                    "content": json.dumps({"id": block["id"], "name": block["name"]}),
                }
        elif event_type == "content_block_delta":
            index = value.get("index", 0)
            delta = value.get("delta", {})
            if delta.get("type") == "text_delta":
                yield {"type": "text_delta", "content": delta.get("text", "")}
            elif delta.get("type") == "input_json_delta":
                partial = delta.get("partial_json", "")
                if index in tool_buffers:
                    tool_buffers[index]["arguments"] += partial
                yield {"type": "tool_call_delta", "content": partial}
        elif event_type == "content_block_stop":
            buffer = tool_buffers.pop(value.get("index", 0), None)
            if buffer is not None:
                try:
                    arguments = json.loads(buffer["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                yield {
                    "type": "tool_call_end",
                    "tool_call": {
                        "id": buffer["id"],
                        "name": buffer["name"],
                        "arguments": arguments,
                    },
                }


async def openai_events(lines: AsyncIterator[str]) -> AsyncIterator[dict]:
    tool_buffers: dict[int, dict[str, str]] = {}
    async for line in lines:
        line = line.strip()
        if not line or not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        choice = data.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        if delta.get("content"):
            yield {"type": "text_delta", "content": delta["content"]}

        for tool_call in delta.get("tool_calls", []):
            index = tool_call.get("index", 0)
            buffer = tool_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if tool_call.get("id"):
                buffer["id"] = tool_call["id"]
            function = tool_call.get("function", {})
            if function.get("name"):
                buffer["name"] = function["name"]
                yield {
                    "type": "tool_call_start",
                    "content": json.dumps({"id": buffer["id"], "name": buffer["name"]}),
                }
            if "arguments" in function:
                buffer["arguments"] += function["arguments"]

        if choice.get("finish_reason") in ("tool_calls", "stop"):
            for index in sorted(tool_buffers):
                buffer = tool_buffers[index]
                if buffer["name"] and buffer["arguments"]:
                    try:
                        arguments = json.loads(buffer["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}
                    yield {
                        "type": "tool_call_end",
                        "tool_call": {
                            "id": buffer["id"] or f"call_{index}",
                            "name": buffer["name"],
                            "arguments": arguments,
                        },
                    }
