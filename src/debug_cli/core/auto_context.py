"""Aggregate DAP frame state into a single ``StoppedContext`` payload.

The CLI surfaces this same shape from every execution command (``run``,
``step``, ``continue``, ``pause``) so callers get a uniform view of
"what's true at this moment": location, source preview, locals, stack,
recent output, warnings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from debug_cli.core.dap_types import (
    FrameInfo,
    Location,
    SourcePreview,
    StoppedContext,
    VariableInfo,
)

if TYPE_CHECKING:
    from debug_cli.core.dap_client import DapClient


MAX_VALUE_CHARS = 200
_MAX_STACK_FRAMES = 20
_MAX_OUTPUT_LINES = 200


def truncate_value(value: str, *, variables_reference: int = 0) -> str:
    """Truncate scalar string values; leave collection previews intact.

    debugpy renders short, well-formatted previews for collections (e.g.
    ``[1, 2, 3]``) — those are already display-ready and a 200-char cap
    on the preview string would mangle them. Scalars (strings/ints/etc.)
    that happen to be huge get truncated with a marker.
    """
    if variables_reference > 0:
        return value
    if len(value) <= MAX_VALUE_CHARS:
        return value
    return f"{value[:MAX_VALUE_CHARS]}…({len(value)} chars total)"


def _frames_from_response(body: dict[str, Any]) -> list[FrameInfo]:
    frames: list[FrameInfo] = []
    for f in body.get("stackFrames", [])[:_MAX_STACK_FRAMES]:
        source = f.get("source") or {}
        frames.append(
            FrameInfo(
                frame_id=int(f.get("id", 0)),
                function=str(f.get("name", "")),
                file=str(source.get("path", "")),
                line=int(f.get("line", 0)),
            )
        )
    return frames


def _read_source_window(path: str, line: int, context_lines: int) -> list[SourcePreview]:
    """Best-effort source preview around ``line``. Empty list on any failure.

    ``context_lines`` is the number of lines on EACH side of ``line`` to
    include — matching the convention used by ``localize``/``tracebacks``.
    For example, ``context_lines=5`` produces up to 11 entries (5 before,
    the current line, 5 after).
    """
    if not path or context_lines < 0:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    start = max(1, line - context_lines)
    end = min(len(lines), line + context_lines)
    preview: list[SourcePreview] = []
    for ln in range(start, end + 1):
        preview.append(
            SourcePreview(line=ln, text=lines[ln - 1], current=(ln == line)),
        )
    return preview


def _pick_locals_scope(scopes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the scope whose presentationHint marks it as locals.

    Falls back to the first scope if no hint is present (debugpy always
    lists Locals first, but we don't rely on that).
    """
    for scope in scopes:
        hint = scope.get("presentationHint")
        if hint == "locals":
            return scope
    return scopes[0] if scopes else None


def _variables_from_scope(client: DapClient, scope: dict[str, Any]) -> list[VariableInfo]:
    ref = int(scope.get("variablesReference", 0))
    if ref <= 0:
        return []
    body = client.variables(ref)
    out: list[VariableInfo] = []
    for v in body.get("variables", []):
        vref = int(v.get("variablesReference", 0))
        raw_value = str(v.get("value", ""))
        out.append(
            VariableInfo(
                name=str(v.get("name", "")),
                type=str(v.get("type", "")),
                value=truncate_value(raw_value, variables_reference=vref),
                variables_reference=vref,
            )
        )
    return out


def _truncate_output(output: str) -> str:
    if not output:
        return ""
    lines = output.splitlines(keepends=True)
    if len(lines) <= _MAX_OUTPUT_LINES:
        return output
    return "".join(lines[-_MAX_OUTPUT_LINES:])


def build_context(
    client: DapClient,
    thread_id: int,
    *,
    reason: str,
    session_id: str,
    source_context_lines: int = 5,
    recent_output: str = "",
    warnings: list[str] | None = None,
) -> StoppedContext:
    """Aggregate frame state at the current stop into a ``StoppedContext``."""
    stack_body = client.stack_trace(thread_id, levels=_MAX_STACK_FRAMES)
    stack = _frames_from_response(stack_body)

    location: Location | None = None
    source: list[SourcePreview] = []
    locals_: list[VariableInfo] = []

    if stack:
        top = stack[0]
        location = Location(file=top.file, line=top.line, function=top.function)
        source = _read_source_window(top.file, top.line, source_context_lines)
        scopes_body = client.scopes(top.frame_id)
        scope = _pick_locals_scope(scopes_body.get("scopes", []))
        if scope is not None:
            locals_ = _variables_from_scope(client, scope)

    return StoppedContext(
        status="stopped",
        reason=reason,
        session_id=session_id,
        location=location,
        source=source,
        locals=locals_,
        stack=stack,
        output=_truncate_output(recent_output),
        warnings=list(warnings) if warnings else [],
    )
