# LLM Provider: Error Handling and Retry

## 1. The Problem: LLM APIs Fail

LLM API calls are the most failure-prone part of the agent harness. Failures come from:

| Category | Examples | Can Retry? |
|---|---|---|
| **Rate limits** | 429 Too Many Requests | Yes — wait and retry |
| **Server errors** | 500, 502, 503, 504 | Yes — retry with backoff |
| **Overload** | 529 Overloaded | Yes — wait longer |
| **Auth failures** | 401 Unauthorized | No — bad API key |
| **Bad request** | 400 Invalid messages format | No — fix the code |
| **Context overflow** | 400 Context length exceeded | No — messages too large |
| **Network errors** | Timeout, connection reset | Yes — retry |

The harness must distinguish between transient failures (retryable) and permanent failures (fatal).

---

## 2. Error Taxonomy

```python
class LLMError(Exception):
    """Base class for LLM provider errors."""
    pass

class RetryableLLMError(LLMError):
    """Temporary error — retry with backoff."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after  # Seconds to wait (from Retry-After header)

class RateLimitError(RetryableLLMError):
    """429 — too many requests."""
    pass

class ServerError(RetryableLLMError):
    """5xx — server-side issue."""
    pass

class OverloadedError(RetryableLLMError):
    """529 — provider overloaded."""
    pass

class NetworkError(RetryableLLMError):
    """Connection timeout, reset, DNS failure."""
    pass

class FatalLLMError(LLMError):
    """Permanent error — do not retry."""
    pass

class AuthError(FatalLLMError):
    """401, 403 — invalid or expired credentials."""
    pass

class BadRequestError(FatalLLMError):
    """400 — request is malformed (our bug)."""
    pass

class ContextOverflowError(FatalLLMError):
    """400 with context length exceeded."""
    pass
```

---

## 3. Retry Strategy

### 3.1 Exponential Backoff with Jitter

```python
import random
import asyncio

class LLMRetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0       # seconds
    max_delay: float = 60.0       # seconds
    backoff_factor: float = 2.0   # multiplier per retry

async def retry_with_backoff(
    fn: callable,
    config: LLMRetryConfig,
) -> LLMResponse:
    last_error = None

    for attempt in range(config.max_retries + 1):
        try:
            return await fn()
        except RetryableLLMError as e:
            last_error = e

            if attempt == config.max_retries:
                break  # All retries exhausted

            # Calculate delay: base * backoff^attempt + jitter
            delay = min(
                config.base_delay * (config.backoff_factor ** attempt),
                config.max_delay
            )
            jitter = random.uniform(0, delay * 0.5)
            wait_time = delay + jitter

            # If the server told us how long to wait, respect it
            if e.retry_after:
                wait_time = max(wait_time, e.retry_after)

            await asyncio.sleep(wait_time)

    raise FatalLLMError(f"All {config.max_retries} retries exhausted. "
                        f"Last error: {last_error}")
```

### 3.2 Visual Timeline

```
Attempt 0: Immediate call
  ├─ 200 OK → return result
  ├─ 429 → wait 1-1.5s
Attempt 1: Retry 1
  ├─ 200 OK → return result
  ├─ 429 → wait 2-3s
Attempt 2: Retry 2
  ├─ 200 OK → return result
  ├─ 429 → wait 4-6s
Attempt 3: Retry 3
  ├─ 200 OK → return result
  └─ 429 → raise FatalLLMError (retries exhausted)
```

---

## 4. Provider-Level Error Wrapping

### 4.1 Anthropic Provider with Retry

```python
class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, retry_config: LLMRetryConfig | None = None):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.retry_config = retry_config or LLMRetryConfig()

    async def generate(self, messages, tools=None) -> LLMResponse:
        return await retry_with_backoff(
            lambda: self._generate_inner(messages, tools),
            self.retry_config
        )

    async def _generate_inner(self, messages, tools):
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=16384,
                messages=self._convert_messages(messages),
                system=self._extract_system(messages),
                tools=self._convert_tools(tools) if tools else None,
            )
            return self._parse_response(response)

        except anthropic.RateLimitError as e:
            retry_after = float(e.response.headers.get("Retry-After", 0)) if e.response else None
            raise RateLimitError(str(e), retry_after=retry_after)

        except anthropic.APIStatusError as e:
            if e.status_code == 401 or e.status_code == 403:
                raise AuthError(f"Authentication failed: {e}")
            if e.status_code == 400:
                if "context_length" in str(e).lower() or "too many tokens" in str(e).lower():
                    raise ContextOverflowError(str(e))
                raise BadRequestError(f"Bad request: {e}")
            if e.status_code >= 500:
                raise ServerError(f"Server error ({e.status_code}): {e}")
            if e.status_code == 529:
                retry_after = float(e.response.headers.get("Retry-After", 0)) if e.response else None
                raise OverloadedError(str(e), retry_after=retry_after)
            raise FatalLLMError(f"Unexpected API error ({e.status_code}): {e}")

        except (asyncio.TimeoutError, ConnectionError) as e:
            raise NetworkError(f"Network error: {e}")
```

### 4.2 Error Mapping Pattern

Every provider implementation follows the same pattern:

```
Provider SDK Exception → Harness Error Type
  RateLimitError       → RateLimitError (retryable)
  500-599              → ServerError (retryable)
  529                  → OverloadedError (retryable)
  Timeout/Connect      → NetworkError (retryable)
  401/403              → AuthError (fatal)
  400 (context)        → ContextOverflowError (fatal)
  400 (other)          → BadRequestError (fatal)
  Everything else      → FatalLLMError (fatal)
```

---

## 5. Token-Aware Retry (Context Overflow)

Context overflow is a special case. It's not a transient error — retrying with the same messages will fail again. But it IS recoverable: compact the context and retry.

```python
class TokenAwareRetryWrapper:
    """Wraps an LLM provider with context management on overflow."""

    def __init__(self, provider: LLMProvider, message_manager: MessageManager):
        self.provider = provider
        self.message_manager = message_manager

    async def generate(self, messages, tools=None) -> LLMResponse:
        try:
            return await self.provider.generate(messages, tools)
        except ContextOverflowError:
            # Compact context and retry
            await self.message_manager.compact(self.provider)
            return await self.provider.generate(
                self.message_manager.to_list(),
                tools
            )
```

---

## 6. Circuit Breaker (Beyond MVP)

For production, a circuit breaker prevents hammering a failing service:

```python
from enum import Enum
import time

class CircuitState(Enum):
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failing — reject calls immediately
    HALF_OPEN = "half_open"    # Testing if service recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0

    async def call(self, fn: callable):
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise FatalLLMError("Circuit breaker open — service unavailable")

        try:
            result = await fn()
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
            return result
        except RetryableLLMError:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            raise
```

---

## 7. Fallback Strategies

### 7.1 Model Fallback

If the primary model fails, try a fallback:

```python
class FallbackProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback

    async def generate(self, messages, tools=None) -> LLMResponse:
        try:
            return await self.primary.generate(messages, tools)
        except FatalLLMError as e:
            print(f"Primary provider failed: {e}. Trying fallback...")
            return await self.fallback.generate(messages, tools)
```

### 7.2 Provider Fallback

If Anthropic is down, try OpenAI:

```python
providers = [
    AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"], model="claude-sonnet-4-20250514"),
    OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"], model="gpt-4o"),
]

for provider in providers:
    try:
        result = await provider.generate(messages, tools)
        break
    except RetryableLLMError:
        continue  # Try next provider
```

**MVP decision**: No fallback. Single provider. If it's down, the agent fails. Fallback adds complexity (different tool formats, different system prompt behavior) without being essential.

---

## 8. Observability

### 8.1 Metrics to Track

```python
@dataclass
class LLMCallMetrics:
    provider: str
    model: str
    duration_ms: int
    input_tokens: int
    output_tokens: int
    retry_count: int
    error_type: str | None
    success: bool
```

### 8.2 Logging

```python
async def generate_with_metrics(self, messages, tools=None) -> LLMResponse:
    start = time.time()
    retries = 0

    try:
        response = await self.generate(messages, tools)
        metrics = LLMCallMetrics(
            provider="anthropic",
            model=self.model,
            duration_ms=int((time.time() - start) * 1000),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            retry_count=retries,
            success=True
        )
        log_metrics(metrics)
        return response

    except Exception as e:
        metrics = LLMCallMetrics(
            provider="anthropic",
            model=self.model,
            duration_ms=int((time.time() - start) * 1000),
            input_tokens=0,
            output_tokens=0,
            retry_count=retries,
            error_type=type(e).__name__,
            success=False
        )
        log_metrics(metrics)
        raise
```

---

## 9. MVP Decisions

| Decision | Rationale |
|---|---|
| **3 retries with exponential backoff** | Industry standard; covers transient failures |
| **Jitter on retry delays** | Prevents thundering herd on recovery |
| **Respect Retry-After headers** | Provider knows best when to retry |
| **Classify errors as retryable/fatal** | Don't retry auth failures or bad requests |
| **No circuit breaker** | Premature for MVP; 3 retries is sufficient |
| **No provider fallback** | Single provider; add when multi-provider is needed |
| **Log all LLM calls with metrics** | Essential for debugging and cost tracking |
| **Context overflow triggers compaction** | Only non-retryable error with a recovery path |
