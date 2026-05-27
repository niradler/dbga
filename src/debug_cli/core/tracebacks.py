from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches the standard "  File "...", line N, in func" header.
_FRAME_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')

# Standard error line: "ExceptionType: message"
_ERROR_RE = re.compile(
    r"^(?P<type>[A-Z]\w*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(?P<msg>.*))?$"
)

# Path fragments that mark a frame as non-user (library) code.
_LIB_MARKERS = ("site-packages", "/lib/python", "\\Lib\\")


@dataclass
class TracebackFrame:
    file: str
    line: int
    func: str
    code: str = ""
    is_user_code: bool = True
    code_context: list[str] = field(default_factory=list)


@dataclass
class ParsedTraceback:
    error_type: str = ""
    message: str = ""
    frames: list[TracebackFrame] = field(default_factory=list)
    deepest_user_frame: TracebackFrame | None = None
    chained: list[ParsedTraceback] = field(default_factory=list)
    raw: str = ""


def _is_library_path(path: str) -> bool:
    return any(marker in path for marker in _LIB_MARKERS)


def _find_deepest_user_frame(frames: list[TracebackFrame]) -> TracebackFrame | None:
    if not frames:
        return None
    for frame in frames:
        if _is_library_path(frame.file):
            frame.is_user_code = False
    for frame in reversed(frames):
        if frame.is_user_code:
            return frame
    return frames[-1]


def _next_code_line(lines: list[str], i: int, skip_patterns: tuple[re.Pattern[str], ...]) -> str:
    """Return the stripped next line as a frame's code, or "" if it would shadow a header."""
    if i + 1 >= len(lines):
        return ""
    nxt = lines[i + 1]
    if any(p.match(nxt) for p in skip_patterns):
        return ""
    return nxt.strip()


def parse_traceback(text: str) -> ParsedTraceback:
    parsed = ParsedTraceback(raw=text)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = _FRAME_RE.match(line)
        if m:
            code = _next_code_line(lines, i, (_FRAME_RE,))
            parsed.frames.append(
                TracebackFrame(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    func=m.group("func"),
                    code=code,
                )
            )
            i += 2 if code else 1
            continue

        merr = _ERROR_RE.match(line.strip())
        if merr and not parsed.error_type:
            parsed.error_type = merr.group("type")
            parsed.message = (merr.group("msg") or "").strip()

        i += 1

    parsed.deepest_user_frame = _find_deepest_user_frame(parsed.frames)
    return parsed
