# tests/test_tools.py
import asyncio
import pytest
from tiny_harness._tools import ToolDef, Tool, ToolRegistry, ToolExecutor, ToolResult, validate_schema
from tiny_harness._guard import FilesystemGuard


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register_from_def(
        ToolDef(name="echo", description="Echo input", parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}),
        lambda args: args["message"],
    )
    r.register_from_def(
        ToolDef(name="failing", description="Always fails", parameters={"type": "object", "properties": {}}),
        lambda args: (_ for _ in ()).throw(RuntimeError("always fails")),
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


@pytest.mark.asyncio
async def test_execute_tool_timeout(registry):
    async def slow_handler(args):
        await asyncio.sleep(10)
        return "done"
    registry.register_from_def(
        ToolDef(name="slow", description="Slow tool", parameters={"type": "object", "properties": {}}),
        slow_handler,
    )
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=100, max_output_chars=100)
    result = await executor.execute("slow", {}, "tc1")
    assert result.success is False
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_execute_result_truncation(registry):
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=20)
    result = await executor.execute("echo", {"message": "x" * 100}, "tc1")
    assert result.success is True
    assert "truncated" in result.content.lower()
    assert len(result.content) < 200


@pytest.mark.asyncio
async def test_execute_tool_suggests_similar_names(registry):
    registry.register_from_def(
        ToolDef(name="read_file", description="Read file", parameters={"type": "object", "properties": {}}),
        lambda: "ok",
    )
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("read_fil", {}, "tc1")
    assert result.success is False
    assert "read_file" in result.content


@pytest.mark.asyncio
async def test_execute_guard_blocks_outside_write(registry):
    registry.register_from_def(
        ToolDef(name="write_outside", description="Write outside", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level="mutation"),
        lambda args: "ok",
    )
    guard = FilesystemGuard("/tmp/tiny_harness_test_workspace")
    executor = ToolExecutor(registry, guard, timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("write_outside", {"path": "/etc/hostname"}, "tc1")
    assert result.success is False
    assert "outside" in result.content.lower() or "denied" in result.content.lower()


@pytest.mark.asyncio
async def test_execute_guard_allows_write_inside(registry):
    registry.register_from_def(
        ToolDef(name="write_inside", description="Write inside", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level="mutation"),
        lambda args: f"ok:{args['path']}",
    )
    guard = FilesystemGuard("/tmp")
    executor = ToolExecutor(registry, guard, timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("write_inside", {"path": "/tmp/test_file.txt"}, "tc1")
    assert result.success is True


@pytest.mark.asyncio
async def test_execute_destructive_tool_blocked_outside(registry):
    registry.register_from_def(
        ToolDef(name="delete_thing", description="Delete", parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level="destructive"),
        lambda args: "deleted",
    )
    guard = FilesystemGuard("/tmp/tiny_harness_test")
    executor = ToolExecutor(registry, guard, timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("delete_thing", {"path": "/etc/passwd"}, "tc1")
    assert result.success is False


@pytest.mark.asyncio
async def test_execute_format_none_returns_success(registry):
    registry.register_from_def(
        ToolDef(name="none_tool", description="Returns None", parameters={"type": "object", "properties": {}}),
        lambda args: None,
    )
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("none_tool", {}, "tc1")
    assert result.success is True
    assert "Success" in result.content


@pytest.mark.asyncio
async def test_execute_format_dict(registry):
    registry.register_from_def(
        ToolDef(name="dict_tool", description="Returns dict", parameters={"type": "object", "properties": {}}),
        lambda args: {"key": "value"},
    )
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("dict_tool", {}, "tc1")
    assert result.success is True
    assert "key" in result.content


@pytest.mark.asyncio
async def test_execute_sync_handler(registry):
    def sync_handler(args):
        return args["message"].upper()
    registry.register_from_def(
        ToolDef(name="sync_tool", description="Sync handler", parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}),
        sync_handler,
    )
    executor = ToolExecutor(registry, FilesystemGuard("/tmp"), timeout_ms=5000, max_output_chars=100)
    result = await executor.execute("sync_tool", {"message": "hello"}, "tc1")
    assert result.success is True
    assert "HELLO" in result.content


def test_validate_schema_required_missing():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    errors = validate_schema(schema, {})
    assert len(errors) == 1
    assert "x" in errors[0]


def test_validate_schema_wrong_type():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    errors = validate_schema(schema, {"x": "not_an_int"})
    assert len(errors) == 1
    assert "integer" in errors[0]


def test_validate_schema_enum():
    schema = {"type": "object", "properties": {"x": {"type": "string", "enum": ["a", "b"]}}}
    errors = validate_schema(schema, {"x": "c"})
    assert len(errors) == 1
    assert "one of" in errors[0]


def test_validate_schema_valid():
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "count": {"type": "integer"}}, "required": ["name"]}
    errors = validate_schema(schema, {"name": "test", "count": 42})
    assert len(errors) == 0


def test_validate_schema_non_object():
    schema = {"type": "array"}
    errors = validate_schema(schema, {})
    assert len(errors) == 0


def test_validate_schema_array_type():
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}
    errors = validate_schema(schema, {"items": "not_array"})
    assert len(errors) == 1


def test_validate_schema_boolean_type():
    schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
    errors = validate_schema(schema, {"flag": "not_bool"})
    assert len(errors) == 1


def test_validate_schema_number_type():
    schema = {"type": "object", "properties": {"val": {"type": "number"}}}
    errors = validate_schema(schema, {"val": "string"})
    assert len(errors) == 1


def test_tool_result_ok():
    result = ToolResult.ok("tc1", "done")
    assert result.success is True
    assert result.tool_call_id == "tc1"
    assert result.content == "done"


def test_tool_result_error():
    result = ToolResult.error("tc2", "failed")
    assert result.success is False
    assert result.content == "failed"


def test_tool_creation():
    tool = Tool(definition=ToolDef(name="test", description="desc", parameters={}), handler=lambda args: None)
    assert tool.definition.name == "test"


def test_register_overwrites_existing():
    reg = ToolRegistry()
    reg.register_from_def(ToolDef(name="x", description="a", parameters={}), lambda: "a")
    reg.register_from_def(ToolDef(name="x", description="b", parameters={}), lambda: "b")
    tool = reg.get("x")
    assert tool.handler() == "b"
