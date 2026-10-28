"""Tool path declarations are independent of tool names and validated twice."""
import os

import pytest

from tiny_harness._guard import FilesystemGuard
from tiny_harness._hitl import ApprovalDecision, ApprovalGate
from tiny_harness._tools import ToolDef, ToolExecutor, ToolRegistry


def _registry(path_args=("filename",), props=None):
    registry = ToolRegistry()
    observed = []
    schema = {"type": "object", "properties": props or {
        "filename": {"type": "string"},
        "path": {"type": "string"},
        "source": {"type": "string"},
        "destination": {"type": "string"},
    }}
    registry.register_from_def(
        ToolDef("custom_import", "fixture", schema,
                risk_level="read_only", path_args=path_args),
        lambda args: observed.append(dict(args)) or str(args),
    )
    return registry, observed


def test_path_args_require_explicit_string_fields():
    for path_args in [("missing",), ("filename", "filename"), ("filename", "integer")]:
        with pytest.raises(ValueError, match="path_args"):
            ToolDef(
                "bad", "fixture",
                {"type": "object", "properties": {
                    "filename": {"type": "string"},
                    "integer": {"type": "integer"},
                }},
                path_args=path_args,
            )


@pytest.mark.asyncio
async def test_custom_path_argument_uses_workspace_not_process_cwd(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    monkeypatch.chdir(other)
    registry, observed = _registry()
    result = await ToolExecutor(registry, FilesystemGuard(str(workspace))).execute(
        "custom_import", {"filename": "data.txt"}, "call-1",
    )
    assert result.success
    assert observed == [{"filename": str(workspace / "data.txt")}]
    assert not (other / "data.txt").exists()


@pytest.mark.asyncio
async def test_unknown_tool_checks_every_conventional_field(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("private")
    registry, observed = _registry(path_args=())
    executor = ToolExecutor(registry, FilesystemGuard(str(workspace)))
    denied = await executor.execute(
        "custom_import",
        {"path": "safe.txt", "source": str(external), "destination": "ok.txt"},
        "call-2",
    )
    assert not denied.success
    assert "outside" in denied.content
    assert observed == []


@pytest.mark.asyncio
async def test_all_declared_paths_block_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "outside.txt"
    secret.write_text("private")
    (workspace / "alias").symlink_to(secret)
    registry, observed = _registry(path_args=("filename",))
    executor = ToolExecutor(registry, FilesystemGuard(str(workspace)))
    denied = await executor.execute("custom_import", {"filename": "alias"}, "call-3")
    assert not denied.success
    assert observed == []


@pytest.mark.asyncio
async def test_approval_modified_arguments_are_validated_and_recannonicalized(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    registry, observed = _registry(path_args=("filename",))

    async def approve(request):
        return ApprovalDecision(approved=True, modified_args={"filename": str(outside)})

    registry.get("custom_import").definition.risk_level = "mutation"
    executor = ToolExecutor(
        registry, FilesystemGuard(str(workspace)),
        approval_gate=ApprovalGate(handler=approve),
    )
    result = await executor.execute(
        "custom_import", {"filename": "safe.txt"}, "call-4",
    )
    assert not result.success and "outside" in result.content
    assert observed == []


@pytest.mark.asyncio
async def test_registry_helper_accepts_custom_path_args(tmp_path):
    registry = ToolRegistry()
    registry.register_tool(
        "artifact_read", "reads a fixture",
        {"type": "object", "properties": {"asset_path": {"type": "string"}}},
        lambda args: args["asset_path"],
        risk_level="read_only", path_args=("asset_path",),
    )
    result = await ToolExecutor(registry, FilesystemGuard(str(tmp_path))).execute(
        "artifact_read", {"asset_path": "nested/file.txt"}, "call-5",
    )
    assert result.success and result.content == str(tmp_path / "nested/file.txt")
