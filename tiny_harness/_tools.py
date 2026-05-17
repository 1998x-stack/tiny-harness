# tiny_harness/_tools.py
from __future__ import annotations
import json
import asyncio
from dataclasses import dataclass
from difflib import get_close_matches
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tiny_harness._guard import FilesystemGuard


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

    @classmethod
    def ok(cls, call_id: str, content: str) -> "ToolResult":
        return cls(success=True, tool_call_id=call_id, content=content)

    @classmethod
    def error(cls, call_id: str, message: str) -> "ToolResult":
        return cls(success=False, tool_call_id=call_id, content=message)


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
    def __init__(self, registry: ToolRegistry, guard: "FilesystemGuard", timeout_ms: int = 30_000, max_output_chars: int = 50_000):
        self._registry = registry
        self._guard = guard
        self._timeout_ms = timeout_ms
        self._max_output_chars = max_output_chars

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

        if self._guard and tool.definition.risk_level != "safe":
            path = args.get("path") or args.get("source") or args.get("destination")
            if not path:
                path = args.get("cwd")
            if path:
                try:
                    op = "delete" if tool.definition.risk_level == "destructive" else "write" if tool.definition.risk_level == "mutation" else "read"
                    self._guard.guard(path, op)
                except Exception as e:
                    return ToolResult.error(call_id, str(e))

        try:
            if asyncio.iscoroutinefunction(tool.handler):
                raw = await asyncio.wait_for(tool.handler(args), timeout=self._timeout_ms / 1000)
            else:
                raw = tool.handler(args)
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
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"'{key}' should be an integer, got {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
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
