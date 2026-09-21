from __future__ import annotations
import json
import asyncio
from dataclasses import dataclass
from difflib import get_close_matches
from collections.abc import Callable
from typing import TYPE_CHECKING

from tiny_harness._events import StreamEvent

if TYPE_CHECKING:
    from tiny_harness._guard import FilesystemGuard
    from tiny_harness._hitl import ApprovalGate
    from tiny_harness._events import EventBus


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    risk_level: str = "read_only"


@dataclass
class Tool:
    definition: ToolDef
    handler: Callable


@dataclass
class ToolResult:
    success: bool
    tool_call_id: str
    content: str
    denied: bool = False

    @classmethod
    def ok(cls, call_id: str, content: str) -> "ToolResult":
        return cls(success=True, tool_call_id=call_id, content=content)

    @classmethod
    def error(cls, call_id: str, message: str) -> "ToolResult":
        return cls(success=False, tool_call_id=call_id, content=message)

    @classmethod
    def denial(cls, call_id: str, reason: str) -> "ToolResult":
        return cls(success=False, tool_call_id=call_id, content=reason, denied=True)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool

    def register_from_def(self, def_: ToolDef, handler: Callable) -> None:
        self.register(Tool(definition=def_, handler=handler))

    def register_tool(self, name: str, description: str, parameters: dict, handler: Callable, risk_level: str = "read_only") -> None:
        self.register_from_def(ToolDef(name=name, description=description, parameters=parameters, risk_level=risk_level), handler)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        return [{"name": t.definition.name, "description": t.definition.description, "input_schema": t.definition.parameters} for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())


# Only the built-in filesystem tools have an explicit path contract. Arbitrary
# plugin arguments are not necessarily paths; plugin authors must sandbox any
# custom filesystem operations themselves.
_FILE_TOOLS = frozenset({
    "read_file", "write_file", "list_directory", "find_files",
    "delete_file", "create_directory", "move_file",
})


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, guard: "FilesystemGuard", timeout_ms: int = 30_000, max_output_chars: int = 50_000, approval_gate: "ApprovalGate | None" = None, event_bus: "EventBus | None" = None):
        self._registry = registry
        self._guard = guard
        self._timeout_ms = timeout_ms
        self._max_output_chars = max_output_chars
        self._approval_gate = approval_gate
        self._event_bus = event_bus

    def get_definitions(self) -> list[dict]:
        return self._registry.get_definitions()

    def _guard_args(self, name: str, args: dict, risk_level: str) -> dict:
        if not self._guard or risk_level == "safe":
            return args
        checked = dict(args)
        if name in _FILE_TOOLS:
            keys = ("source", "destination") if name == "move_file" else ("path",)
            for key in keys:
                if key in checked:
                    checked[key] = self._guard.guard(checked[key], risk_level)
            if name == "find_files":
                # Validate the glob's static prefix and each returned match in
                # the handler; glob patterns are not plain filesystem paths.
                import os
                pattern = checked.get("pattern", "")
                if os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/"):
                    raise ValueError("Glob pattern must remain within the workspace")
        else:
            # Preserve the legacy guard for external plugins that expose a
            # single conventional path argument. No generic shell sandbox is
            # implied by this check.
            path = checked.get("path") or checked.get("source") or checked.get("destination") or checked.get("cwd")
            if path:
                self._guard.guard(path, risk_level)
        return checked

    async def execute(self, name: str, args: dict, call_id: str) -> ToolResult:
        tool = self._registry.get(name)
        if tool is None:
            suggestions = get_close_matches(name, self._registry.names(), n=3, cutoff=0.6)
            msg = f"Tool '{name}' not found."
            if suggestions:
                msg += f" Did you mean: {', '.join(suggestions)}?"
            return ToolResult.error(call_id, msg)

        errors = validate_schema(tool.definition.parameters, args)
        if errors:
            return ToolResult.error(call_id, f"Invalid arguments for '{name}':\n" + "\n".join(f"  - {e}" for e in errors))

        try:
            self._guard_args(name, args, tool.definition.risk_level)
        except (OSError, ValueError, TypeError) as e:
            return ToolResult.error(call_id, str(e))
        except Exception as e:
            return ToolResult.error(call_id, str(e))

        if self._approval_gate is not None:
            decision = await self._approval_gate.check(name, args, tool.definition.risk_level)
            if not decision.approved:
                if self._event_bus is not None:
                    await self._event_bus.emit(StreamEvent(type="tool_denied", tool_name=name, message=decision.reason))
                return ToolResult.denial(call_id, f"Tool '{name}' denied: {decision.reason}")
            if decision.modified_args is not None:
                args = decision.modified_args

        errors = validate_schema(tool.definition.parameters, args)
        if errors:
            return ToolResult.error(call_id, f"Invalid approved arguments for '{name}':\n" + "\n".join(f"  - {e}" for e in errors))
        try:
            args = self._guard_args(name, args, tool.definition.risk_level)
        except Exception as e:
            return ToolResult.error(call_id, str(e))

        try:
            if asyncio.iscoroutinefunction(tool.handler):
                raw = await asyncio.wait_for(tool.handler(args), timeout=self._timeout_ms / 1000)
            else:
                # A thread keeps blocking handlers from freezing the event
                # loop. A timed-out thread cannot be forcibly terminated;
                # plugins must implement their own cancellation for side effects.
                raw = await asyncio.wait_for(asyncio.to_thread(tool.handler, args), timeout=self._timeout_ms / 1000)
        except asyncio.TimeoutError:
            return ToolResult.error(call_id, f"Tool '{name}' timed out after {self._timeout_ms/1000}s")
        except Exception as e:
            return ToolResult.error(call_id, f"Tool '{name}' failed: {e}")

        formatted = self._format(raw)
        return ToolResult.ok(call_id, formatted)

    def _format(self, raw) -> str:
        if raw is None:
            return "Success."
        if isinstance(raw, str):
            result = raw
        elif isinstance(raw, (dict, list)):
            result = json.dumps(raw, indent=2)
        else:
            result = str(raw)
        if len(result) > self._max_output_chars:
            result = result[:self._max_output_chars] + f"\n\n[... truncated at {self._max_output_chars} characters]"
        return result


def validate_schema(schema: dict, args: dict) -> list[str]:
    errors = []
    schema_type = schema.get("type")
    if schema_type != "object":
        return errors
    if not isinstance(args, dict):
        return [f"arguments should be an object, got {type(args).__name__}"]
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for field in required:
        if field not in args:
            errors.append(f"'{field}' is required but was not provided")
    if schema.get("additionalProperties") is False:
        for key in args.keys() - properties.keys():
            errors.append(f"'{key}' is not an allowed argument")
    for key, value in args.items():
        if key in properties:
            prop = properties[key]
            expected_type = prop.get("type")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"'{key}' should be a string, got {type(value).__name__}")
            elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                errors.append(f"'{key}' should be an integer, got {type(value).__name__}")
            elif expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                errors.append(f"'{key}' should be a number, got {type(value).__name__}")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"'{key}' should be a boolean, got {type(value).__name__}")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"'{key}' should be an array, got {type(value).__name__}")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"'{key}' should be an object, got {type(value).__name__}")
            if "enum" in prop and value not in prop["enum"]:
                errors.append(f"'{key}' must be one of {prop['enum']}, got {value!r}")
    return errors
