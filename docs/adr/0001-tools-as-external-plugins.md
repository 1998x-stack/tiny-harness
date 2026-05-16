# ADR 001: Tools as External Plugins

**Date**: 2026-05-16
**Status**: Accepted

## Context

The Agent needs filesystem access to be useful. The question: should file tools (read, write, list, search, delete) ship as part of the Agent Core, or should every tool — even file access — be explicitly registered by the user?

Two models considered:

**Model A — Built-in tools**: The Agent ships with file tools. `Agent(config).run("do X")` can immediately read and write files. Convenient, but the Agent has filesystem authority by default.

**Model B — Plugin model**: The Agent Core ships with zero tools. The user must explicitly register every tool. `register_file_tools(agent)` is a convenience helper, but the user always controls what's available.

## Decision

**Model B — Plugin model.** The Agent Core contains only the Loop, MessageManager, Config, LLMProvider, and an empty ToolRegistry. No tools are available until registered.

## Rationale

1. **Security by default**: An Agent with no tools cannot do anything. The user must consciously grant capabilities. This prevents accidental filesystem access.
2. **Clean boundaries**: The ToolRegistry is the container (part of Agent Core). Individual tools are not. This separation is clear in both code and concept.
3. **User control**: Different use cases need different tool sets. A coding agent needs file tools; a chatbot doesn't. The user decides.
4. **Testability**: The Agent Core can be tested in isolation (no filesystem dependency). Tools are tested separately.
5. **Convenience is recoverable**: A `register_file_tools(agent)` helper preserves the convenience of the built-in model without baking tools into the Agent.

## Consequences

- The user must explicitly register tools before the Agent can do anything useful. The "hello world" requires at least one tool registration.
- A convenience helper (`register_file_tools`) is expected, documented, and tested — but it's a helper, not part of the Agent.
- Security-sensitive deployments can create Agents with zero or minimal tool sets.
