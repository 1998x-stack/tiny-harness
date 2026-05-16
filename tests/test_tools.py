# tests/test_tools.py
import pytest
from tiny_harness._tools import ToolDef, Tool, ToolRegistry, ToolExecutor, ToolResult
from tiny_harness._guard import FilesystemGuard


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register_from_def(
        ToolDef(name="echo", description="Echo input", parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}),
        lambda message: message,
    )
    r.register_from_def(
        ToolDef(name="failing", description="Always fails", parameters={"type": "object", "properties": {}}),
        lambda: (_ for _ in ()).throw(RuntimeError("always fails")),
    )
    return r


def test_register_and_get_tool(registry):
    tool = registry.get("echo")
    assert tool is not None
    assert tool.definition.name == "echo"


def test_get_nonexistent_tool(registry):
    assert registry.get("nonexistent") is None


def test_get_definitions(registry):
    defs = registry.get_definitions()
    assert len(defs) == 2
    assert defs[0]["name"] == "echo"


def test_names(registry):
    names = registry.names()
    assert "echo" in names
    assert "failing" in names


@pytest.mark.asyncio
async def test_execute_returns_success_result(registry):
    guard = FilesystemGuard("/tmp")
    executor = ToolExecutor(registry, guard, timeout_ms=5000, max_output_chars=10000)
    result = await executor.execute("echo", {"message": "hello"}, "tc1")
    assert result.success is True
    assert result.tool_call_id == "tc1"
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_execute_tool_not_found(registry):
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=10000)
    result = await executor.execute("nonexistent", {}, "tc1")
    assert result.success is False
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_execute_schema_validation_fails(registry):
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=10000)
    result = await executor.execute("echo", {}, "tc1")
    assert result.success is False


@pytest.mark.asyncio
async def test_execute_handler_exception_becomes_error_result(registry):
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=10000)
    result = await executor.execute("failing", {}, "tc1")
    assert result.success is False
    assert "always fails" in result.content
