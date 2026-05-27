"""Shared dataclasses describing DAP session state.

Lives in its own module so ``dap_session`` and ``auto_context`` can both
import from it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Breakpoint:
    file: Path
    line: int
    condition: str | None = None


@dataclass
class FrameInfo:
    frame_id: int
    function: str
    file: str
    line: int


@dataclass
class VariableInfo:
    name: str
    type: str
    value: str  # already truncated
    variables_reference: int = 0
    length: int | None = None  # for collections


@dataclass
class Location:
    file: str
    line: int
    function: str


@dataclass
class SourcePreview:
    line: int
    text: str
    current: bool = False


@dataclass
class StoppedContext:
    status: str  # "stopped" | "exited" | "terminated" | "error"
    reason: str = ""  # "breakpoint" | "step" | "exception" | "pause" | "entry"
    session_id: str = "default"
    location: Location | None = None
    source: list[SourcePreview] = field(default_factory=list)
    locals: list[VariableInfo] = field(default_factory=list)
    stack: list[FrameInfo] = field(default_factory=list)
    output: str = ""
    warnings: list[str] = field(default_factory=list)
    exit_code: int | None = None
