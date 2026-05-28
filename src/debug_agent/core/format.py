from __future__ import annotations

import json
from typing import Any


def format_json(data: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def format_text(data: Any, *, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(format_text(v, indent=indent + 1))
            else:
                lines.append(f"{pad}{k}: {v}")
        return "\n".join(lines)
    if isinstance(data, list):
        return "\n".join(format_text(item, indent=indent) for item in data)
    return f"{pad}{data}"


def emit_payload(payload: dict[str, Any], *, text: bool = False, pretty: bool = False) -> None:
    """Print a payload to stdout in either JSON (default) or text format."""
    if text:
        print(format_text(payload))
    else:
        print(format_json(payload, pretty=pretty))


def emit_error(
    error_type: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    text: bool = False,
    pretty: bool = False,
) -> int:
    """Print structured error JSON to stdout and return exit code 1.

    All command error paths should funnel through this helper so callers can
    rely on a uniform ``{"status": "error", "error_type": ..., "message": ...}``
    shape on stdout (never a Python traceback).
    """
    payload: dict[str, Any] = {"status": "error", "error_type": error_type, "message": message}
    if details:
        payload["details"] = details
    emit_payload(payload, text=text, pretty=pretty)
    return 1
