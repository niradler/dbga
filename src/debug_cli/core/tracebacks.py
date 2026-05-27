from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Matches the standard "  File "...", line N, in func" header.
_FRAME_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')

# SyntaxError header has no ", in <func>" suffix.
_FRAME_NO_FUNC_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)$')

# pytest --tb=short style: "path/to/file.py:12: in test_bar"
_PYTEST_FRAME_RE = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):\s*in\s+(?P<func>\S+)$")

# Standard error line: "ExceptionType: message"
_ERROR_RE = re.compile(
    r"^(?P<type>[A-Z]\w*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(?P<msg>.*))?$"
)

# pytest-style error line: "E   ExceptionType: message"
_PYTEST_ERROR_RE = re.compile(
    r"^E\s+(?P<type>[A-Z]\w*(?:Error|Exception|Warning|Exit|Interrupt))"
    r"(?::\s*(?P<msg>.*))?$"
)

_CHAINED_DIVIDERS = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
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


def _parse_standard_segment(text: str) -> ParsedTraceback:
    """Parse a single (non-chained) traceback segment using the standard format."""
    parsed = ParsedTraceback(raw=text)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = _FRAME_RE.match(line)
        if m:
            code = _next_code_line(lines, i, (_FRAME_RE, _FRAME_NO_FUNC_RE))
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

        m2 = _FRAME_NO_FUNC_RE.match(line)
        if m2:
            # SyntaxError-style header (no "in <func>"). Synthesize func="<module>".
            code = _next_code_line(lines, i, (_FRAME_RE, _FRAME_NO_FUNC_RE))
            parsed.frames.append(
                TracebackFrame(
                    file=m2.group("file"),
                    line=int(m2.group("line")),
                    func="<module>",
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

    return parsed


def _parse_pytest_short_segment(text: str) -> ParsedTraceback:
    """Parse a pytest --tb=short style segment."""
    parsed = ParsedTraceback(raw=text)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _PYTEST_FRAME_RE.match(line)
        if m:
            code = _next_code_line(lines, i, (_PYTEST_FRAME_RE, _PYTEST_ERROR_RE))
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

        merr = _PYTEST_ERROR_RE.match(line)
        if merr and not parsed.error_type:
            parsed.error_type = merr.group("type")
            parsed.message = (merr.group("msg") or "").strip()

        i += 1

    return parsed


def _parse_segment(text: str) -> ParsedTraceback:
    """Parse one segment, trying standard format first and falling back to pytest-short."""
    parsed = _parse_standard_segment(text)
    if not parsed.frames:
        pytest_parsed = _parse_pytest_short_segment(text)
        if pytest_parsed.frames:
            parsed = pytest_parsed
            parsed.raw = text
    parsed.deepest_user_frame = _find_deepest_user_frame(parsed.frames)
    return parsed


def _split_chained(text: str) -> list[str]:
    """Split traceback text on chained-exception divider lines."""
    segments: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() in _CHAINED_DIVIDERS:
            if buf:
                segments.append("\n".join(buf))
                buf = []
        else:
            buf.append(line)
    if buf:
        segments.append("\n".join(buf))
    return segments


def parse_traceback(text: str) -> ParsedTraceback:
    segments = _split_chained(text)
    if not segments:
        return ParsedTraceback(raw=text)

    # Python prints chained exceptions oldest-first; the LAST segment is the outermost.
    parsed_segments = [_parse_segment(seg) for seg in segments]
    outermost = parsed_segments[-1]
    # Earlier segments link in as `chained`, reverse-chronological (most recent first).
    outermost.chained = list(reversed(parsed_segments[:-1]))
    outermost.raw = text
    return outermost


def attach_source(
    parsed: ParsedTraceback,
    *,
    context_lines: int = 2,
    cwd: Path | None = None,
) -> None:
    """Fill `code_context` for every frame (recursing into chained tracebacks)."""
    base = cwd if cwd is not None else Path.cwd()
    for frame in parsed.frames:
        path = Path(frame.file)
        if not path.is_absolute():
            path = base / path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        start = max(0, frame.line - 1 - context_lines)
        end = min(len(lines), frame.line + context_lines)
        frame.code_context = lines[start:end]

    for child in parsed.chained:
        attach_source(child, context_lines=context_lines, cwd=cwd)
