"""Coordinator-owned internal contracts; callers never supply SDK options directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(repr=False)
class RunSpec:
    session_id: str
    model: str
    system_prompt: str
    prompt: str
    max_turns: int
    deadline_monotonic: float
    token_budget_remaining: int
    profile: str = "completion"
    mcp_servers: dict[str, Any] = field(default_factory=dict, repr=False)
    allowed_tools: list[str] = field(default_factory=list)
    workdir: Path | None = None
    local_tools: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class RuntimeEvent:
    kind: str
    data: dict[str, Any]


class RunFailure(Exception):
    """A stable safe failure code, never raw provider/tool exception text."""

    def __init__(self, code: str, status_code: int = 503) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)
