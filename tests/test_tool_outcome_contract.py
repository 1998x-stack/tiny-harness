"""Typed built-in outcomes preserve execution status without parsing arbitrary text."""
import shlex
import sys
from types import SimpleNamespace

import pytest

from tiny_harness import Agent, Config, Prompt
from tiny_harness._llm import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from tiny_harness._tool_outcome import ToolOutcome
from tiny_harness._tools import ToolDef, ToolResult
from tiny_harness.tools.files import read_file
from tiny_harness.tools.shell import run_command_async


def test_outcome_contract_is_explicit():
    assert ToolOutcome.ok("Error: a quoted line in a source file").success is True
    assert ToolOutcome.error("not found").success is False


@pytest.mark.asyncio
async def test_executor_accepts_typed_result_and_never_guesses_from_text(tmp_path):
    agent = Agent(Prompt("fixture"), Config(model="test", api_key="unused", workspace=str(tmp_path)))
    agent.tools.register_from_def(
        ToolDef("reported_error", "fixture", {"type": "object"}, risk_level="read_only"),
        lambda args: ToolOutcome.error("Something unavailable"),
    )
    agent.tools.register_from_def(
        ToolDef("quoted_text", "fixture", {"type": "object"}, risk_level="read_only"),
        lambda args: "Error: this is an expected literal output",
    )
    fail = await agent._tool_executor.execute("reported_error", {}, "e1")
    success = await agent._tool_executor.execute("quoted_text", {}, "e2")
    assert not fail.success and not fail.denied
    assert fail.content == "Something unavailable"
    assert success.success and success.content.startswith("Error:")


@pytest.mark.asyncio
async def test_missing_file_is_error_only_in_structured_agent_path(tmp_path):
    agent = Agent(Prompt("fixture"), Config(model="test", api_key="unused", workspace=str(tmp_path)))
    agent.load_skill("files")
    result = await agent._tool_executor.execute("read_file", {"path": "missing.txt"}, "f1")
    assert not result.success
    assert "not found" in result.content.lower()
    assert isinstance(read_file({"path": str(tmp_path / "missing.txt")}), str)


@pytest.mark.asyncio
async def test_invalid_search_regex_is_failure_in_agent_path(tmp_path):
    agent = Agent(Prompt("fixture"), Config(model="test", api_key="unused", workspace=str(tmp_path)))
    agent.load_skill("search")
    result = await agent._tool_executor.execute("search_content", {"pattern": "[invalid"}, "s1")
    assert not result.success
    assert "invalid" in result.content.lower() or "failed" in result.content.lower()


@pytest.mark.asyncio
async def test_nonzero_shell_exit_is_failure_without_giving_up_stdout(tmp_path):
    agent = Agent(Prompt("fixture"), Config(
        model="test", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
    ))
    agent.load_skill("shell")
    command = shlex.quote(sys.executable) + ' -c "import sys; print(42); sys.exit(7)"'
    result = await agent._tool_executor.execute("run_command", {"command": command}, "c1")
    assert not result.success
    assert "[exit code: 7]" in result.content
    assert "42" in result.content
    raw = await run_command_async({"command": command, "cwd": str(tmp_path)})
    assert isinstance(raw, str) and "[exit code: 7]" in raw


@pytest.mark.asyncio
async def test_nonzero_shell_status_exhausts_agent_error_budget(tmp_path):
    agent = Agent(Prompt("fixture"), Config(
        model="test", api_key="unused", workspace=str(tmp_path),
        no_hitl=True, allow_unsafe_shell=True,
        max_errors=1, max_consecutive_errors=1,
    ))
    agent.load_skill("shell")
    command = shlex.quote(sys.executable) + ' -c "import sys; sys.exit(8)"'

    class FakeLLM:
        stream_count = 0
        degraded_count = 0

        async def generate_stream(self, messages, tools=None):
            self.stream_count += 1
            yield LLMStreamChunk(type="tool_call_end", tool_call=ToolCallRequest(
                id="failed-shell", name="run_command", arguments={"command": command},
            ))

        async def generate(self, messages, tools=None):
            self.degraded_count += 1
            assert tools == []
            assert [msg["tool_call_id"] for msg in messages if msg["role"] == "tool"] == ["failed-shell"]
            return LLMResponse(text="Recovered", tool_calls=[],
                               usage=TokenUsage(input_tokens=1, output_tokens=1), finish_reason="stop")

    fake = FakeLLM()
    agent._llm_provider = fake
    assert await agent.run("run fixture") == "Recovered"
    assert fake.stream_count == fake.degraded_count == 1
    assert "[exit code: 8]" in next(
        msg["content"] for msg in agent._messages.to_list() if msg["role"] == "tool"
    )
