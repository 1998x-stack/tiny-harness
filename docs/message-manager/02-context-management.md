# Message Manager: Context Management

## 1. The Problem: Monotonic Growth, Finite Window

Every agent loop iteration adds messages:

```
System prompt (fixed size)
User message (fixed size)
Iteration 1: assistant + tool_result × N
Iteration 2: assistant + tool_result × N
...
Iteration N: assistant + tool_result × N
```

The messages array grows **monotonically** — it only ever gets bigger. But the LLM's context window is **finite** — typically 128K-200K tokens. Eventually, these two facts collide.

When context overflows:
- The API rejects the request (hard failure)
- The LLM provider silently truncates from the beginning (losing the system prompt and user's original request)
- The LLM "forgets" what happened earlier (degraded reasoning)

---

## 2. Context Budget Analysis

### 2.1 Where Tokens Go

For a typical agent task, the budget breakdown:

| Component | % of Budget |
|---|---|
| System prompt | 1-5% |
| User message | <1% |
| LLM reasoning (all iterations) | 10-30% |
| Tool definitions (per-call overhead) | 5-15% |
| Tool results (all iterations) | 50-80% |

**Key insight**: Tool results consume the most tokens. A single large file read (50K tokens) can consume 25% of the budget in one shot. Truncating tool results is the highest-leverage context management strategy.

### 2.2 Growth Patterns

```
Short task (3 iterations, small files):
  2K (system) + 0.5K (user) + 3 × (0.5K reasoning + 1K tool results) = ~7K tokens

Medium task (10 iterations, medium files):
  2K + 0.5K + 10 × (0.5K + 5K) = ~57K tokens

Complex task (20 iterations, large files):
  2K + 0.5K + 20 × (1K + 20K) = ~422K tokens → OVERFLOW
```

Complex tasks with large tool results will overflow. You need a strategy before this happens.

---

## 3. Context Management Strategies

### 3.1 Strategy 0: Do Nothing (MVP)

For the MVP, with a large context window (200K tokens), most tasks won't overflow. Add a warning at 80% capacity and terminate at 100%.

```python
if messages.estimate_tokens() > context_limit * 0.8:
    yield "[Warning: Approaching context limit]"

if messages.estimate_tokens() > context_limit:
    return "Context limit reached. Please restart with a more specific task."
```

### 3.2 Strategy 1: Tool Result Truncation

The simplest effective strategy: truncate large tool results before adding them to messages.

```python
def add_tool_result(self, result: ToolResult, max_tokens: int = 10_000):
    content = result.content
    if estimate_tokens(content) > max_tokens:
        truncated = content[:max_tokens * 4]  # Rough char estimate
        content = truncated + "\n\n[... result truncated. " \
                  f"Original: {estimate_tokens(result.content)} tokens. " \
                  "Use more specific tool parameters to narrow results.]"

    self.messages.append({
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": content
    })
```

**Pros**: Simple, effective, preserves all conversation history
**Cons**: Loses detail from large results; LLM may need to re-query with narrower scope

### 3.3 Strategy 2: Sliding Window

Keep only the most recent N messages, discarding older ones:

```python
SLIDING_WINDOW_SIZE = 50  # messages, not tokens

def keep_last_n_with_system(self, n: int):
    """Keep system message + last N messages."""
    system = self.messages[0]  # Always preserve system message
    recent = self.messages[-(n-1):]  # Keep last N-1
    self.messages = [system] + recent
```

**Pros**: Simple, predictable memory usage
**Cons**: Loses earlier context — the LLM forgets the user's original request, earlier discoveries

**Mitigation**: Before discarding, ask the LLM to summarize the discarded portion and inject the summary.

### 3.4 Strategy 3: Summarization (Compaction)

The most sophisticated strategy: have the LLM summarize old context before discarding it.

```python
async def compact(self, llm: LLMProvider, keep_recent: int = 10):
    """Summarize old messages, keeping only recent ones in full."""
    if len(self.messages) <= keep_recent + 20:
        return  # Not enough to compact

    # Split into "old" and "recent"
    old_messages = [self.messages[0]] + self.messages[1:-keep_recent]
    recent_messages = self.messages[-keep_recent:]

    # Ask LLM to summarize old context
    summary_prompt = [
        {"role": "system", "content": "Summarize the following conversation concisely. "
         "Include: the original task, key decisions made, important discoveries, "
         "current progress, and what remains to be done. Be specific — include "
         "file paths, function names, and data that will be needed going forward."},
        {"role": "user", "content": json.dumps(old_messages)}
    ]

    summary = await llm.generate(messages=summary_prompt, tools=[])

    # Replace old messages with summary
    self.messages = [
        self.messages[0],  # Original system prompt
        {"role": "user", "content": f"[Context Summary]\n{summary.text}"},
        *recent_messages
    ]
```

**Pros**: Preserves semantic knowledge while freeing tokens
**Cons**: Another LLM call (cost + latency); summary may miss important details

### 3.5 Strategy 4: Structured Conversation History

Maintain a structured log of key events alongside the full messages:

```python
@dataclass
class ConversationLog:
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        parts = ["[Conversation Summary]"]
        if self.files_created:
            parts.append(f"Files created: {', '.join(self.files_created)}")
        if self.files_modified:
            parts.append(f"Files modified: {', '.join(self.files_modified)}")
        if self.key_findings:
            parts.append(f"Key findings: {'; '.join(self.key_findings)}")
        if self.decisions_made:
            parts.append(f"Decisions: {'; '.join(self.decisions_made)}")
        return "\n".join(parts)
```

This structured log is cheap to maintain (updated by tool handlers) and provides a concise summary for the LLM.

---

## 4. When to Compact: Trigger Conditions

Compaction is expensive (extra LLM call) and lossy (information lost). Trigger it only when necessary:

### 4.1 Threshold-Based Trigger

```python
def should_compact(self) -> bool:
    tokens = self.estimate_tokens()
    context_limit = self.config.context_limit

    if tokens > context_limit * 0.9:  # 90% full
        return True  # Emergency — compact now
    if tokens > context_limit * 0.7:  # 70% full
        # Plan ahead — compact after current iteration completes
        return True
    return False
```

### 4.2 Progressive Response

Don't jump straight to aggressive compaction. Escalate:

```
< 50%:  Normal operation
50-70%: Log warning, begin truncating tool results more aggressively
70-85%: Compact conversation history (summarize old messages)
85-95%: Aggressive truncation + notify user
> 95%:  Emergency — drop all but essential context, ask LLM to finish
```

---

## 5. What to Keep, What to Discard

When context is tight, prioritize:

### Must Keep (Never Discard)

1. System prompt (defines agent behavior)
2. User's original request (the task itself)
3. Most recent assistant message (current train of thought)
4. Most recent tool results (current working context)

### Should Keep If Possible

5. Key findings from earlier iterations (file paths, search results, decisions)
6. Tool results that the LLM is likely to reference again
7. Error messages that explain why certain approaches failed

### Can Discard

8. Verbose tool results that have been summarized
9. Intermediate reasoning that led to already-completed actions
10. Redundant tool calls (same file read multiple times)
11. "Thinking out loud" text that isn't needed for task completion

---

## 6. Implementation: Context-Aware Message Manager

```python
class ContextAwareMessageManager(MessageManager):
    def __init__(self, system_prompt: str, config: ContextConfig):
        super().__init__(system_prompt)
        self.config = config
        self.compaction_count = 0
        self.conversation_log = ConversationLog()

    async def maybe_compact(self, llm: LLMProvider) -> bool:
        """Check if compaction is needed and perform if so. Returns True if compacted."""
        tokens = self.estimate_tokens()

        if tokens < self.config.context_limit * 0.7:
            return False

        # Emergency: aggressive mode
        if tokens > self.config.context_limit * 0.95:
            await self._emergency_compact(llm)
            return True

        # Normal: summarize old context
        if tokens > self.config.context_limit * 0.7:
            await self._summarize_compact(llm)
            return True

        return False

    async def _summarize_compact(self, llm: LLMProvider):
        """Compact by summarizing the middle of the conversation."""
        # Always keep: system (0), user (1), last 5 messages
        keep_head = 2  # system + user
        keep_tail = 5  # most recent messages
        middle = self.messages[keep_head:-keep_tail]

        if len(middle) < 10:
            return  # Not enough to summarize

        # Build summary prompt
        summary_input = json.dumps(middle, indent=2)
        summary = await llm.generate(
            messages=[{
                "role": "user",
                "content": f"Summarize this conversation segment concisely. "
                           f"Focus on: what was done, what was found, "
                           f"what decisions were made, what files were affected.\n\n"
                           f"{summary_input}"
            }],
            tools=[]
        )

        # Reconstruct messages: head + summary + tail
        self.messages = (
            self.messages[:keep_head] +
            [{"role": "user", "content": f"[Compacted Context]\n{summary.text}"}] +
            self.messages[-keep_tail:]
        )

        self.compaction_count += 1

    async def _emergency_compact(self, llm: LLMProvider):
        """Emergency compaction: drop everything except essentials."""
        # Keep only: system, user, last 3 messages
        # Plus a desperate note to the LLM
        self.messages = (
            self.messages[:2] +
            [{"role": "user", "content":
              "[URGENT] Context limit reached. You must deliver a final answer "
              "based on what you know. Do not use any more tools. "
              "If the task is incomplete, explain what was done and what remains."}] +
            self.messages[-3:]
        )
```

---

## 7. MVP Decisions

For `tiny-harness` MVP:

| Decision | Rationale |
|---|---|
| **Do nothing by default** | 200K context windows are large; most MVP tasks won't overflow |
| **Warn at 80%** | Give user (and LLM) early notice |
| **Truncate tool results at 50K chars** | Simple, prevents runaway growth from large file reads |
| **Error at 100%** | Hard stop before API rejects the request |
| **No compaction in MVP** | Adds complexity (extra LLM call, summary quality concerns) |
| **Conversation log (structured)** | Cheap to maintain; enables future compaction; useful for debugging |
| **Progressive truncation** | Simple escalation: warn → truncate more → hard stop |

### MVP Context Config

```python
@dataclass
class ContextConfig:
    context_limit: int = 200_000     # Model's max context (tokens)
    warn_threshold: float = 0.8      # Warn at 80%
    max_tool_result_tokens: int = 12_500  # ~50K chars
    enable_compaction: bool = False  # Off for MVP
```

---

## 8. When to Add Compaction

Add compaction when you observe:
1. Tasks consistently hitting the context limit
2. Users reporting the agent "forgetting" earlier context
3. Multi-step tasks failing because the LLM loses track of progress

Until then, the overhead (extra LLM calls, summary quality risk) outweighs the benefit.
