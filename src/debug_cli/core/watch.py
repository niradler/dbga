from __future__ import annotations

import contextlib
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from debug_cli.core.process import kill_tree


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


def scan_process(
    cmd: list[str],
    *,
    patterns: list[str],
    timeout: float,
    until: int | None = None,
    context_lines: int = 1,
) -> Iterator[WatchMatch]:
    """Run ``cmd`` and yield WatchMatch for each pattern hit on its merged stdout/stderr.

    Stops when: the process exits, ``until`` matches have been yielded, or
    wall-clock ``timeout`` is exceeded. The process tree is killed in ``finally``
    to avoid orphans.
    """
    compiled = [(p, re.compile(p)) for p in patterns]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=(sys.platform != "win32"),
    )
    deadline = time.monotonic() + timeout
    history: list[str] = []
    yielded = 0
    try:
        assert proc.stdout is not None
        line_number = 0
        for raw_line in proc.stdout:
            if time.monotonic() > deadline:
                return
            line = raw_line.rstrip("\n")
            history.append(line)
            line_number += 1
            for raw_pattern, regex in compiled:
                m = regex.search(line)
                if m is None:
                    continue
                start = max(0, line_number - 1 - context_lines)
                end = min(len(history), line_number + context_lines)
                yield WatchMatch(
                    line_number=line_number,
                    pattern=raw_pattern,
                    match=m.group(0),
                    groups=tuple(g if g is not None else "" for g in m.groups()),
                    surrounding_lines=history[start:end],
                    timestamp_ms=_now_ms(),
                )
                yielded += 1
                if until is not None and yielded >= until:
                    return
    finally:
        if proc.poll() is None:
            kill_tree(proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()
