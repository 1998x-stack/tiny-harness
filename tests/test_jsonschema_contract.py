"""Runtime validates nested JSON Schema, not only top-level annotations."""
import pytest

from tiny_harness._guard import FilesystemGuard
from tiny_harness._hitl import ApprovalDecision, ApprovalGate
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry, validate_schema


COMPLEX_SCHEMA = {
    "type": "object",
    "required": ["jobs"],
    "additionalProperties": False,
    "properties": {
        "jobs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["name", "retries"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 3, "pattern": "^[a-z]+"},
                    "retries": {"type": "integer", "minimum": 0, "maximum": 4},
                },
            },
        }
    },
}


def test_nested_object_and_array_constraints_are_enforced():
    valid = {"jobs": [{"name": "build", "retries": 0}]}
    invalid = {"jobs": [
        {"name": "X", "retries": True, "unexpected": "data"},
        {"name": "ok", "retries": 6},
        {"name": "third", "retries": 0},
    ], "extra": "no"}
    assert validate_schema(COMPLEX_SCHEMA, valid) == []
    failures = validate_schema(COMPLEX_SCHEMA, invalid)
    assert len(failures) >= 5
    assert any("jobs.0.name" in f for f in failures)
    assert any("jobs.0.retries" in f for f in failures)
    assert any("jobs.1.retries" in f for f in failures)
    assert any("unexpected" in f for f in failures)
    assert any("extra" in f for f in failures)


def test_anyof_oneof_and_formats():
    schema = {"type": "object", "properties": {
        "choice": {"oneOf": [
            {"type": "integer", "minimum": 1},
            {"type": "string", "minLength": 5},
        ]},
        "email": {"type": "string", "format": "email"},
    }, "required": ["choice", "email"]}
    assert validate_schema(schema, {"choice": "valid", "email": "person@example.com"}) == []
    errors = validate_schema(schema, {"choice": 0, "email": "not-an-email"})
    assert len(errors) == 2


def test_internal_schema_references_work():
    schema = {
        "$defs": {"project": {"type": "string", "minLength": 4}},
        "type": "object",
        "properties": {"project": {"$ref": "#/$defs/project"}},
    }
    assert validate_schema(schema, {"project": "abcd"}) == []
    assert validate_schema(schema, {"project": "a"})


@pytest.mark.parametrize("invalid_schema", [
    {"type": "object", "properties": {"x": {"type": "not-a-type"}}},
    {"type": "array"},
    {"type": "object", "properties": {"x": {"$ref": "https://example.test/schema"}}},
])
def test_bad_tool_schemas_rejected_at_registration(invalid_schema):
    with pytest.raises(ValueError):
        ToolDef("bad_tool", "invalid", invalid_schema, risk_level="read_only")


@pytest.mark.asyncio
async def test_nested_invalid_arguments_never_reach_handler(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("batch", "batch", COMPLEX_SCHEMA, risk_level="read_only"),
        lambda args: executed.append(args) or "done",
    )
    executor = ToolExecutor(registry, FilesystemGuard(str(tmp_path)))
    failure = await executor.execute("batch", {"jobs": [{"name": "x", "retries": -1}]}, "c1")
    assert not failure.success and "jobs.0" in failure.content
    assert executed == []


@pytest.mark.asyncio
async def test_approval_modified_nested_payload_is_revalidated(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register_from_def(
        ToolDef("batch", "batch", COMPLEX_SCHEMA, risk_level="mutation"),
        lambda args: executed.append(args) or "done",
    )

    async def approve(request):
        assert request.args["jobs"][0]["name"] == "valid"
        return ApprovalDecision(
            approved=True, modified_args={"jobs": [{"name": "X", "retries": 0}]}
        )

    executor = ToolExecutor(
        registry, FilesystemGuard(str(tmp_path)), approval_gate=ApprovalGate(handler=approve),
    )
    failure = await executor.execute(
        "batch", {"jobs": [{"name": "valid", "retries": 0}]}, "c2",
    )
    assert not failure.success
    assert "Invalid approved arguments" in failure.content
    assert executed == []


def test_all_args_must_be_objects_even_for_empty_schema():
    assert validate_schema({}, [])
    assert validate_schema({}, {}) == []
