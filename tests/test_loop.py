# tests/test_loop.py
import pytest
from tiny_harness._loop import ErrorBudget, LoopDetector
from tiny_harness._config import AgentConfig, Prompt
from tiny_harness._messages import MessageManager
from tiny_harness._events import EventBus
from tiny_harness._tools import ToolResult
from tiny_harness._loop import AgentLoop
from tiny_harness._llm import LLMStreamChunk, ToolCallRequest


def test_error_budget_records_errors():
    budget = ErrorBudget(max_total=10, max_consecutive=3)
    assert budget.record_error() is True
    assert budget.record_error() is True


def test_error_budget_exhausted_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_error_budget_exhausted_total():
    budget = ErrorBudget(max_total=2, max_consecutive=10)
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_error_budget_success_resets_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    budget.record_error()
    budget.record_success()
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_loop_detector_rejects_repeated_calls():
    detector = LoopDetector(max_repeats=2)
    args = {"path": "/tmp/x"}
    assert detector.check("read_file", args) is True
    assert detector.check("read_file", args) is False


def test_loop_detector_allows_different_args():
    detector = LoopDetector(max_repeats=2)
    assert detector.check("read_file", {"path": "/tmp/a"}) is True
    assert detector.check("read_file", {"path": "/tmp/b"}) is True


def test_loop_detector_allows_same_args_different_tool():
    detector = LoopDetector(max_repeats=2)
    args = {"path": "/tmp/x"}
    assert detector.check("read_file", args) is True
    assert detector.check("write_file", args) is True


def test_loop_detector_reset():
    detector = LoopDetector(max_repeats=2)
    detector.check("read_file", {"path": "/tmp/x"})
    detector.check("read_file", {"path": "/tmp/x"})
    detector.reset()
    assert detector.check("read_file", {"path": "/tmp/x"}) is True


def test_error_budget_reset():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    budget.record_error()
    budget.record_error()
    assert budget.record_error() is False
    budget.reset()
    assert budget.record_error() is True


class FakeProvider:
    def __init__(self, responses):
        self.responses = responses
        self.idx = 0
        self.calls = 0

    async def generate_stream(self, messages, tools=None):
        self.calls += 1
        for chunk in self.responses[min(self.idx, len(self.responses)-1)]:
            yield chunk
        self.idx += 1

    async def generate(self, messages, tools=None):
        self.calls += 1
        from tiny_harness._llm import LLMResponse, TokenUsage
        return LLMResponse(text="final_after_degrade", tool_calls=[], usage=TokenUsage(input_tokens=5, output_tokens=3), finish_reason="stop")


class FakeExecutor:
    def __init__(self, results=None):
        self.results = results or []
        self.idx = 0
    def get_definitions(self):
        return []
    async def execute(self, name, args, call_id):
        r = self.results[min(self.idx, len(self.results)-1)]
        self.idx += 1
        return r


@pytest.mark.asyncio
async def test_loop_returns_final_answer():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp")
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    provider = FakeProvider(responses=[[LLMStreamChunk(type="text_delta", content="Hello!")]])
    executor = FakeExecutor()
    loop = AgentLoop(config, messages, provider, executor, events)
    result = await loop.run("Hi")
    assert "Hello!" in result
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_loop_executes_tool_and_continues():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp")
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    tc = ToolCallRequest(id="t1", name="echo", arguments={"msg": "hi"})
    provider = FakeProvider(responses=[
        [LLMStreamChunk(type="text_delta", content="let me check"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="got result")],
    ])
    executor = FakeExecutor(results=[ToolResult.ok("t1", "echo: hi")])
    loop = AgentLoop(config, messages, provider, executor, events)
    result = await loop.run("check")
    assert "got result" in result
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_loop_max_iterations_triggers_degraded_finish():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp", max_iterations=2)
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    tc = ToolCallRequest(id="t1", name="echo", arguments={"msg": "x"})
    provider = FakeProvider(responses=[
        [LLMStreamChunk(type="text_delta", content="a"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="b"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
    ])
    executor = FakeExecutor(results=[
        ToolResult.ok("t1", "ok"),
        ToolResult.ok("t1", "ok"),
    ])
    loop = AgentLoop(config, messages, provider, executor, events)
    result = await loop.run("do stuff")
    assert "final_after_degrade" in result


@pytest.mark.asyncio
async def test_loop_error_budget_exhausted_degrade():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp", max_errors=2, max_consecutive_errors=2)
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    tc = ToolCallRequest(id="t1", name="failing", arguments={})
    provider = FakeProvider(responses=[
        [LLMStreamChunk(type="text_delta", content="try1"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="try2"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
    ])
    executor = FakeExecutor(results=[
        ToolResult.error("t1", "fail1"),
        ToolResult.error("t1", "fail2"),
    ])
    loop = AgentLoop(config, messages, provider, executor, events)
    result = await loop.run("do")
    assert "final_after_degrade" in result


@pytest.mark.asyncio
async def test_loop_detector_intervenes():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp", max_iterations=10, max_errors=20, max_consecutive_errors=20)
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    tc = ToolCallRequest(id="t1", name="stuck", arguments={"path": "/tmp/x"})
    provider = FakeProvider(responses=[
        [LLMStreamChunk(type="text_delta", content="a"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="b"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="c"), LLMStreamChunk(type="tool_call_end", tool_call=tc)],
        [LLMStreamChunk(type="text_delta", content="fixed")],
    ])
    fail = ToolResult.error("t1", "fail")
    executor = FakeExecutor(results=[fail, fail, fail, ToolResult.ok("t1", "ok")])
    loop = AgentLoop(config, messages, provider, executor, events)
    result = await loop.run("help")
    assert "different approach" in result.lower() or "fixed" in result


@pytest.mark.asyncio
async def test_loop_llm_error_terminates():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp")
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()

    class ErrorProvider:
        async def generate_stream(self, messages, tools=None):
            raise RuntimeError("API down")
            yield
        async def generate(self, messages, tools=None):
            raise RuntimeError("API down")

    loop = AgentLoop(config, messages, ErrorProvider(), FakeExecutor(), events)
    result = await loop.run("hi")
    assert "LLM error" in result or "stopped" in result.lower()


@pytest.mark.asyncio
async def test_loop_emits_iteration_events():
    config = AgentConfig(model="t", api_key="k", workspace="/tmp")
    messages = MessageManager(Prompt("Be helpful."))
    events = EventBus()
    iterations = []
    async def capture(e):
        if e.type == "iteration":
            iterations.append(e)
    events.subscribe(capture)

    provider = FakeProvider(responses=[[LLMStreamChunk(type="text_delta", content="done")]])
    loop = AgentLoop(config, messages, provider, FakeExecutor(), events)
    await loop.run("hi")
    assert len(iterations) == 1
    assert iterations[0].num == 1
