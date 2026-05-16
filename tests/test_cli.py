# tests/test_cli.py
import sys
import pytest
from unittest.mock import patch
from argparse import Namespace
from tiny_harness.cli import parse_args, _run_one_shot


def test_parse_args_one_shot():
    with patch.object(sys, 'argv', ['tiny-harness', 'Hello']):
        args = parse_args()
        assert args.prompt == 'Hello'


def test_parse_args_no_prompt():
    with patch.object(sys, 'argv', ['tiny-harness']):
        args = parse_args()
        assert args.prompt is None


def test_parse_args_with_options():
    with patch.object(sys, 'argv', [
        'tiny-harness', 'Hello',
        '--model', 'claude-opus',
        '--workspace', '/tmp/project',
        '--max-iterations', '10',
        '--skills', 'files',
    ]):
        args = parse_args()
        assert args.prompt == 'Hello'
        assert args.model == 'claude-opus'
        assert args.workspace == '/tmp/project'
        assert args.max_iterations == 10
        assert args.skills == 'files'
        assert args.provider == 'deepseek'
        assert args.api_base_url == 'https://api.deepseek.com/v1'


def test_parse_args_with_provider():
    with patch.object(sys, 'argv', ['tiny-harness', 'hi', '--provider', 'deepseek', '--api-base-url', 'https://api.deepseek.com/v1']):
        args = parse_args()
        assert args.provider == 'deepseek'
        assert args.api_base_url == 'https://api.deepseek.com/v1'


def test_parse_args_tui_flag():
    with patch.object(sys, 'argv', ['tiny-harness', '--tui']):
        args = parse_args()
        assert args.tui is True
        assert args.prompt is None


def test_parse_args_tui_with_prompt():
    with patch.object(sys, 'argv', ['tiny-harness', '--tui', 'hello']):
        args = parse_args()
        assert args.tui is True
        assert args.prompt == 'hello'


@pytest.mark.asyncio
async def test_run_one_shot_displays_iteration():
    from tiny_harness import Agent, Prompt, Config

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            from tiny_harness._llm import LLMStreamChunk
            yield LLMStreamChunk(type="text_delta", content="Hello")
            yield LLMStreamChunk(type="text_delta", content=" world")

    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._llm_provider = FakeLLM()

    args = Namespace(prompt="Hi")
    with patch("builtins.print") as mock_print:
        await _run_one_shot(args, agent)

    printed = "".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
    assert "Hello world" in printed


@pytest.mark.asyncio
async def test_run_one_shot_handles_tool_events():
    from tiny_harness import Agent, Prompt, Config, ToolDef
    from tiny_harness._llm import LLMStreamChunk, ToolCallRequest

    class FakeLLM:
        async def generate_stream(self, messages, tools=None):
            yield LLMStreamChunk(type="tool_call_end", tool_call=ToolCallRequest(id="call_1", name="echo", arguments={"msg": "hi"}))

    agent = Agent(prompt=Prompt("test"), config=Config(model="t", api_key="k", workspace="/tmp"))
    agent._llm_provider = FakeLLM()
    agent.tools.register_from_def(
        ToolDef(name="echo", description="Echo", parameters={"type": "object", "properties": {"msg": {"type": "string"}}}),
        lambda args: f"echo: {args.get('msg', '')}",
    )

    args = Namespace(prompt="Hi")
    with patch("builtins.print") as mock_print:
        await _run_one_shot(args, agent)

    printed = "".join(str(call.args[0]) for call in mock_print.call_args_list if call.args)
    assert "echo" in printed


def test_main_routes_to_tui():
    with patch.object(sys, 'argv', ['tiny-harness', '--tui', '--api-key-env', 'FAKE_KEY']):
        with patch.dict('os.environ', {'FAKE_KEY': 'test-key'}):
            with patch('tiny_harness.cli.asyncio.run') as mock_run:
                from tiny_harness.cli import main
                main()
                assert mock_run.called


def test_main_routes_to_session():
    with patch.object(sys, 'argv', ['tiny-harness', '--api-key-env', 'FAKE_KEY']):
        with patch.dict('os.environ', {'FAKE_KEY': 'test-key'}):
            with patch('tiny_harness.cli.asyncio.run') as mock_run:
                from tiny_harness.cli import main
                main()
                assert mock_run.called
