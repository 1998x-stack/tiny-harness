# ADR 002: Prompt as First-Class Artifact

**Date**: 2026-05-16
**Status**: Accepted

## Context

The system prompt defines the Agent's personality, tool usage rules, constraints, and behavior. Where does it live in the API?

**Option A — Prompt inside Config**: `AgentConfig.system_prompt` is a string field alongside `model`, `max_iterations`, etc. Simple: one object configures everything.

**Option B — Prompt as a peer to Config**: `Agent(prompt=Prompt(...), config=AgentConfig(...))`. The Prompt is a first-class parameter, separate from runtime configuration.

## Decision

**Option B — Prompt as a first-class artifact, separate from Config.**

## Rationale

1. **Different lifecycles**: Config parameters (model, iterations, temperature) are tuned once and rarely change. Prompts are iterated, versioned, A/B tested, and swapped frequently. Coupling them forces retuning of config when the prompt changes.
2. **Different concerns**: Config is "how the Agent runs." Prompt is "who the Agent is." These are orthogonal.
3. **Reusability**: The same Prompt can be used with different Configs (different models, different iteration limits). The same Config can be used with different Prompts (coding assistant vs debugger).
4. **Testing**: Prompts should be tested independently of runtime parameters. A prompt test suite shouldn't need to know about model selection or iteration limits.
5. **Version control**: Prompts are text artifacts that benefit from diffing, review, and changelogs — like code. Config parameters are values, not text.

## Consequences

- The Agent constructor takes two arguments (`prompt`, `config`) instead of one.
- Prompt can be a string (simple), a file path (loaded at creation), or a template object (future).
- Config no longer has a `system_prompt` field. The system prompt is exclusively the Prompt's responsibility.
