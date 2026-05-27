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
