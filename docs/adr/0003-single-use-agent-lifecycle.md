# ADR 003: Session-Scoped Agent Lifecycle

**Date**: 2026-05-16
**Status**: Accepted (amended 2026-05-16)

## Context

After the Agent produces a result, can the same Agent instance handle another task? Two models considered:

**Model A — Single-use Agent**: Each `agent.run()` is one-shot. After completion, the Agent is done.

**Model B — Session-scoped Agent**: The Agent lives for the duration of a Session, serving multiple user prompts. The Conversation persists across prompts within the Session.

## Decision

**Model B — Session-scoped Agent.** The Agent is created when a Session starts, serves multiple user prompts, and is discarded when the Session ends.

## Rationale

1. **Conversation continuity**: The CLI requires multi-turn interaction. Each new user prompt appends to the same Conversation, giving the Agent memory of earlier actions and decisions. A single-use Agent would lose context between prompts.
2. **Clear lifecycle boundary**: The Agent is Session-scoped — persisted across prompts, discarded at session end. No cross-session state management needed (that's a future concern).
3. **No state reset needed**: Within a Session, the Conversation grows naturally. No need to decide what to reset between prompts — nothing resets. The Conversation is the Agent's continuous memory.
4. **Matches user expectation**: A "session" with an input box naturally implies conversation continuity. Users expect the Agent to remember what was discussed earlier in the same session.

## Consequences

- The Agent introduces a `start_session()` method or is created when the CLI starts.
- Within a Session, `agent.run(prompt)` appends the new user prompt to the existing Conversation. The Loop continues from the current state.
- The Conversation is discarded when the Session ends. No cross-session persistence (MVP scope).
- Tool registration happens once per Session (at Agent creation).
- The single-prompt API (`agent.run("do X")` without a session) is still supported as a shorthand — it creates an implicit session, runs one prompt, and ends.
