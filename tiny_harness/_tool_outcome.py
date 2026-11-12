"""Explicit tool handler outcomes.

Handlers may continue returning legacy strings for successful calls. Built-in
handlers additionally expose a typed outcome so executor status never depends
on text beginning with "Error:" or on a shell output convention.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolOutcome:
    success: bool
    content: str

    @classmethod
    def ok(cls, content: str) -> "ToolOutcome":
        return cls(success=True, content=content)

    @classmethod
    def error(cls, content: str) -> "ToolOutcome":
        return cls(success=False, content=content)
