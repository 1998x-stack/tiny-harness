# LLM Provider: Abstraction and Implementation

## 1. First Principles: What Does the LLM Provider Do?

The LLM provider is the **bridge between the harness and an actual language model**. Its job:

```
Input:  messages[] + tools[] + config
Output: text chunks (streamed) + tool calls (if any)
```

From the harness's perspective, the LLM provider is a black box. The harness doesn't care whether it's calling Claude, GPT-4, or a local model. It only cares about the interface.

---

## 2. The Provider Interface

### 2.1 Minimal Contract

```python
class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream a response from the LLM."""
        ...
```

### 2.2 Response Model

```python
@dataclass
class LLMResponse:
    text: str | None                         # Full text (null if only tool calls)
    tool_calls: list[ToolCallRequest]         # Tool calls requested by LLM
    usage: TokenUsage                         # Token consumption
    model: str                                # Actual model used
    finish_reason: str                        # "stop", "tool_calls", "length"

    @property
    def is_final(self) -> bool:
        """True if this is a final answer (no tool calls)."""
        return len(self.tool_calls) == 0


@dataclass
class ToolCallRequest:
    id: str                                   # LLM-generated unique ID
    name: str                                 # Tool name
    arguments: dict                           # Parsed JSON arguments


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0               # Prompt caching (Anthropic)
    cache_write_tokens: int = 0


@dataclass
class LLMStreamChunk:
    type: str                                 # "text" | "tool_call_start" | "tool_call_delta" | "tool_call_end"
    content: str | None = None
    tool_call: ToolCallRequest | None = None
```

---

## 3. Streaming Implementation

### 3.1 Why Stream?

Without streaming, the harness must wait for the entire LLM response before showing anything to the user. With a 30-second generation time, this is a terrible experience.

Streaming delivers tokens as they're generated. The user sees the agent "thinking" in real time.

### 3.2 Stream Chunk Types

```
text_delta:         "I'll search..." " for that" " file..."  (incremental text)
tool_call_start:    {id: "toolu_001", name: "read_file"}     (LLM decided to use tool)
tool_call_delta:    {"path": "/tmp/da...}                     (building arguments)
tool_call_end:      {id: "toolu_001", arguments: complete}    (tool call ready)
```

### 3.3 Stream Handler

```python
class StreamHandler:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.text_buffer = ""
        self.tool_calls: dict[str, ToolCallBuilder] = {}

    async def handle_chunk(self, chunk: LLMStreamChunk):
        match chunk.type:
            case "text_delta":
                self.text_buffer += chunk.content
                await self.event_bus.emit("text_delta", chunk.content)

            case "tool_call_start":
                builder = ToolCallBuilder(id=chunk.tool_call.id,
                                          name=chunk.tool_call.name)
                self.tool_calls[chunk.tool_call.id] = builder
                await self.event_bus.emit("tool_call_start", {
                    "id": chunk.tool_call.id,
                    "name": chunk.tool_call.name
                })

            case "tool_call_delta":
                builder = self.tool_calls[chunk.tool_call.id]
                builder.add_args_json(chunk.content)

            case "tool_call_end":
                builder = self.tool_calls[chunk.tool_call.id]
                completed = builder.build()
                await self.event_bus.emit("tool_call_end", {
                    "id": completed.id,
                    "name": completed.name,
                    "arguments": completed.arguments
                })

    def get_response(self) -> LLMResponse:
        return LLMResponse(
            text=self.text_buffer.strip() or None,
            tool_calls=[b.build() for b in self.tool_calls.values()],
            ...
        )
```

---

## 4. Anthropic Provider Implementation

### 4.1 Core Implementation

```python
class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def generate(self, messages, tools=None) -> LLMResponse:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=16384,
            messages=self._convert_messages(messages),
            system=self._extract_system(messages),
            tools=self._convert_tools(tools) if tools else None,
        )
        return self._parse_response(response)

    async def generate_stream(self, messages, tools=None) -> AsyncIterator[LLMStreamChunk]:
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=16384,
            messages=self._convert_messages(messages),
            system=self._extract_system(messages),
            tools=self._convert_tools(tools) if tools else None,
        ) as stream:
            async for event in stream:
                yield self._convert_event(event)

            final = stream.get_final_message()
            # Yield final usage info
            yield LLMStreamChunk(
                type="usage",
                content=json.dumps({
                    "input": final.usage.input_tokens,
                    "output": final.usage.output_tokens,
                })
            )

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        """Extract non-system messages."""
        return [m for m in messages if m["role"] != "system"]

    def _extract_system(self, messages: list[dict]) -> str:
        """Extract system prompt (Anthropic uses a separate parameter)."""
        for m in messages:
            if m["role"] == "system":
                return m["content"]
        return ""

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert to Anthropic tool format."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"]
            }
            for t in tools
        ]

    def _parse_response(self, response) -> LLMResponse:
        text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))

        return LLMResponse(
            text=text or None,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            model=response.model,
            finish_reason=response.stop_reason or "stop"
        )
```

### 4.2 Anthropic-Specific: System Prompt Separation

Anthropic's API uses a separate `system` parameter instead of a system role message:

```python
# Anthropic API format
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    system="You are a helpful assistant.",  # Separate parameter
    messages=[
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
)

# vs OpenAI API format (system is just another message)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]
)
```

The provider handles this conversion internally. The harness uses a uniform format.

---

## 5. OpenAI Provider Implementation

```python
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate(self, messages, tools=None) -> LLMResponse:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # Uses system role directly
            tools=self._convert_tools(tools) if tools else None,
            temperature=0,
            max_tokens=16384,
        )
        return self._parse_response(response.choices[0])

    async def generate_stream(self, messages, tools=None):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self._convert_tools(tools) if tools else None,
            temperature=0,
            max_tokens=16384,
            stream=True,
        )
        async for chunk in stream:
            yield self._convert_chunk(chunk)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert to OpenAI tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"]
                }
            }
            for t in tools
        ]

    def _parse_response(self, choice) -> LLMResponse:
        msg = choice.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                ))

        return LLMResponse(
            text=msg.content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=0,   # Not available in stream mode
                output_tokens=0,
            ),
            model=self.model,
            finish_reason=choice.finish_reason or "stop"
        )
```

---

## 6. Provider Selection

### 6.1 Factory Pattern

```python
def create_provider(config: AgentConfig) -> LLMProvider:
    api_key = config.api_key or os.environ.get(f"{config.provider.upper()}_API_KEY")

    if not api_key:
        raise ConfigError(f"No API key for provider '{config.provider}'")

    match config.provider:
        case "anthropic":
            return AnthropicProvider(api_key=api_key, model=config.model)
        case "openai":
            return OpenAIProvider(api_key=api_key, model=config.model)
        case "openrouter":
            return OpenRouterProvider(api_key=api_key, model=config.model)
        case _:
            raise ConfigError(f"Unknown provider: {config.provider}")
```

### 6.2 Auto-Detection

```python
def auto_detect_provider() -> str:
    """Detect which provider is available from environment."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    raise ConfigError("No LLM API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
```

---

## 7. MVP Decisions

| Decision | Rationale |
|---|---|
| **Single provider (Anthropic)** | Simplify MVP; add others when needed |
| **Streaming always on** | Essential UX; no reason to turn off for MVP |
| **Provider interface is an ABC** | Enables swapping providers without changing harness code |
| **No prompt caching yet** | Anthropic-specific optimization; add when cost becomes a concern |
| **No multi-model routing** | One model for all calls; routing is optimization, not necessity |
| **Messages format conversion in provider** | Harness uses uniform format; provider handles API differences |
| **Async-only interface** | Python's asyncio is the standard for I/O-bound agent loops |
