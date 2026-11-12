# tiny_harness/_tools.py
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

    def __post_init__(self) -> None:
        allowed = {"safe", "read_only", "mutation", "destructive", "dangerous"}
        if self.risk_level not in allowed:
            raise ValueError(f"Unknown tool risk level: {self.risk_level!r}")


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
        """Convenience method: register a tool without creating a ToolDef explicitly."""
        self.register_from_def(ToolDef(name=name, description=description, parameters=parameters, risk_level=risk_level), handler)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        return [{"name": t.definition.name, "description": t.definition.description, "input_schema": t.definition.parameters} for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())


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
            args = self._guard_paths(args, tool.definition.risk_level)
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
                    return ToolResult.error(
                        call_id,
                        f"Invalid arguments for '{name}':\n" + "\n".join(f"  - {e}" for e in errors),
                    )
                try:
                    args = self._guard_paths(args, tool.definition.risk_level)
                except Exception as e:
                    return ToolResult.error(call_id, str(e))

        try:
            if asyncio.iscoroutinefunction(tool.handler):
                invocation = tool.handler(args)
            else:
                invocation = asyncio.to_thread(tool.handler, args)
            raw = await asyncio.wait_for(invocation, timeout=self._timeout_ms / 1000)
        except asyncio.TimeoutError:
            return ToolResult.error(call_id, f"Tool '{name}' timed out after {self._timeout_ms/1000}s")
        except Exception as e:
            return ToolResult.error(call_id, f"Tool '{name}' failed: {e}")

        formatted = self._format(raw)
        if _is_error_output(formatted):
            return ToolResult.error(call_id, formatted)
        return ToolResult.ok(call_id, formatted)

    def _guard_paths(self, args: dict, risk_level: str) -> dict:
        if not self._guard or risk_level == "safe":
            return args
        guarded = dict(args)
        default_op = "delete" if risk_level == "destructive" else "write" if risk_level == "mutation" else "read"
        operations = {
            "path": default_op,
            "source": "read",
            "destination": "write",
            "cwd": "read",
        }
        for field, operation in operations.items():
            path = guarded.get(field)
            if path:
                guarded[field] = self._guard.guard(path, operation)
        return guarded

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


def _is_error_output(output: str) -> bool:
    stripped = output.lstrip()
    return stripped.startswith("Error:") or stripped.startswith("[exit code:")
