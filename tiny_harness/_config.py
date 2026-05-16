# tiny_harness/_config.py
from dataclasses import dataclass


@dataclass
class AgentConfig:
    model: str
    api_key: str
    workspace: str
    max_iterations: int = 25
    max_errors: int = 10
    max_consecutive_errors: int = 3
    timeout_ms: int = 30_000
    max_tool_result_chars: int = 50_000


class Prompt:
    def __init__(self, base: str):
        self._sections: list[str] = [base]

    def append(self, section: str) -> None:
        self._sections.append(section)

    def to_string(self) -> str:
        return "\n\n".join(self._sections)
