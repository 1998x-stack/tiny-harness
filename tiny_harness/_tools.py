from __future__ import annotations
import json
import asyncio
from dataclasses import dataclass
from difflib import get_close_matches
from collections.abc import Callable
from typing import TYPE_CHECKING

from tiny_harness._events import StreamEvent
from tiny_harness._tool_outcome import ToolOutcome

if TYPE_CHECKING:
    from tiny_harness._guard import FilesystemGuard
    from tiny_harness._hitl import ApprovalGate
    from tiny_harness._events import EventBus


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    risk_level: str = "mutation"
    # Filesystem locations in the schema, independent of a tool's Python name.
    # All fields listed here are canonicalized before the handler is invoked.
    path_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.risk_level not in ("safe", "read_only", "mutation", "destructive", "dangerous"):
            raise ValueError(f"Unknown tool risk_level: {self.risk_level!r}")
        if not isinstance(self.path_args, tuple) or len(set(self.path_args)) != len(self.path_args):
            raise ValueError("path_args must be a tuple of distinct schema property names")
        props = self.parameters.get("properties", {})
        for field in self.path_args:
            if not isinstance(field, str) or not field or props.get(field, {}).get("type") != "string":
                raise ValueError(f"path_args entry {field!r} must be a declared string property")


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

    def register_tool(self, name: str, description: str, parameters: dict, handler: Callable, risk_level: str = "mutation", path_args: tuple[str, ...] = ()) -> None:
        self.register_from_def(ToolDef(
            name=name, description=description, parameters=parameters,
            risk_level=risk_level, path_args=path_args,
        ), handler)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self) -> list[dict]:
        return [{"name": t.definition.name, "description": t.definition.description, "input_schema": t.definition.parameters} for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())


# Compatibility for third-party tools registered before path_args existed.
# New tools should declare ToolDef(path_args=("filename", ...)).
_LEGACY_FILE_PATH_KEYS = {
    "read_file": ("path",),
    "write_file": ("path",),
    "list_directory": ("path",),
    "find_files": ("path",),
    "delete_file": ("path",),
    "create_directory": ("path",),
    "move_file": ("source", "destination"),
    "search_content": ("path",),
}
_DEFAULT_WORKSPACE_PATH_TOOLS = frozenset((
    "list_directory", "find_files", "search_content", "run_command",
))
_CONVENTIONAL_PATH_KEYS = ("path", "source", "destination", "cwd")

class ToolExecutor:
    def __init__(self, registry: ToolRegistry, guard: "FilesystemGuard", timeout_ms: int = 30_000, max_output_chars: int = 50_000, approval_gate: "ApprovalGate | None" = None, event_bus: "EventBus | None" = None, allow_unsafe_shell: bool = False):
        self._registry = registry
        self._guard = guard
        self._timeout_ms = timeout_ms
        self._max_output_chars = max_output_chars
        self._approval_gate = approval_gate
        self._event_bus = event_bus
        self._allow_unsafe_shell = allow_unsafe_shell

    def get_definitions(self) -> list[dict]:
        return self._registry.get_definitions()

    def _guard_args(self, tool: Tool, args: dict) -> dict:
        if not self._guard:
            return dict(args)
        name = tool.definition.name
        checked = dict(args)

        # Legacy conventional fields are checked for compatibility. A ToolDef
        # may additionally declare arbitrary path fields such as "filename".
        # Resolve EVERY field, not just the first nonempty one.
        fields = set(tool.definition.path_args)
        fields.update(_LEGACY_FILE_PATH_KEYS.get(name, ()))
        fields.update(k for k in _CONVENTIONAL_PATH_KEYS if k in checked)
        if name == "run_command":
            fields.add("cwd")

        for field in fields:
            if field in checked:
                value = checked[field]
                if not isinstance(value, str):
                    raise ValueError(f"Filesystem path {field!r} must be a string")
                checked[field] = self._guard.guard(value, tool.definition.risk_level)
            elif field == "cwd" and name == "run_command":
                checked["cwd"] = self._guard.guard(".", tool.definition.risk_level)
            elif field == "path" and name in _DEFAULT_WORKSPACE_PATH_TOOLS:
                checked["path"] = self._guard.guard(".", tool.definition.risk_level)

        if name == "find_files":
            # Glob patterns need validation beyond ordinary path arguments.
            import os
            pattern = checked.get("pattern", "")
            if os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/"):
                raise ValueError("Glob pattern must remain within the workspace")
        return checked

    async def execute(self, name: str, args: dict, call_id: str) -> ToolResult:
        tool = self._registry.get(name)
        if tool is None:
            suggestions = get_close_matches(name, self._registry.names(), n=3, cutoff=0.6)
            msg = f"Tool '{name}' not found."
            if suggestions:
                msg += f" Did you mean: {', '.join(suggestions)}?"
            return ToolResult.error(call_id, msg)

        if (self._approval_gate is None and name == "run_command"
                and not self._allow_unsafe_shell):
            return ToolResult.denial(
                call_id,
                "Shell tool requires approval or explicit allow_unsafe_shell=True.",
            )

        errors = validate_schema(tool.definition.parameters, args)
        if errors:
            return ToolResult.error(call_id, f"Invalid arguments for '{name}':\n" + "\n".join(f"  - {e}" for e in errors))

        try:
            self._guard_args(tool, args)
        except Exception as e:
            return ToolResult.error(call_id, str(e))

        if self._approval_gate is not None:
            try:
                decision = await self._approval_gate.check(name, args, tool.definition.risk_level)
            except Exception as e:
                # An approval UI failure must never authorize the operation.
                return ToolResult.denial(call_id, f"Tool '{name}' approval failed: {e}")
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
            args = self._guard_args(tool, args)
        except Exception as e:
            return ToolResult.error(call_id, str(e))

        try:
            if asyncio.iscoroutinefunction(tool.handler):
                raw = await asyncio.wait_for(tool.handler(args), timeout=self._timeout_ms / 1000)
            else:
                # Thread timeouts prevent event-loop blocking, but cannot
                # terminate a worker already performing side effects.
                raw = await asyncio.wait_for(asyncio.to_thread(tool.handler, args), timeout=self._timeout_ms / 1000)
        except asyncio.TimeoutError:
            return ToolResult.error(call_id, f"Tool '{name}' timed out after {self._timeout_ms/1000}s")
        except Exception as e:
            return ToolResult.error(call_id, f"Tool '{name}' failed: {e}")

        if isinstance(raw, ToolOutcome):
            content = self._format(raw.content)
            return ToolResult.ok(call_id, content) if raw.success else ToolResult.error(call_id, content)
        return ToolResult.ok(call_id, self._format(raw))

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
