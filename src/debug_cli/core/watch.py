from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WatchMatch:
    line_number: int
    pattern: str
    match: str
    groups: tuple[str, ...]
    surrounding_lines: list[str] = field(default_factory=list)
    timestamp_ms: int = 0


def _now_ms() -> int:
    return int(time.time() * 1000)


def scan_file(
    path: Path,
    *,
    patterns: list[str],
    context_lines: int = 1,
) -> Iterator[WatchMatch]:
    """Scan a file once for regex patterns, yielding a WatchMatch per hit."""
    compiled = [(p, re.compile(p)) for p in patterns]
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    for idx, line in enumerate(lines):
        line_number = idx + 1
        for raw_pattern, regex in compiled:
            m = regex.search(line)
            if m is None:
                continue
            start = max(0, line_number - 1 - context_lines)
            end = min(total, line_number + context_lines)
            yield WatchMatch(
                line_number=line_number,
                pattern=raw_pattern,
                match=m.group(0),
                groups=tuple(g if g is not None else "" for g in m.groups()),
                surrounding_lines=lines[start:end],
                timestamp_ms=_now_ms(),
            )
